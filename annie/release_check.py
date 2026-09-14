"""Offline release diagnostics; no microphone capture or cloud requests."""
import json
from pathlib import Path
import subprocess
import sys


def check(condition, message):
    # These checks must remain active in optimized frozen builds.
    if not condition:
        raise RuntimeError(message)


def run(check_secrets=True):
    from annie import config as cfg
    from annie.secure_storage import read_secret, write_secret, delete_secret
    from annie.calendar_service import is_connected
    import faster_whisper
    import ctranslate2
    import av
    import onnxruntime
    import soundcard
    from google import genai
    from googleapiclient.discovery import build_from_document
    from googleapiclient.discovery_cache import get_static_doc
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QApplication
    from annie.gui.studio_setup import StudioSetup
    from annie.gui.meeting_window import MeetingWindow
    from annie.gui.studio_dock import StudioDock
    from annie.study_sessions import StudyStore

    check(not cfg.GEMINI_API_KEY and not cfg.GROQ_API_KEY, 'Fresh profile contains an API key')
    check(not cfg.LIBCAL_EMAIL and not is_connected(), 'Fresh profile contains an account')
    if check_secrets:
        secret = Path(cfg.DATA_DIR) / 'diagnostic.dpapi'
        try:
            write_secret(secret, {'test': 'not-a-real-credential'})
            check(read_secret(secret)['test'] == 'not-a-real-credential', 'Secret roundtrip failed')
            check(b'not-a-real-credential' not in secret.read_bytes(), 'Secret stored in plaintext')
        finally:
            delete_secret(secret)
    native_checks = []
    if sys.platform == 'darwin':
        import AppKit
        import Quartz
        import AVFoundation
        from keyring.backends.macOS import Keyring
        from annie.macos_audio import check_helper
        result = subprocess.run([str(check_helper()), '--self-test'], capture_output=True,
                                text=True, encoding='utf-8', check=True, timeout=15)
        capabilities = json.loads(result.stdout)
        check(capabilities.get('type') == 'capabilities' and capabilities.get('system_audio') is True,
              'ScreenCaptureKit helper is missing system-audio support')
        native_checks = ['native-Mac-imports', 'ScreenCaptureKit-helper-link-and-protocol']
    check(get_static_doc('calendar', 'v3'), 'Calendar discovery document missing')
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    setup = StudioSetup()
    setup.setAttribute(Qt.WA_DontShowOnScreen)
    setup.show()
    app.processEvents()
    check(setup.key.text() == '', 'Setup inherited a key')
    setup.close()
    window = MeetingWindow()
    window.setAttribute(Qt.WA_DontShowOnScreen)
    window.show()
    window._switch_tab(5)
    app.processEvents()
    check(window.stack.count() == 6, 'Studio tab missing')
    check(not window.study_page.store.history(), 'Fresh profile contains study history')
    window.close()
    dock = StudioDock()
    check((Path(__file__).parent / 'gui/assets/portals/moodle-symbol.svg').is_file(), 'Dock asset missing')
    dock.hide_immediately()
    app.processEvents()
    print(json.dumps({'status': 'ok', 'checks': ['fresh-profile', 'calendar-discovery',
          'Whisper-backend-imports', 'setup-window', 'six-Studio-tabs', 'dock-assets'] + native_checks +
          (['native-secret-storage'] if check_secrets else []),
          'skipped': [] if check_secrets else ['native-secret-storage (noninteractive build check)']}))
    return 0
