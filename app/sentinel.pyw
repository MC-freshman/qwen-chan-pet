"""Resident supervisor for the pet, in one of two modes (config `bind_qoder`).

bound  — she appears while Qoder runs and leaves once it stops.
open   — she is a standalone pet: started regardless of Qoder, restarted if she dies,
         and never killed because Qoder went away. run/quit then means "not until the
         next logon", since the sentinel clears it when it itself starts.

Costs about one window scan every 3s in bound mode; in open mode no scan at all.
"""

from __future__ import annotations

import json
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
MAX_BACKOFF = 300.0   # 启动即崩时最长退避，之后每 5 分钟仍再试一次
CRASH_SECONDS = 8.0   # 起来这么久还没落地 pid 就算这一次启动失败

ERROR_ALREADY_EXISTS = 183


def bind_qoder() -> bool:
    """出厂默认独立（false）：下载的人手动跑起来就该是一只独立桌宠。

    只在启动时读一次——改这个开关要重启哨兵，别在轮询里读盘。
    """
    try:
        cfg = json.loads((APP / "config.json").read_text(encoding="utf-8"))
        local = APP / "config.local.json"
        if local.exists():
            cfg.update(json.loads(local.read_text(encoding="utf-8")))
    except (OSError, ValueError) as e:      # 配置坏了也要能起来，按默认独立跑
        print("config 读不动，按独立模式跑：%s" % e, file=sys.stderr)
        return False
    return bool(cfg.get("bind_qoder", False))


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
    log_path = RUN / "pet.err.log"
    if log_path.exists() and log_path.stat().st_size > 256 * 1024:
        log_path.write_text("", encoding="utf-8")   # 别让它无声地长满盘
    log = open(log_path, "ab")
    try:
        subprocess.Popen(
            [sys.executable, str(PET)],
            cwd=str(APP),
            creationflags=DETACHED_PROCESS | CREATE_NO_WINDOW,
            close_fds=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=log,   # 异常只进 DEVNULL 的话，她定格时现场什么都查不到
        )
    finally:
        log.close()


def main() -> None:
    RUN.mkdir(exist_ok=True)
    hold_singleton()
    pythonw = Path(sys.executable).name.lower()
    if pythonw != "pythonw.exe":
        print("提示：用 pythonw.exe 启动哨兵才不会留控制台窗口", file=sys.stderr)
    qoder_since: float | None = None
    bound = bind_qoder()
    if not bound:
        # 独立模式：run/quit 的有效期是"本次开机"，哨兵一起来就把它作废
        QUIT_FLAG.unlink(missing_ok=True)
    qoder_was_up = bool(winutil.process_ids(winutil.QODER_EXE)) if bound else False
    session = 0
    if bound:
        first = winutil.qoder_main_window()
        session = winutil.window_pid(first) if first else 0
    last_start: float | None = None
    unhealthy_since: float | None = None   # 这一串连续"她不在"是从什么时候开始的
    blocked_until = 0.0
    healthy = False      # 这一次拉起来之后见过她还活着吗
    crash_streak = 0
    while True:
        if bound:
            running = bool(winutil.process_ids(winutil.QODER_EXE))
            current_session = 0
            hwnd = winutil.qoder_main_window()
            if hwnd:
                current_session = winutil.window_pid(hwnd)
            if (qoder_was_up and not running) or (current_session and session and current_session != session):
                # 命中任一都算"新的一段 Qoder 会话"：
                # 1) Qoder 关过一轮 = 上一次"别烦我"作废；
                # 2) 主窗口换了进程 = 新会话。光靠"关过一轮"不够：她自己的看门狗在 Qoder 关闭
                #    十几秒后才退出，那时标记已经被清掉，它又把标记写了回来，于是下次开机永远不醒。
                # 崩溃退避也一起作废——否则上一段会话里数到的 5 分钟等待会拖住这一段的开机。
                QUIT_FLAG.unlink(missing_ok=True)
                blocked_until, crash_streak = 0.0, 0
                unhealthy_since, last_start, healthy = None, None, False
            if current_session:
                session = current_session
            qoder_was_up = running
        else:
            running = True        # 独立模式：她在不在和 Qoder 无关，也不去扫窗口
        current = pet_pid()
        alive = current and winutil.process_alive(current)
        if running:
            qoder_since = None
            if alive:
                healthy, unhealthy_since = True, None
            elif not QUIT_FLAG.exists():
                now = time.time()
                if unhealthy_since is None:
                    unhealthy_since = last_start if last_start is not None else now
                if now >= blocked_until:
                    # 拉起来 8 秒还没见过她的 pid 落地 = 启动即崩：指数退避。
                    # 按"这一串连续失败"的起点计时而不是上一次启动时间，因为慢启动的
                    # 每一次尝试都会把 last_start 往前挪，用它的间隔永远数不出崩溃。
                    # 没有这层退避，素材缺失或配置抛错会被每 3 秒重拉一次、永远拉不起来。
                    if not healthy and now - unhealthy_since > CRASH_SECONDS:
                        crash_streak += 1
                    else:
                        crash_streak = 0
                    start_pet()
                    last_start, healthy = now, False
                    blocked_until = now + min(MAX_BACKOFF, POLL_SECONDS * 2 ** crash_streak)
                    if crash_streak:
                        print("qwen娘 启动即退出，连续 %d 次：%.0fs 后再试"
                              % (crash_streak, blocked_until - now), file=sys.stderr)
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
