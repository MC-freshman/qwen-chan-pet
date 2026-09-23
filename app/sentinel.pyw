"""Resident sentinel: she appears while Qoder runs and leaves once it stops.

Starts nothing when Qoder is closed, and costs about one window scan every 3s.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import winutil

APP = Path(__file__).resolve().parent
RUN = APP / "run"
PET = APP / "pet.pyw"
PET_PID = RUN / "pet.pid"
QUIT_FLAG = RUN / "quit"
POLL_SECONDS = 3.0
GRACE_SECONDS = 20.0  # the pet has its own watchdog; this only cleans up strays

ERROR_ALREADY_EXISTS = 183


def hold_singleton() -> int:
    """A named mutex keeps exactly one sentinel alive across logon and manual starts."""
    handle = winutil.kernel32.CreateMutexW(None, False, "Local\\qwen-chan-sentinel")
    if winutil.kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        if handle:
            winutil.kernel32.CloseHandle(handle)
        raise SystemExit("sentinel already running")
    return handle


def pet_pid() -> int:
    if not PET_PID.exists():
        return 0
    try:
        return int(PET_PID.read_text().strip())
    except ValueError:
        return 0


def start_pet() -> None:
    DETACHED_PROCESS = 0x00000008
    CREATE_NO_WINDOW = 0x08000000
    subprocess.Popen(
        [sys.executable, str(PET)],
        cwd=str(APP),
        creationflags=DETACHED_PROCESS | CREATE_NO_WINDOW,
        close_fds=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def main() -> None:
    RUN.mkdir(exist_ok=True)
    hold_singleton()
    pythonw = Path(sys.executable).name.lower()
    if pythonw != "pythonw.exe":
        print("提示：用 pythonw.exe 启动哨兵才不会留控制台窗口", file=sys.stderr)
    qoder_since: float | None = None
    qoder_was_up = bool(winutil.process_ids(winutil.QODER_EXE))
    session = winutil.window_pid(winutil.qoder_main_window()) if winutil.qoder_main_window() else 0
    while True:
        running = bool(winutil.process_ids(winutil.QODER_EXE))
        current_session = 0
        hwnd = winutil.qoder_main_window()
        if hwnd:
            current_session = winutil.window_pid(hwnd)
        if qoder_was_up and not running:
            QUIT_FLAG.unlink(missing_ok=True)   # Qoder 关过一轮 = 上一次"别烦我"作废
        elif current_session and session and current_session != session:
            # 主窗口换了进程 = 新会话。光靠"关过一轮"不够：她自己的看门狗在 Qoder 关闭
            # 十几秒后才退出，那时标记已经被清掉，它又把标记写了回来，于是下次开机永远不醒。
            QUIT_FLAG.unlink(missing_ok=True)
        if current_session:
            session = current_session
        qoder_was_up = running
        current = pet_pid()
        alive = current and winutil.process_alive(current)
        if running:
            qoder_since = None
            if not alive and not QUIT_FLAG.exists():
                start_pet()
        elif alive:
            # Pet's own watchdog should have quit; only force-kill after a grace period.
            if qoder_since is None:
                qoder_since = time.time()
            elif time.time() - qoder_since > GRACE_SECONDS:
                subprocess.run(
                    ["taskkill", "/PID", str(current), "/F"],
                    creationflags=0x08000000,
                    capture_output=True,
                )
                PET_PID.unlink(missing_ok=True)
                qoder_since = None
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
