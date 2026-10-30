# -*- coding: utf-8 -*-
"""열려 있는 창들의 윗변을 '발판'으로 알려줌 (윈도우 전용, 다른 OS에선 빈 목록)

반환 좌표는 실제 화면 픽셀(물리 픽셀). 다른 창에 가려진 부분은 발판에서 뺌.
"""
import os
import sys

IS_WIN = sys.platform == "win32"

if IS_WIN:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    dwmapi = ctypes.WinDLL("dwmapi")

    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongW.restype = ctypes.c_long
    dwmapi.DwmGetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]

    GWL_EXSTYLE = -20
    WS_EX_TOOLWINDOW = 0x00000080
    WS_EX_NOACTIVATE = 0x08000000
    DWMWA_EXTENDED_FRAME_BOUNDS = 9
    DWMWA_CLOAKED = 14
    SKIP_CLASSES = {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd",
                    "Windows.UI.Core.CoreWindow", "ApplicationFrameWindow_Hidden",
                    "NotifyIconOverflowWindow", "TopLevelWindowForOverflowXamlIsland",
                    "XamlExplorerHostIslandWindow", "ForegroundStaging"}
    MY_PID = os.getpid()


def _rect(hwnd):
    r = wintypes.RECT()
    # 윈도우10/11은 GetWindowRect에 보이지 않는 테두리가 포함됨 → DWM 실제 테두리 사용
    if dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(r), ctypes.sizeof(r)) != 0:
        user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


def _is_real_window(hwnd):
    if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
        return False
    cloaked = wintypes.DWORD(0)
    if dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(cloaked), ctypes.sizeof(cloaked)) == 0 \
            and cloaked.value:
        return False                       # 다른 가상 데스크톱 / 숨겨진 앱 창
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if pid.value == MY_PID:
        return False                       # 펫 자기 자신
    buf = ctypes.create_unicode_buffer(128)
    user32.GetClassNameW(hwnd, buf, 128)
    if buf.value in SKIP_CLASSES:
        return False
    return True


def list_windows():
    """보이는 창들을 위에 있는 순서대로: [(hwnd, left, top, right, bottom, 발판후보여부)]"""
    if not IS_WIN:
        return []
    out = []

    def cb(hwnd, _):
        try:
            if _is_real_window(hwnd):
                l, t, r, b = _rect(hwnd)
                if r - l > 20 and b - t > 20:
                    ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
                    titled = user32.GetWindowTextLengthW(hwnd) > 0
                    platform_ok = titled and not (ex & WS_EX_TOOLWINDOW) and not (ex & WS_EX_NOACTIVATE)
                    out.append((int(hwnd or 0), l, t, r, b, platform_ok))
        except Exception:
            pass
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return out


def platforms(min_width=60):
    """{hwnd: [(x1, x2, y, 창왼쪽x), ...]} — 창 윗변 중 다른 창에 안 가려진 구간 (물리 픽셀)"""
    wins = list_windows()
    result = {}
    for i, (hwnd, l, t, r, b, ok) in enumerate(wins):
        if not ok or r - l < min_width:
            continue
        segs = [(l, r)]
        for (_, l2, t2, r2, b2, _ok) in wins[:i]:          # 이 창보다 위에 있는 창들
            if t2 - 2 <= t <= b2:                       # 윗변 높이를 덮고 있으면 그 구간을 뺌
                new = []
                for a, c in segs:
                    if r2 <= a or l2 >= c:
                        new.append((a, c))
                    else:
                        if l2 > a:
                            new.append((a, l2))
                        if r2 < c:
                            new.append((r2, c))
                segs = new
                if not segs:
                    break
        segs = [(a, c) for a, c in segs if c - a >= min_width]
        if segs:
            result[hwnd] = [(a, c, t, l) for a, c in segs]
    return result


def window_rect(hwnd):
    """창 하나의 현재 위치 (물리 픽셀). 닫혔거나 최소화/숨김이면 None — 매 프레임 써도 가벼움"""
    if not IS_WIN:
        return None
    try:
        if not user32.IsWindow(hwnd) or not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
            return None
        cloaked = wintypes.DWORD(0)
        if dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(cloaked), ctypes.sizeof(cloaked)) == 0 \
                and cloaked.value:
            return None
        return _rect(hwnd)
    except Exception:
        return None


if IS_WIN:
    user32.IsWindow.argtypes = [wintypes.HWND]
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    user32.MonitorFromWindow.restype = wintypes.HANDLE

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

    user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MONITORINFO)]


