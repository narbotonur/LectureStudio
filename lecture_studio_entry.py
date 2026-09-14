"""Frozen bootstrap. Worker dispatch happens before importing Qt or the UI."""
import os
import sys


def main():
    # Frozen Python does not honor PYTHONIOENCODING like the normal interpreter.
    # The worker protocol must preserve Cyrillic and timestamp symbols over pipes.
    for name in ('stdin', 'stdout', 'stderr'):
        stream = getattr(sys, name)
        if stream is not None and hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    if '--self-test' in sys.argv or '--self-test-no-keychain' in sys.argv:
        # Always isolate diagnostics from accounts, startup entries and recordings.
        import tempfile
        with tempfile.TemporaryDirectory(prefix='annie-self-test-') as temporary:
            os.environ['ANNIE_DATA_DIR'] = temporary
            from annie.release_check import run
            return run(check_secrets='--self-test-no-keychain' not in sys.argv)
    if '--whisper-service' in sys.argv:
        # Console worker executable retains real stdin/stdout for JSON IPC.
        from annie.whisper_worker import clean_stray_scripts
        from annie.whisper_runtime import main as worker_main
        sys.argv = [sys.argv[0], '--service']
        return worker_main(clean_stray_scripts)
    if getattr(sys, 'frozen', False):
        from annie.paths import DATA_DIR
        # A windowed executable has no console streams. Keep them writable.
        for name in ('stdout', 'stderr'):
            if getattr(sys, name) is None:
                setattr(sys, name, open(os.devnull, 'w', encoding='utf-8'))
    if '--prayer-widget' in sys.argv:
        from annie.prayer_widget_main import main as prayer_main
        return prayer_main()
    from annie.workstation_main import main as studio_main
    return studio_main()


if __name__ == '__main__':
    raise SystemExit(main())
