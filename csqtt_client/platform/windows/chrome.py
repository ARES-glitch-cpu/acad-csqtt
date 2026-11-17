"""Native Windows resizing and taskbar behavior with an application title bar."""
import ctypes
from ctypes import wintypes
import sys


class WindowChrome:
    def __init__(self, root, scale=1):
        self.root, self.scale = root, scale
        self.hwnd = None
        self.previous = None
        self.region_size = None
        self.drag_origin = None
        self.normal_size = None
        if sys.platform != "win32":
            return
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        self.gdi = ctypes.WinDLL("gdi32", use_last_error=True)
        self.proc_type = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT,
                                          wintypes.WPARAM, wintypes.LPARAM)
        self.user.GetParent.argtypes = [wintypes.HWND]
        self.user.GetParent.restype = wintypes.HWND
        self.user.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        self.user.GetAncestor.restype = wintypes.HWND
        self.user.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
        self.user.SetWindowLongPtrW.restype = ctypes.c_void_p
        self.user.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT,
                                            wintypes.WPARAM, wintypes.LPARAM]
        self.user.CallWindowProcW.restype = ctypes.c_ssize_t
        self.user.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        self.user.SetWindowRgn.argtypes = [wintypes.HWND, wintypes.HRGN, wintypes.BOOL]
        self.user.IsZoomed.argtypes = [wintypes.HWND]
        self.user.IsWindow.argtypes = [wintypes.HWND]
        self.user.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                          ctypes.c_int, ctypes.c_int, wintypes.UINT]
        self.user.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
        self.user.MonitorFromWindow.restype = wintypes.HMONITOR
        self.gdi.CreateRoundRectRgn.argtypes = [ctypes.c_int] * 6
        self.gdi.CreateRoundRectRgn.restype = wintypes.HRGN
        self.gdi.DeleteObject.argtypes = [wintypes.HANDLE]
        self.callback = self.proc_type(self.window_proc)
        root.bind("<Map>", self.on_map, add="+")

    def on_map(self, event):
        if event.widget is self.root:
            self.root.after_idle(self.install)

    def install(self):
        hwnd = self.user.GetAncestor(self.root.winfo_id(), 2)
        if self.previous and self.hwnd == hwnd:
            return
        self.stop()
        self.hwnd = hwnd
        self.previous = self.user.SetWindowLongPtrW(self.hwnd, -4, ctypes.cast(self.callback, ctypes.c_void_p))
        if not self.previous:
            raise ctypes.WinError(ctypes.get_last_error())
        self.user.SetWindowPos(self.hwnd, None, 0, 0, 0, 0, 0x0027)  # FRAMECHANGED | NOZORDER | NOMOVE | NOSIZE
        self.round_window()

    def window_proc(self, hwnd, message, wparam, lparam):
        if message == 0x0083:  # WM_NCCALCSIZE: the title bar is part of our client area.
            if wparam and self.user.IsZoomed(hwnd):
                class MonitorInfo(ctypes.Structure):
                    _fields_ = [("size", wintypes.DWORD), ("monitor", wintypes.RECT),
                                ("work", wintypes.RECT), ("flags", wintypes.DWORD)]
                info = MonitorInfo()
                info.size = ctypes.sizeof(info)
                monitor = self.user.MonitorFromWindow(hwnd, 2)
                self.user.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MonitorInfo)]
                if self.user.GetMonitorInfoW(monitor, ctypes.byref(info)):
                    ctypes.cast(lparam, ctypes.POINTER(wintypes.RECT))[0] = info.work
            return 0
        if message == 0x0084:  # WM_NCHITTEST
            if self.user.IsZoomed(hwnd):
                return 1
            rect = wintypes.RECT()
            self.user.GetWindowRect(hwnd, ctypes.byref(rect))
            x, y = ctypes.c_short(lparam & 0xffff).value, ctypes.c_short((lparam >> 16) & 0xffff).value
            edge = max(5, round(5 * self.scale))
            left, right = x < rect.left + edge, x >= rect.right - edge
            top, bottom = y < rect.top + edge, y >= rect.bottom - edge
            if top:
                return 13 if left else 14 if right else 12
            if bottom:
                return 16 if left else 17 if right else 15
            if left or right:
                return 10 if left else 11
            return 1
        if message == 0x0085:  # WM_NCPAINT
            return 0
        if message == 0x0086:  # WM_NCACTIVATE: retain activation without painting the old caption.
            lparam = -1
        result = self.user.CallWindowProcW(self.previous, hwnd, message, wparam, lparam)
        if message == 0x0005:  # WM_SIZE
            self.round_window()
        return result

    def round_window(self):
        rect = wintypes.RECT()
        if not self.hwnd or not self.user.GetWindowRect(self.hwnd, ctypes.byref(rect)):
            return
        zoomed = bool(self.user.IsZoomed(self.hwnd))
        size = (rect.right - rect.left, rect.bottom - rect.top, zoomed)
        if size == self.region_size or min(size[:2]) <= 0:
            return
        self.region_size = size
        if zoomed:
            self.user.SetWindowRgn(self.hwnd, None, True)
        else:
            diameter = round(18 * self.scale)
            region = self.gdi.CreateRoundRectRgn(0, 0, size[0] + 1, size[1] + 1, diameter, diameter)
            if not self.user.SetWindowRgn(self.hwnd, region, True):
                self.gdi.DeleteObject(region)

    def drag(self, event):
        # A native modal move loop inside a Tcl callback can re-enter Tcl and abort
        # the process. Keep movement in Tk's ordinary event loop instead.
        self.drag_origin = (event.x_root, event.y_root, self.root.winfo_x(), self.root.winfo_y())

    def drag_motion(self, event):
        if self.drag_origin is None:
            return
        start_x, start_y, window_x, window_y = self.drag_origin
        dx, dy = event.x_root - start_x, event.y_root - start_y
        if abs(dx) + abs(dy) < 3:
            return
        if self.root.state() == "zoomed":
            fraction = (start_x - window_x) / max(1, self.root.winfo_width())
            width, height = self.normal_size or (round(1120*self.scale), round(900*self.scale))
            self.root.state("normal")
            window_x = event.x_root - round(width * fraction)
            window_y = event.y_root - round(20*self.scale)
            self.root.geometry(f"{width}x{height}+{window_x}+{window_y}")
            self.drag_origin = (event.x_root, event.y_root, window_x, window_y)
        else:
            self.root.geometry(f"+{window_x + dx}+{window_y + dy}")

    def drag_end(self, event=None):
        self.drag_origin = None

    def maximize(self, event=None):
        self.drag_end()
        if self.root.state() != "zoomed":
            self.normal_size = (self.root.winfo_width(), self.root.winfo_height())
        self.root.state("normal" if self.root.state() == "zoomed" else "zoomed")

    def stop(self):
        if self.hwnd and self.previous and self.user.IsWindow(self.hwnd):
            self.user.SetWindowLongPtrW(self.hwnd, -4, self.previous)
            self.previous = None
