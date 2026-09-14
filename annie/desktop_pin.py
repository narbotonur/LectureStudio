"""Optional Windows desktop attachment. Never modify Explorer's own windows.

The Explorer host is discovered, not created using undocumented shell messages.
Only this app's HWND is reparented/restyled. Unsupported shells and DPI mismatches
fail explicitly and leave a recoverable floating widget. This is not Win+W.
"""
import sys


def enable_widget_dpi():
    """Call before QApplication: match modern Explorer's per-monitor-v2 mode."""
    if sys.platform == 'win32':
        import ctypes
        try:
            user32 = ctypes.WinDLL('user32', use_last_error=True)
            user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
            user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        except (AttributeError, OSError):
            pass  # An existing app/older Windows can already have set its mode.


def find_desktop_host(gui=None):
    if gui is None:
        import win32gui as gui
    found = []

    def visit(hwnd, _):
        if gui.GetClassName(hwnd) not in ('Progman', 'WorkerW'):
            return
        view = gui.FindWindowEx(hwnd, 0, 'SHELLDLL_DefView', None)
        if view and gui.IsWindowVisible(hwnd):
            left, top, right, bottom = gui.GetClientRect(hwnd)
            if right > left and bottom > top:
                found.append(hwnd)

    gui.EnumWindows(visit, None)
    return found[0] if found else None


class DesktopPin:
    def __init__(self, widget):
        self.widget = widget
        self.hwnd = self.host = None
        self.original = None

    @property
    def attached(self):
        if not self.hwnd or sys.platform != 'win32':
            return False
        import win32gui
        return (win32gui.IsWindow(self.hwnd) and win32gui.IsWindow(self.host)
                and win32gui.GetParent(self.hwnd) == self.host)

    def attach(self):
        if sys.platform != 'win32':
            raise RuntimeError('Desktop pinning is available on Windows. Floating mode still works here.')
        if self.attached:
            return
        import ctypes
        import win32con as con
        import win32gui as gui
        import win32process
        import psutil
        host = find_desktop_host(gui)
        if not host:
            raise RuntimeError('Windows desktop is unavailable. The widget stays floating; try pinning again.')
        pid = win32process.GetWindowThreadProcessId(host)[1]
        if psutil.Process(pid).name().lower() != 'explorer.exe':
            raise RuntimeError('Desktop host is not Windows Explorer. Pinning was not applied.')
        hwnd = int(self.widget.winId())
        if not gui.IsWindow(hwnd):
            # Explorer can remove a cross-process child HWND during a restart.
            # Recreate our own native surface only; never restart/change Explorer.
            self.widget.destroy()
            hwnd = int(self.widget.winId())
            self.widget.show()
        user32 = ctypes.WinDLL('user32', use_last_error=True)
        user32.GetWindowDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        user32.GetWindowDpiAwarenessContext.restype = ctypes.c_void_p
        user32.AreDpiAwarenessContextsEqual.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        if not user32.AreDpiAwarenessContextsEqual(user32.GetWindowDpiAwarenessContext(hwnd),
                                                  user32.GetWindowDpiAwarenessContext(host)):
            raise RuntimeError('Desktop DPI mode differs. Restart the prayer widget before pinning.')
        self.detach()
        style = gui.GetWindowLong(hwnd, con.GWL_STYLE)
        extended = gui.GetWindowLong(hwnd, con.GWL_EXSTYLE)
        # IsWindowVisible/SetParent success does NOT prove alpha composition.
        # Transparent Qt children disappeared in the real pythonw widget even
        # when an isolated probe rendered correctly. Fail while still floating
        # rather than letting a cosmetic change regress desktop visibility.
        if extended & 0x00080000:  # WS_EX_LAYERED
            raise RuntimeError('Transparent windows cannot be pinned safely. The widget remains floating.')
        rect = gui.GetWindowRect(hwnd)
        self.hwnd, self.host = hwnd, host
        self.original = (gui.GetParent(hwnd), style, extended)
        try:
            gui.SetWindowLong(hwnd, con.GWL_STYLE, (style & ~con.WS_POPUP) | con.WS_CHILD)
            gui.SetWindowLong(hwnd, con.GWL_EXSTYLE,
                              (extended | con.WS_EX_TOOLWINDOW | 0x08000000)  # WS_EX_NOACTIVATE
                              & ~con.WS_EX_APPWINDOW & ~con.WS_EX_TOPMOST)
            gui.SetParent(hwnd, host)
            x, y = gui.ScreenToClient(host, rect[:2])
            gui.SetWindowPos(hwnd, con.HWND_TOP, x, y, rect[2] - rect[0], rect[3] - rect[1],
                             con.SWP_NOACTIVATE | con.SWP_FRAMECHANGED | con.SWP_SHOWWINDOW)
            if not self.attached:
                raise RuntimeError('Windows did not attach the widget to the desktop.')
        except Exception:
            self.detach()
            raise

    def detach(self):
        if not self.hwnd or not self.original or sys.platform != 'win32':
            return
        import win32con as con
        import win32gui as gui
        hwnd, original = self.hwnd, self.original
        if gui.IsWindow(hwnd):
            rect = gui.GetWindowRect(hwnd)
            parent, style, extended = original
            gui.SetParent(hwnd, parent if parent and gui.IsWindow(parent) else 0)
            gui.SetWindowLong(hwnd, con.GWL_STYLE, style)
            gui.SetWindowLong(hwnd, con.GWL_EXSTYLE, extended)
            gui.SetWindowPos(hwnd, con.HWND_NOTOPMOST, *rect[:2], rect[2] - rect[0], rect[3] - rect[1],
                             con.SWP_NOACTIVATE | con.SWP_FRAMECHANGED)
        self.hwnd = self.host = self.original = None
