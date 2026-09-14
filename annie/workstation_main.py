"""Standalone Lecture Studio entry point (no voice assistant or vision worker)."""
import os
import sys

os.environ['OPENCV_LOG_LEVEL'] = 'ERROR'
os.environ['OPENCV_VIDEOIO_PRIORITY_MSMF'] = '0'
os.environ['PYTHONUTF8'] = '1'

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon, QMenu, QStyle

from annie.meeting_prompt import MeetingPromptController
from annie.studio_router import StudioRouter


def main(watch_only=None):
    if watch_only is None:
        watch_only = '--watch' in sys.argv[1:]
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle('Fusion')
    app.setQuitOnLastWindowClosed(False)
    if sys.platform == 'darwin':
        from annie.macos_support import set_studio_visible
        from PyQt5.QtGui import QFont
        QFont.insertSubstitution('Segoe UI', 'Helvetica Neue')
        QFont.insertSubstitution('Consolas', 'Menlo')
        set_studio_visible(not watch_only)

    from annie.paths import PRIVATE_PROFILE
    if PRIVATE_PROFILE:
        from annie.gui.studio_setup import StudioSetup, SETUP_MARKER
        if not SETUP_MARKER.exists():
            # Startup never opens an unexpected account dialog.
            if watch_only:
                return 0
            if StudioSetup().exec_() != StudioSetup.Accepted:
                return 0

    studio_holder = [None]

    def get_studio():
        if watch_only:
            raise RuntimeError('The watcher cannot own a Studio window.')
        if studio_holder[0] is None:
            from annie.gui.meeting_window import MeetingWindow
            studio_holder[0] = MeetingWindow()
            studio_holder[0].setWindowTitle('Lecture Studio')
            studio_holder[0].settings_changed.connect(refresh_monitor)
            if not watch_only:
                studio_holder[0].finished.connect(begin_shutdown)
        return studio_holder[0]

    def refresh_monitor():
        controller.stop()
        controller._schedule_events = []
        controller._schedule_day = ''
        controller.start()

    from annie.startup import StudioLauncher
    router = StudioRouter(app, get_studio,
                          launch_owner=StudioLauncher() if watch_only else None)
    router.error.connect(lambda message: QMessageBox.information(None, 'Lecture Studio', message))

    def start_prompted_transcription(source, context):
        router.request('start', source=source, context=context)

    controller = MeetingPromptController(
        app,
        start_prompted_transcription,
        is_recording=router.is_recording,
    )
    monitor_started = controller.start()
    if watch_only and not monitor_started:
        # Another full Annie or silent watcher already owns monitoring.
        return 0

    shutdown_started = False
    shutdown_timer = QTimer(app)

    def finish_shutdown():
        from annie.whisper_service import whisper_service_is_running
        studio = studio_holder[0]
        if (controller.has_running_job() or
                (studio and studio.has_running_jobs()) or
                whisper_service_is_running()):
            return
        shutdown_timer.stop()
        app.quit()

    shutdown_timer.timeout.connect(finish_shutdown)

    def begin_shutdown(*_):
        nonlocal shutdown_started
        if shutdown_started:
            return
        shutdown_started = True
        router.begin_shutdown()
        controller.stop()
        if studio_holder[0]:
            studio_holder[0].stop_jobs()
        from annie.whisper_service import shutdown_whisper_service
        shutdown_whisper_service()
        shutdown_timer.start(50)

    tray = None
    if watch_only:
        tray = QSystemTrayIcon(app.style().standardIcon(QStyle.SP_ComputerIcon), app)
        tray.setToolTip('Lecture Studio · Meeting and lecture reminders')
        tray_menu = QMenu()
        tray_menu.addAction('Open Lecture Studio', lambda: router.request())
        tray_menu.addAction('Quit watcher', begin_shutdown)
        tray.setContextMenu(tray_menu)
        tray.activated.connect(lambda reason: router.request() if reason == QSystemTrayIcon.DoubleClick else None)
        tray.show()
        app.aboutToQuit.connect(tray.hide)

    if not watch_only:
        def routed(action):
            if action == 'show' and studio_holder[0] is None:
                # An existing process owns the window; this launcher can exit.
                begin_shutdown()
        router.delivered.connect(routed)
        router.error.connect(lambda message: (print(message), begin_shutdown()))
        QTimer.singleShot(0, router.request)

    def final_cleanup():
        controller.stop()
        if studio_holder[0]:
            studio_holder[0].stop_jobs()
        from annie.whisper_service import shutdown_whisper_service
        shutdown_whisper_service()

    app.aboutToQuit.connect(final_cleanup)
    return app.exec_()


if __name__ == '__main__':
    raise SystemExit(main())
