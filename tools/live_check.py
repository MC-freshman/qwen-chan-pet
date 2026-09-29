# -*- coding: utf-8 -*-
"""真实运行 20 秒：她动不动、报错日志有没有新增、窗口还在不在。

只做只读观察 + 按自己 Popen 出来的 PID 精确收尾；不合成鼠标键盘输入，不碰 run/quit。
wmic 在这台机上已被移除，所以她身份用"我拉起的那只 + 她自写的 run/pet.pid"来认。
"""
from __future__ import annotations

import ctypes as C
import subprocess
import sys
import time
from ctypes import wintypes as W
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
import winutil  # noqa: E402
from PIL import ImageGrab  # noqa: E402

APP = Path(__file__).resolve().parent.parent / "app"
LOG = APP / "run" / "pet.err.log"
PID_FILE = APP / "run" / "pet.pid"
OUT = Path(__file__).resolve().parent
DETACHED = 0x00000008
NO_WINDOW = 0x08000000


def logged_pid() -> int:
    try:
        return int(PID_FILE.read_text().strip())
    except (OSError, ValueError):
        return 0


def her_rect(pid: int) -> tuple[int, int, int, int] | None:
    """她自己的可见窗口；找不到就是循环停摆或窗口没建起来。"""
    found: list[int] = []

    def callback(hwnd, _lparam):
        if winutil.user32.IsWindowVisible(hwnd) and winutil.window_pid(hwnd) == pid:
            found.append(hwnd)
        return True

    proc = C.WINFUNCTYPE(C.c_bool, W.HWND, W.LPARAM)(callback)
    winutil._ENUM_PROCS.append(proc)
    try:
        winutil.user32.EnumWindows(proc, 0)
    finally:
        winutil._ENUM_PROCS.remove(proc)
    if not found:
        return None
    x, y, w, h = winutil.window_rect(found[0])
    return None if w <= 1 or h <= 1 else (x, y, w, h)


def new_log_bytes(before: int) -> str:
    if not LOG.exists():
        return ""
    return LOG.read_text(encoding="utf-8", errors="replace")[before:]


def main() -> int:
    winutil.set_dpi_aware()
    before = LOG.stat().st_size if LOG.exists() else 0
    existing = logged_pid()
    if existing and winutil.process_alive(existing):
        print("已经有一只在跑（pid %d），这次不拉第二只" % existing)
        return 0
    pythonw = sys.executable.replace("python.exe", "pythonw.exe")
    proc = subprocess.Popen([pythonw, str(APP / "pet.pyw")], cwd=str(APP),
                            creationflags=DETACHED | NO_WINDOW, close_fds=True,
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=open(LOG, "ab"))
    pid = proc.pid
    for _ in range(40):
        time.sleep(0.5)
        if winutil.process_alive(pid) and logged_pid() == pid:
            break
    else:
        print("FAIL 她没能把 pid 写进 run/pet.pid")
        print(new_log_bytes(before) or "（日志无新增）")
        subprocess.run(["taskkill", "/PID", str(pid), "/F"], creationflags=NO_WINDOW,
                       capture_output=True)
        return 1
    print("pid=%d 起来了，先让帧缓存热 12 秒" % pid)
    time.sleep(12)
    rect = her_rect(pid)
    if rect is None:
        # 她没起来通常不是停摆而是"按绑定走了"：本机 config.local.json 里
        # requires_qoder=true，而 Qoder 主窗口最小化时落在 -32000，面积判据直接不过。
        hwnd = winutil.qoder_main_window()
        why = "Qoder 主窗口找不到（被最小化？）" if not hwnd else "Qoder 主窗口在，她却没有窗口"
        print("FAIL 没有可见窗口：%s；进程还在=%s" % (why, winutil.process_alive(pid)))
        print(new_log_bytes(before) or "（日志无新增）")
        subprocess.run(["taskkill", "/PID", str(pid), "/F"], creationflags=NO_WINDOW,
                       capture_output=True)
        return 1
    shots = []
    for _ in range(5):
        r = her_rect(pid)
        if r is not None:
            shots.append(ImageGrab.grab((r[0], r[1], r[0] + r[2], r[1] + r[3])))
        time.sleep(0.3)
    print("  窗口 %dx%d @%d,%d，抓到 %d 张" % (rect[2], rect[3], rect[0], rect[1], len(shots)))
    added = new_log_bytes(before)
    alive = winutil.process_alive(pid)
    frames_differ = len({im.tobytes() for im in shots}) > 1
    for name, image in (("live_check.png", shots[0] if shots else None),
                        ("live_check_last.png", shots[-1] if len(shots) > 1 else None)):
        if image is not None:
            image.save(OUT / name)
    subprocess.run(["taskkill", "/PID", str(pid), "/F"], creationflags=NO_WINDOW,
                   capture_output=True)
    time.sleep(1.0)
    PID_FILE.unlink(missing_ok=True)
    print("进程还在=%s  连续截图互不相同=%s（她在动）" % (alive, frames_differ))
    print("截图 out/live_check.png 与 out/live_check_last.png")
    if added:
        print("=== 这 20 秒新增的报错 ===")
        print(added[:4000])
    else:
        print("报错日志零新增")
    ok = alive and frames_differ and not added
    print("%s 实况验收" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
