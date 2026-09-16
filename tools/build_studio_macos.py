"""Allowlisted Mac source kit or a native Mac preview bundle. No credentials."""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.build_studio_release import stage, DENIED
from tools.build_macos_audio import build_helper

TESTS = ('test_audio_io.py', 'test_calendar_background.py', 'test_deadlines.py', 'test_gpa_tracker.py',
         'test_moodle_calendar.py', 'test_macos_audio.py',
         'test_macos_port.py', 'test_macos_ui.py', 'test_meeting_prompt.py',
         'test_slide_analysis.py', 'test_studio_dock.py', 'test_studio_router.py',
         'test_study_guide.py', 'test_study_sessions.py', 'test_week_calendar.py', 'test_whisper_pipeline.py',
         'test_whisper_models.py', 'test_prayer_widget.py', 'test_updates.py', 'test_update_download.py')


def stage_macos(destination):
    stage(destination)
    for name in ('requirements-studio.txt', 'requirements-macos.txt',
                 'lecture_studio_macos.spec', 'macos-entitlements.plist', 'MACOS.md'):
        shutil.copy2(ROOT / 'packaging' / name, destination / 'packaging' / name)
    (destination / 'tools').mkdir(exist_ok=True)
    for name in ('build_studio_release.py', 'build_studio_macos.py', 'build_macos_audio.py', 'test_studio_package.py'):
        shutil.copy2(ROOT / 'tools' / name, destination / 'tools' / name)
    (destination / 'tests').mkdir(exist_ok=True)
    for name in TESTS:
        shutil.copy2(ROOT / 'tests' / name, destination / 'tests' / name)
    native = destination / 'native/macos'
    native.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / 'native/macos/LectureAudioCapture.swift', native)
    workflow = destination / '.github/workflows'
    workflow.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / '.github/workflows/macos-studio.yml', workflow)


def checksum(path):
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    path.with_suffix(path.suffix + '.sha256').write_text(digest + '  ' + path.name + '\n', encoding='ascii')


def zip_app(package, archive):
    if archive.exists():
        raise FileExistsError(archive)
    # Preserve required symlinks, executable permissions and signing metadata.
    subprocess.run(['/usr/bin/ditto', '-c', '-k', '--sequesterRsrc', '--keepParent',
                    str(package), str(archive)], check=True)