def fullscreen_foreground():
    """지금 맨 앞 창이 모니터 전체를 덮고 있나 (PPT 발표, 영상 전체화면, 게임 등)"""
    if not IS_WIN:
        return False
    try:
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return False
        buf = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(hwnd, buf, 64)
        if buf.value in ("Progman", "WorkerW", "Shell_TrayWnd"):
            return False                       # 바탕화면 자체는 제외
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == MY_PID:
            return False
        r = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(r))
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        if not user32.GetMonitorInfoW(user32.MonitorFromWindow(hwnd, 2), ctypes.byref(mi)):
            return False
        m = mi.rcMonitor
        return r.left <= m.left and r.top <= m.top and r.right >= m.right and r.bottom >= m.bottom
    except Exception:
        return False


def lower_priority():
    """업무 프로그램보다 CPU 순서를 양보 (보통보다 낮은 우선순위)"""
    if IS_WIN:
        try:
            k = ctypes.WinDLL("kernel32")
            k.SetPriorityClass(k.GetCurrentProcess(), 0x00004000)   # BELOW_NORMAL_PRIORITY_CLASS
        except Exception:
            pass


ARROW_KEYS = (0x25, 0x26, 0x27, 0x28)      # ← ↑ → ↓

if IS_WIN:
    user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    user32.GetAsyncKeyState.restype = ctypes.c_short


def arrows_down():
    """지금 눌려 있는 방향키 (어떤 창을 보고 있어도 확인 가능, 키 입력은 가로채지 않음)"""
    if not IS_WIN:
        return frozenset()
    try:
        return frozenset(vk for vk in ARROW_KEYS if user32.GetAsyncKeyState(vk) & 0x8000)
    except Exception:
        return frozenset()


# ───── Raw Input: 다른 창을 보고 있어도 방향키 누름을 정확히 받기 (아주 짧은 연타도) ─────
WM_INPUT = 0x00FF
if IS_WIN:
    class RAWINPUTDEVICE(ctypes.Structure):
        _fields_ = [("usUsagePage", wintypes.USHORT), ("usUsage", wintypes.USHORT),
                    ("dwFlags", wintypes.DWORD), ("hwndTarget", wintypes.HWND)]

    class RAWINPUTHEADER(ctypes.Structure):
        _fields_ = [("dwType", wintypes.DWORD), ("dwSize", wintypes.DWORD),
                    ("hDevice", wintypes.HANDLE), ("wParam", wintypes.WPARAM)]

    class RAWKEYBOARD(ctypes.Structure):
        _fields_ = [("MakeCode", wintypes.USHORT), ("Flags", wintypes.USHORT), ("Reserved", wintypes.USHORT),
                    ("VKey", wintypes.USHORT), ("Message", wintypes.UINT), ("ExtraInformation", wintypes.ULONG)]

    class RAWINPUT(ctypes.Structure):
        _fields_ = [("header", RAWINPUTHEADER), ("keyboard", RAWKEYBOARD)]

    user32.RegisterRawInputDevices.argtypes = [ctypes.POINTER(RAWINPUTDEVICE), wintypes.UINT, wintypes.UINT]
    user32.GetRawInputData.argtypes = [wintypes.HANDLE, wintypes.UINT, ctypes.c_void_p,
                                       ctypes.POINTER(wintypes.UINT), wintypes.UINT]
    user32.GetRawInputData.restype = wintypes.UINT
    _raw_buf = RAWINPUT()


def register_raw_keyboard(hwnd):
    """키보드 입력을 (창이 뒤에 있어도) 이 창으로도 알려 달라고 등록. 키 입력을 막거나 바꾸지 않음"""
    if not IS_WIN:
        return False
    try:
        dev = RAWINPUTDEVICE(0x01, 0x06, 0x00000100, hwnd)    # 키보드, RIDEV_INPUTSINK
        return bool(user32.RegisterRawInputDevices(ctypes.byref(dev), 1, ctypes.sizeof(dev)))
    except Exception:
        return False


def read_raw_key(lparam):
    """WM_INPUT 메시지 → (가상키, 뗐는지) / 키보드가 아니면 None"""
    try:
        size = wintypes.UINT(ctypes.sizeof(_raw_buf))
        got = user32.GetRawInputData(lparam, 0x10000003, ctypes.byref(_raw_buf), ctypes.byref(size),
                                     ctypes.sizeof(RAWINPUTHEADER))
        if got == 0xFFFFFFFF or _raw_buf.header.dwType != 1:
            return None
        return int(_raw_buf.keyboard.VKey), bool(_raw_buf.keyboard.Flags & 1)
    except Exception:
        return None
