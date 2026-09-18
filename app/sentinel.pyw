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
    while True:
        running = bool(winutil.process_ids(winutil.QODER_EXE))
        current = pet_pid()
        alive = current and winutil.process_alive(current)
        if running:
            qoder_since = None
            if not alive:
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
