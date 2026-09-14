"""Build only app code/assets; never copy the developer workspace as a release."""
import argparse
import ast
import hashlib
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
MODULES = ('__init__', 'paths', 'platform_support', 'macos_support', 'macos_audio', 'secure_storage', 'startup', 'config', 'workstation_main',
           'studio_router', 'meeting_prompt', 'calendar_service', 'study_sessions', 'study_guide',
           'meeting', 'dsp', 'audio_io', 'recording_audio', 'whisper_service', 'whisper_worker',
           'whisper_runtime', 'whisper_models', 'whisper_events', 'release_check',
           'prayer_times', 'prayer_startup', 'prayer_widget_main', 'desktop_pin')
GUI = ('__init__', 'design', 'meeting_window', 'studio_dock', 'week_calendar', 'study_timer', 'studio_setup', 'prayer_widget', 'prayer_card')
DENIED = ('token.json', 'credentials.json', 'annie_settings.json', 'study_sessions.sqlite3',
          'accounts.dpapi', 'calendar.dpapi', 'google-client.dpapi', 'lecture_schedule_cache.json',
          'prayer-widget.json', 'prayer-times-cache.json')


def validate_source(path):
    text = path.read_text(encoding='utf-8-sig')
    if re.search(r'(?:gsk_[A-Za-z0-9]{15,}|AIza[A-Za-z0-9_-]{25,}|-----BEGIN (?:RSA )?PRIVATE KEY)', text):
        raise ValueError(f'Possible embedded credential in {path.name}; build stopped.')
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and node.value.value:
            for target in node.targets:
                if isinstance(target, ast.Name) and (target.id.endswith('_API_KEY') or
                    target.id in ('LIBCAL_FIRST_NAME', 'LIBCAL_LAST_NAME', 'LIBCAL_EMAIL', 'LIBCAL_ID_CARD')):
                    raise ValueError(f'Personal default in {path.name}: {target.id}; build stopped.')


def stage(destination):
    files = [ROOT / 'lecture_studio_entry.py']
    files += [ROOT / 'annie' / (name + '.py') for name in MODULES]
    files += [ROOT / 'annie/gui' / (name + '.py') for name in GUI]
    files += [ROOT / 'annie/utils' / (name + '.py') for name in ('__init__', 'nu_links')]
    for source in files:
        validate_source(source)
        target = destination / source.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    assets = ROOT / 'annie/gui/assets/portals'
    for source in assets.iterdir():
        if source.suffix.lower() in ('.svg', '.png', '.ico', '.md'):
            target = destination / source.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    target = destination / 'packaging'
    target.mkdir(exist_ok=True)
    shutil.copy2(ROOT / 'packaging/lecture_studio.spec', target)
    shutil.copy2(ROOT / 'packaging/PRAYER_WIDGET.md', target)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--stage-only', action='store_true')
    parser.add_argument('--reuse-build', type=Path)
    options = parser.parse_args()
    if sys.platform != 'win32' and not options.stage_only:
        parser.error('Use tools/build_studio_macos.py for a macOS build.')
    output = ROOT / 'releases'
    output.mkdir(exist_ok=True)
    # Keep failed build diagnostics; never recursively delete a user-supplied directory.
    build = options.reuse_build.resolve() if options.reuse_build else Path(tempfile.mkdtemp(prefix='lecture-studio-build-'))
    if options.reuse_build and (not build.is_dir() or not build.name.startswith('lecture-studio-build-') or
                               build.parent != Path(tempfile.gettempdir()).resolve()):
        raise ValueError('Reuse is allowed only for an existing Lecture Studio temporary build directory.')
    stage(build)
    print('Clean source staged:', build, flush=True)
    if options.stage_only:
        return
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--distpath', str(build / 'dist'),
                    '--workpath', str(build / 'work'), str(build / 'packaging/lecture_studio.spec')],
                   cwd=build, check=True)
    package = build / 'dist/LectureStudio'
    for name in ('START_HERE.md', 'Create shortcuts.ps1', 'PRAYER_WIDGET.md'):
        shutil.copy2(ROOT / 'packaging' / name, package / name)
    for path in package.rglob('*'):
        if path.is_file() and (path.name in DENIED or path.suffix in ('.wav', '.sqlite3', '.dpapi')):
            raise ValueError(f'Unexpected personal data in release: {path.name}')
    # Verify the frozen runtime in a blank profile before declaring a release.
    diagnostic = subprocess.run([str(package / 'LectureStudioWorker.exe'), '--self-test'], timeout=90,
                   capture_output=True, text=True, encoding='utf-8',
                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    print(diagnostic.stdout, flush=True)
    if diagnostic.returncode:
        print(diagnostic.stderr, flush=True)
        raise RuntimeError('Frozen-app diagnostics failed; no release ZIP was created.')
    from datetime import datetime
    archive = output / ('LectureStudio-Windows-x64-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '.zip')
    if archive.exists():
        raise FileExistsError('Release already exists; preserve it or choose a new release name before building again.')
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as zipped:
        for path in package.rglob('*'):
            if path.is_file():
                zipped.write(path, Path('LectureStudio') / path.relative_to(package))
    digest = hashlib.file_digest(archive.open('rb'), 'sha256').hexdigest()
    (output / (archive.name + '.sha256')).write_text(digest + '  ' + archive.name + '\n', encoding='ascii')
    print('Release:', archive)
    print('SHA256:', digest)
    print('Uncompressed test package:', package)


if __name__ == '__main__':
    main()
