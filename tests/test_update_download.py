import hashlib
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile

from annie.update_download import (DownloadCancelled, UpdateError, download_release,
    expected_checksum, open_asset, stage_windows)
from annie.updates import RELEASES_URL, parse_release


def payload(content=b'installer'):
    name = 'LectureStudio-Windows-x64-test.zip'
    asset = {'name': name, 'browser_download_url': f'{RELEASES_URL}/download/v99.0.0/{name}',
             'size': len(content), 'digest': 'sha256:' + hashlib.sha256(content).hexdigest()}
    return {'tag_name': 'v99.0.0', 'html_url': RELEASES_URL + '/tag/v99.0.0', 'assets': [asset]}


def reply(content, status=200, headers=None):
    response = Mock(status_code=status, headers=headers or {})
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.iter_content.return_value = [content]
    return response


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_verified_download_keeps_digest_size_and_reports_progress(self):
        data = payload()
        self.assertEqual(parse_release(data)['assets'][0]['digest'], data['assets'][0]['digest'])
        progress = Mock()
        with patch('annie.update_download.select_download', side_effect=lambda r: r['assets'][0]), \
             patch('annie.update_download.subprocess.run') as quarantine, \
             patch('annie.update_download.open_asset', return_value=reply(b'installer')):
            result = download_release(data, self.root, progress)
        if sys.platform == 'darwin':
            self.assertIn('com.apple.quarantine', quarantine.call_args.args[0])
        self.assertEqual(Path(result['path']).read_bytes(), b'installer')
        self.assertEqual(result['sha256'], hashlib.sha256(b'installer').hexdigest())
        progress.assert_called_with(9, 9)

    def test_corrupt_truncated_or_cancelled_download_never_becomes_an_installer(self):
        for content, cancelled, error in ((b'bad', lambda: False, UpdateError),
                                          (b'fake-data', lambda: False, UpdateError),
                                          (b'installer', lambda: True, DownloadCancelled)):
            with patch('annie.update_download.select_download', side_effect=lambda r: r['assets'][0]), \
                 patch('annie.update_download.open_asset', return_value=reply(content)):
                with self.assertRaises(error):
                    download_release(payload(), self.root, cancelled=cancelled)
            self.assertEqual(list(self.root.rglob('*.zip')), [])
            self.assertEqual(list(self.root.rglob('*.part')), [])

    def test_mac_download_marks_quarantine_before_opening(self):
        with patch('annie.update_download.select_download', side_effect=lambda r: r['assets'][0]), \
             patch('annie.update_download.sys.platform', 'darwin'), \
             patch('annie.update_download.subprocess.run') as quarantine, \
             patch('annie.update_download.open_asset', return_value=reply(b'installer')):
            result = download_release(payload(), self.root)
        command = quarantine.call_args.args[0]
        self.assertEqual(command[:3], ['/usr/bin/xattr', '-w', 'com.apple.quarantine'])
        self.assertTrue(command[-1].endswith('.part'))
        self.assertTrue(Path(result['path']).exists())

    def test_checksum_sidecar_requires_matching_filename(self):
        data = payload()
        asset = data['assets'][0]
        asset.pop('digest')
        with self.assertRaisesRegex(UpdateError, 'no SHA-256'):
            expected_checksum(data, asset)
        data['assets'].append({'name': asset['name'] + '.sha256',
                              'browser_download_url': asset['browser_download_url'] + '.sha256'})
        digest = hashlib.sha256(b'installer').hexdigest()
        with patch('annie.update_download.open_asset', return_value=reply((digest + '  ' + asset['name']).encode())):
            self.assertEqual(expected_checksum(data, asset), digest)
        with patch('annie.update_download.open_asset', return_value=reply((digest + '  wrong.zip').encode())):
            with self.assertRaises(UpdateError):
                expected_checksum(data, asset)

    def test_redirects_only_follow_https_github_asset_hosts(self):
        url = payload()['assets'][0]['browser_download_url']
        for location in ('https://example.com/evil.zip', 'http://github.com/evil.zip'):
            with patch('annie.update_download.requests.get', return_value=reply(b'', 302, {'Location': location})) as get:
                with self.assertRaises(UpdateError):
                    open_asset(url)
                get.assert_called_once()
        final = reply(b'installer')
        with patch('annie.update_download.requests.get', side_effect=[
            reply(b'', 302, {'Location': 'https://release-assets.githubusercontent.com/file?token=abc'}), final]):
            self.assertIs(open_asset(url), final)

    def make_archive(self, extra=None):
        archive = self.root / 'update.zip'
        with zipfile.ZipFile(archive, 'w') as zipped:
            for name, content in [('LectureStudio.exe', b'new-gui'),
                                  ('LectureStudioWorker.exe', b'new-worker'), ('_internal/runtime.dll', b'runtime')]:
                zipped.writestr('LectureStudio/' + name, content)
            if extra is not None:
                zipped.writestr(extra, b'bad')
        return archive

    def install_directory(self):
        target = self.root / 'LectureStudio'
        target.mkdir()
        (target / 'LectureStudio.exe').write_bytes(b'old-gui')
        (target / 'LectureStudioWorker.exe').write_bytes(b'old-worker')
        (target / '_internal').mkdir()
        return target

    def test_staging_keeps_old_installation_and_uses_separate_sibling(self):
        target = self.install_directory()
        staged = stage_windows(self.make_archive(), target)
        self.assertEqual((target / 'LectureStudio.exe').read_bytes(), b'old-gui')
        self.assertEqual((staged / 'LectureStudio.exe').read_bytes(), b'new-gui')
        # macOS exposes /var through /private/var, so compare canonical paths.
        self.assertEqual(staged.parent.parent, target.parent.resolve())
        with self.assertRaises(UpdateError):
            stage_windows(self.make_archive(), self.root)

    def test_traversal_links_reserved_names_and_case_collisions_are_rejected_before_extraction(self):
        target = self.install_directory()
        link = zipfile.ZipInfo('LectureStudio/link')
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        for extra in ('LectureStudio/../../outside', '/outside', 'LectureStudio/C:/file',
                      'LectureStudio/CON', 'LectureStudio/lecturestudio.EXE', link):
            with self.assertRaises(UpdateError):
                stage_windows(self.make_archive(extra), target)
        self.assertEqual(list(self.root.glob('LectureStudio-update-*')), [])

    @unittest.skipUnless(sys.platform == 'win32', 'Windows helper integration')
    def test_windows_helper_swaps_bundles_and_retains_backup(self):
        self.run_helper_case(False)

    @unittest.skipUnless(sys.platform == 'win32', 'Windows helper integration')
    def test_windows_helper_rolls_back_when_launch_fails(self):
        self.run_helper_case(True)

    def run_helper_case(self, launch_fails):
        target = self.install_directory()
        staged = stage_windows(self.make_archive(), target)
        source = (Path(__file__).resolve().parents[1] / 'annie/update_install.ps1').read_text()
        # Use the actual file operations, replacing process enumeration/launch
        # and error UI only. The fixture executables are inert bytes, never run.
        source = source.replace("[System.Windows.Forms.MessageBox]::Show($message, 'Lecture Studio update') | Out-Null",
                                'Write-Output $message')
        launch = "throw 'Simulated launch failure'" if launch_fails else "return"
        quote = lambda value: "'" + str(value).replace("'", "''") + "'"
        harness = "function Get-Process { return @() }\nfunction Start-Process { " + launch + " }\n"
        harness += "$body = @'\n" + source + "\n'@\n"
        harness += f"& ([ScriptBlock]::Create($body)) -InstallDir {quote(target)} -StagedDir {quote(staged)} -WaitPid 2147483647\n"
        result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', harness],
                                text=True, capture_output=True, timeout=20,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        expected = b'old-gui' if launch_fails else b'new-gui'
        self.assertEqual((target / 'LectureStudio.exe').read_bytes(), expected, result.stdout + result.stderr)
        if launch_fails:
            self.assertIn('Simulated launch failure', result.stdout)
            self.assertEqual((staged / 'LectureStudio.exe').read_bytes(), b'new-gui')
        if not launch_fails:
            backups = list(self.root.glob('LectureStudio.backup-*'))
            self.assertEqual(len(backups), 1, result.stdout + result.stderr)
            self.assertEqual((backups[0] / 'LectureStudio.exe').read_bytes(), b'old-gui')

    def test_install_is_blocked_during_recording(self):
        from PyQt5.QtWidgets import QApplication, QWidget
        from annie.gui.studio_updates import UpdateDialog
        from annie.update_download import DownloadService
        from annie.updates import UpdateService
        app = QApplication.instance() or QApplication([])
        parent = QWidget()
        parent.is_active = lambda: True
        downloads = DownloadService(self.root)
        downloads.result = {'path': str(self.root / 'installer.dmg'), 'tag': 'v99.0.0'}
        service = UpdateService(cache_path=self.root / 'cache.json')
        dialog = UpdateDialog(service, downloads, parent)
        with patch('annie.gui.studio_updates.QMessageBox.information') as info, \
             patch('annie.gui.studio_updates.QDesktopServices.openUrl') as open_url:
            dialog.install_download()
            info.assert_called_once()
            open_url.assert_not_called()
        service.stop()
        dialog.close()
        parent.close()
        app.processEvents()
