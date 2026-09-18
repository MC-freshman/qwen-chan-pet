"""Win32 helpers used by both the sentinel and the pet.

Every call here is local and read-only: no network, no model, no token.
"""

from __future__ import annotations

import ctypes as C
import re
from ctypes import wintypes as W

user32 = C.windll.user32
kernel32 = C.windll.kernel32

QODER_EXE = "qoder.exe"
ELECTRON_CLASS = "Chrome_WidgetWin_1"
HELPER_TITLES = {"Qoder Desktop Pet", "Qoder Companion Activity"}

_ENUM_PROCS = []  # keep callbacks alive or Windows calls freed memory


class _ProcEntry(C.Structure):
    _fields_ = [
        ("dwSize", W.DWORD),
        ("cntUsage", W.DWORD),
        ("th32ProcessID", W.DWORD),
        ("th32DefaultHeapID", C.c_size_t),
        ("th32ModuleID", W.DWORD),
        ("cntThreads", W.DWORD),
        ("th32ParentProcessID", W.DWORD),
        ("pcPriClassBase", C.c_long),
        ("dwFlags", W.DWORD),
        ("szExeFile", W.WCHAR * 260),
    ]


def set_dpi_aware() -> None:
    """Ask Windows for real pixels; otherwise every coordinate is virtualised."""
    try:
        if user32.SetProcessDpiAwarenessContext(C.c_void_p(-4)):  # PER_MONITOR_AWARE_V2
            return
    except AttributeError:
        pass
    try:
        C.windll.shcore.SetProcessDpiAwareness(2)
        return
    except (AttributeError, OSError):
        pass
    user32.SetProcessDPIAware()


def system_scale() -> float:
    """Desktop scale factor, e.g. 1.75 for 175%. Call after set_dpi_aware()."""
    try:
        dpi = C.windll.user32.GetDpiForSystem()
        if dpi:
            return dpi / 96.0
    except AttributeError:
        pass
    return 1.0


def _walk_processes() -> dict[int, str]:
    kernel32.CreateToolhelp32Snapshot.restype = W.HANDLE
    snap = kernel32.CreateToolhelp32Snapshot(0x2, 0)
    if snap in (0, W.HANDLE(-1).value):
        return {}
    entry = _ProcEntry()
    entry.dwSize = C.sizeof(entry)
    found: dict[int, str] = {}
    # Process32First/Next resolve to the ANSI variants unless asked explicitly.
    first, nxt = kernel32.Process32FirstW, kernel32.Process32NextW
    ok = first(snap, C.byref(entry))
    while ok:
        found[entry.th32ProcessID] = entry.szExeFile.lower()
        ok = nxt(snap, C.byref(entry))
    kernel32.CloseHandle(snap)
    return found


def process_ids(image_name: str) -> set[int]:
    """PIDs whose executable matches image_name (case-insensitive)."""
    wanted = image_name.lower()
    return {pid for pid, name in _walk_processes().items() if name == wanted}


def all_pids() -> set[int]:
    return set(_walk_processes())


def process_alive(pid: int) -> bool:
    """Handle-based probing is unreliable here, so consult the process snapshot."""
    if not pid:
        return False
    return pid in all_pids()


def _window_text(hwnd) -> str:
    buffer = C.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, buffer, 512)
    return buffer.value


def _window_class(hwnd) -> str:
    buffer = C.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buffer, 256)
    return buffer.value


def _window_pid(hwnd) -> int:
    pid = W.DWORD()
    user32.GetWindowThreadProcessId(hwnd, C.byref(pid))
    return pid.value


def window_rect(hwnd) -> tuple[int, int, int, int]:
    rect = W.RECT()
    user32.GetWindowRect(hwnd, C.byref(rect))
    return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top


def qoder_main_window() -> int | None:
    """Largest visible Qoder window that is not one of Qoder's own overlays."""
    pids = process_ids(QODER_EXE)
    if not pids:
        return None
    best: tuple[int, int] | None = None

    def callback(hwnd, _lparam):
        nonlocal best
        if not user32.IsWindowVisible(hwnd) or _window_pid(hwnd) not in pids:
            return True
        title = _window_text(hwnd)
        if not title or title in HELPER_TITLES or _window_class(hwnd) != ELECTRON_CLASS:
            return True
        rect = W.RECT()
        user32.GetWindowRect(hwnd, C.byref(rect))
        area = (rect.right - rect.left) * (rect.bottom - rect.top)
        if area > 120_000 and (best is None or area > best[0]):
            best = (area, hwnd)
        return True

    proc_type = C.WINFUNCTYPE(C.c_bool, W.HWND, W.LPARAM)
    proc = proc_type(callback)
    _ENUM_PROCS.append(proc)
    try:
        user32.EnumWindows(proc, 0)
    finally:
        _ENUM_PROCS.remove(proc)
    return best[1] if best else None


def foreground_title() -> str:
    return _window_text(user32.GetForegroundWindow())


_IDLE_INFO_CLASS = 3


class _LastInputInfo(C.Structure):
    _fields_ = [("cbSize", W.DWORD), ("dwTime", W.DWORD)]


def idle_seconds() -> float:
    """Seconds since the last keyboard/mouse input, for "主人还在忙吗"."""
    info = _LastInputInfo()
    info.cbSize = C.sizeof(info)
    if not user32.GetLastInputInfo(C.byref(info)):
        return 0.0
    tick = kernel32.GetTickCount()
    return max(0.0, (tick - info.dwTime) / 1000.0)


_PROJECT_RE = re.compile(r"([A-Za-z0-9_\-.]+\.[A-Za-z]{1,5})\s*-")


def foreground_file(title: str) -> str:
    match = _PROJECT_RE.search(title)
    return match.group(1) if match else ""
