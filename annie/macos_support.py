"""Lazy native Mac integration. Watcher scans never request OS permissions."""
import json
import subprocess


def active_audio_processes():
    """Read CoreAudio activity metadata off the GUI thread; never record sound."""
    from annie.macos_audio import helper_path
    import psutil
    path = helper_path()
    if not path.is_file():
        return set()
    try:
        result = subprocess.run([str(path), '--audio-processes'], capture_output=True,
                                text=True, encoding='utf-8', check=True, timeout=2)
        event = json.loads(result.stdout)
        if event.get('type') != 'audio-processes':
            return set()
        names = set()
        for pid in event.get('pids', [])[:1024]:
            try:
                process = psutil.Process(int(pid))
                names.add(process.name())
                # Teams/Chromium may host audio in a helper process.
                names.update(parent.name() for parent in process.parents()[:3])
            except (ValueError, psutil.Error):
                continue
        return names
    except (OSError, subprocess.SubprocessError, ValueError, TypeError, AttributeError):
        return set()


def visible_windows():
    try:
        import Quartz
        if not Quartz.CGPreflightScreenCaptureAccess():
            return []
        windows = Quartz.CGWindowListCopyWindowInfo(
            Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements,
            Quartz.kCGNullWindowID) or []
        result = []
        for item in windows:
            if item.get(Quartz.kCGWindowLayer, 0) != 0:
                continue
            title = item.get(Quartz.kCGWindowName, '')
            owner = item.get(Quartz.kCGWindowOwnerName, '')
            if title and owner:
                result.append((title, owner, int(item.get(Quartz.kCGWindowOwnerPID, 0))))
        return result
    except (ImportError, AttributeError, RuntimeError):
        return []


def request_meeting_permission():
    """Only call from an explicit user click, never on startup or a timer."""
    import Quartz
    return bool(Quartz.CGRequestScreenCaptureAccess())


def set_accessory_mode():
    """Keep a --watch process in the menu bar, without a Dock icon."""
    set_studio_visible(False)


def set_studio_visible(visible):
    from AppKit import (NSApplication, NSApplicationActivationPolicyAccessory,
                        NSApplicationActivationPolicyRegular)
    policy = NSApplicationActivationPolicyRegular if visible else NSApplicationActivationPolicyAccessory
    NSApplication.sharedApplication().setActivationPolicy_(policy)