def submit_notarization(artifact, profile):
    result = subprocess.run(['/usr/bin/xcrun', 'notarytool', 'submit', str(artifact),
                             '--keychain-profile', profile, '--wait', '--output-format', 'json'],
                            check=True, capture_output=True, text=True, timeout=1800)
    response = json.loads(result.stdout)
    if response.get('status') != 'Accepted':
        raise RuntimeError('Apple did not accept notarization. Submission ID: ' + str(response.get('id', 'unknown')))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-only', action='store_true', help='Create a clean source kit on any host, not an executable.')
    parser.add_argument('--ci', action='store_true', help='Noninteractive diagnostics: skip real Keychain access, report it as untested.')
    parser.add_argument('--smoke-model', type=Path, help='Cached public Whisper model for a real generated-speech transcription test.')
    parser.add_argument('--sign-identity', help='Developer ID Application identity already installed in this Mac\'s Keychain.')
    parser.add_argument('--notary-profile', help='Explicitly submit the app using an existing notarytool Keychain profile.')
    options = parser.parse_args()
    if not options.source_only and sys.platform != 'darwin':
        parser.error('A macOS .app must be built on macOS. Use --source-only on Windows.')
    if options.notary_profile and (not options.sign_identity or options.source_only):
        parser.error('--notary-profile requires a native build and --sign-identity.')
    build = Path(tempfile.mkdtemp(prefix='lecture-studio-macos-'))
    stage_macos(build)
    output = ROOT / 'releases'
    output.mkdir(exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    if options.source_only:
        archive = output / f'LectureStudio-macOS-SOURCE-preview-{stamp}.zip'
        with zipfile.ZipFile(archive, 'x', zipfile.ZIP_DEFLATED) as zipped:
            for path in build.rglob('*'):
                if path.is_file():
                    if path.name in DENIED or path.suffix in ('.wav', '.sqlite3', '.dpapi'):
                        raise RuntimeError('Personal data found in staged source.')
                    zipped.write(path, Path('LectureStudioMacSource') / path.relative_to(build))
    else:
        build_helper(build)
        environment = dict(os.environ)
        # The signing choice is explicit, never accidentally inherited from a shell.
        environment['ANNIE_CODESIGN_IDENTITY'] = options.sign_identity or ''
        subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm',
                        '--distpath', str(build / 'dist'), '--workpath', str(build / 'work'),
                        str(build / 'packaging/lecture_studio_macos.spec')], cwd=build, env=environment, check=True)
        package = build / 'dist/Lecture Studio.app'
        worker = package / 'Contents/MacOS/LectureStudioWorker'
        if not worker.is_file():
            raise RuntimeError('The .app is missing its recording worker.')
        if not (package / 'Contents/MacOS/LectureAudioCapture').is_file():
            raise RuntimeError('The .app is missing native system-audio capture.')
        for path in package.rglob('*'):
            if path.is_file() and (path.name in DENIED or path.suffix in ('.wav', '.sqlite3', '.dpapi')):
                raise RuntimeError('Personal data found in the app bundle.')
        # Requires an interactive Mac desktop and unlocked Keychain. This checks
        # native imports/storage/UI, not microphone hardware or meeting detection.
        subprocess.run([str(worker), '--self-test-no-keychain' if options.ci else '--self-test'], check=True, timeout=180)
        if options.smoke_model:
            subprocess.run([sys.executable, str(build / 'tools/test_studio_package.py'), str(package),
                            '--model', str(options.smoke_model.resolve()), '--speech'], check=True, timeout=180)
        label = 'NOTARIZED' if options.notary_profile else 'UNNOTARIZED'
        archive = output / f'LectureStudio-macOS-{platform.machine()}-{label}-{stamp}.zip'
        if options.sign_identity:
            subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', '--verbose=2', str(package)], check=True)
        if options.notary_profile:
            submission = build / 'notary-submission.zip'
            zip_app(package, submission)
            submit_notarization(submission, options.notary_profile)
            subprocess.run(['/usr/bin/xcrun', 'stapler', 'staple', str(package)], check=True)
            subprocess.run(['/usr/bin/xcrun', 'stapler', 'validate', str(package)], check=True)
            subprocess.run(['/usr/sbin/spctl', '--assess', '--type', 'execute', '--verbose=2', str(package)], check=True)
        zip_app(package, archive)
        # A drag-to-Applications installer; never overwrite an installed app.
        installer = build / 'installer'
        installer.mkdir()
        subprocess.run(['/usr/bin/ditto', str(package), str(installer / package.name)], check=True)
        (installer / 'Applications').symlink_to('/Applications', target_is_directory=True)
        shutil.copy2(build / 'packaging/MACOS.md', installer / 'READ ME.md')
        dmg = archive.with_suffix('.dmg')
        subprocess.run(['/usr/bin/hdiutil', 'create', '-volname', 'Lecture Studio',
                        '-srcfolder', str(installer), '-format', 'UDZO', str(dmg)], check=True)
        if options.sign_identity:
            subprocess.run(['/usr/bin/codesign', '--force', '--sign', options.sign_identity, '--timestamp', str(dmg)], check=True)
        if options.notary_profile:
            submit_notarization(dmg, options.notary_profile)
            subprocess.run(['/usr/bin/xcrun', 'stapler', 'staple', str(dmg)], check=True)
            subprocess.run(['/usr/bin/xcrun', 'stapler', 'validate', str(dmg)], check=True)
        checksum(dmg)
        print('Installer:', dmg)
        if options.ci:
            print('Native Keychain and recording hardware remain UNTESTED (CI mode).')
    checksum(archive)
    print('Experimental preview:', archive)
    print('Build diagnostics retained:', build)


if __name__ == '__main__':
    main()
