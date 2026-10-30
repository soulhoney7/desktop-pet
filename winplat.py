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
