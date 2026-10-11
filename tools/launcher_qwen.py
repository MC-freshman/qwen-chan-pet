"""Small GUI launcher for the independent qwen娘 process."""

from pathlib import Path
import ctypes
import os
import shutil
import subprocess
import sys
import time
import traceback


def launch_logged(python_exe, target):
    """Keep startup diagnostics for both source and packaged launchers."""
    run = target.parent / "run"
    run.mkdir(exist_ok=True)
    path = run / "pet.exe.log"
    if path.exists() and path.stat().st_size > 256 * 1024:
        os.replace(path, run / "pet.exe.log.1")
    flags = (getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
             | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
             | getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))
    with path.open("ab", buffering=0) as log:
        log.write(("\n[%s] launch interpreter=%s target=%s\n"
                   % (time.strftime("%Y-%m-%d %H:%M:%S"), python_exe, target)).encode("utf-8"))
        try:
            child = subprocess.Popen([str(python_exe), str(target)], cwd=str(target.parent),
                                     creationflags=flags, close_fds=True,
                                     stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                     env=os.environ.copy())
        except OSError:
            log.write(traceback.format_exc().encode("utf-8"))
            raise
        log.write(("spawned pid=%d\n" % child.pid).encode("utf-8"))
    return child


def main() -> None:
    root = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) \
        else Path(__file__).resolve().parents[1]
    target = root / "app" / "pet.pyw"
    candidates = [
        shutil.which("python.exe"),
        shutil.which("pythonw.exe"),
        r"D:\Various_programming_languages\pycharm\python3.9\python.exe",
        r"D:\Various_programming_languages\pycharm\python3.9\pythonw.exe",
    ]
    python_exe = next((p for p in candidates if p and Path(p).exists()), None)
    if not python_exe:
        ctypes.windll.user32.MessageBoxW(0, "找不到 Python，请先安装并加入 PATH。", "qwen娘", 0x10)
        return
    if not target.exists():
        ctypes.windll.user32.MessageBoxW(0, f"找不到启动文件：{target}", "qwen娘", 0x10)
        return
    try:
        launch_logged(python_exe, target)
    except OSError as exc:
        ctypes.windll.user32.MessageBoxW(
            0, f"启动失败：{exc}\\n详见 {target.parent / 'run' / 'pet.exe.log'}", "qwen娘", 0x10)


if __name__ == "__main__":
    main()
