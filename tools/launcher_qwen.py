"""Small GUI launcher for the independent qwen娘 process."""

from pathlib import Path
import ctypes
import os
import shutil
import subprocess
import sys


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
    flags = getattr(subprocess, "DETACHED_PROCESS", 0x00000008) | \
        getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
    subprocess.Popen([python_exe, str(target)], cwd=str(target.parent),
                     creationflags=flags, close_fds=True,
                     env=os.environ.copy())


if __name__ == "__main__":
    main()
