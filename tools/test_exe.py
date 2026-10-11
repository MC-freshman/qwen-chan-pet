"""Launch the rebuilt exe, inspect its own windows, then restore local state.

The ready marker keeps the instance alive for computer-use menu acceptance.
Only exact project script paths qualify for process stop/restart.
"""
import ctypes as C
import hashlib
import json
import subprocess
import sys
import time
from ctypes import wintypes as W
from pathlib import Path
import psutil
from PIL import ImageGrab, ImageChops

root = Path(__file__).resolve().parents[1]
name = "qwen娘"
app = root / ("shell" if name == "grok娘" else "app")
target, sentinel = app / "pet.pyw", app / "sentinel.pyw"
sys.path.insert(0, str(root / ("brain" if name == "grok娘" else "app")))
import winutil
winutil.set_dpi_aware()
user32 = C.windll.user32
local = app / "config.local.json"
files = [local, app / "save.json", app / "run/quit", app / "run/pet.pid"]
backups = {p: p.read_bytes() if p.exists() else None for p in files}
out = root / "out"
out.mkdir(exist_ok=True)
finish = out / "exe_finish"
finish.unlink(missing_ok=True)
restarts = []


def matches(script):
    found = []
    for p in psutil.process_iter(["pid", "cmdline", "create_time"]):
        try:
            if any(Path(a).is_absolute() and Path(a).resolve() == script.resolve() for a in p.info["cmdline"] or []):
                found.append(p)
        except (OSError, psutil.Error):
            pass
    return found


def visible_rect(pid):
    found = []
    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd) and winutil.window_pid(hwnd) == pid:
            x,y,w,h = winutil.window_rect(hwnd)
            if w > 80 and h > 80:
                found.append((w*h, (x,y,x+w,y+h)))
        return True
    callback = C.WINFUNCTYPE(C.c_bool, W.HWND, W.LPARAM)(cb)
    user32.EnumWindows(callback, 0)
    return max(found)[1] if found else None


checks, evidence = {}, {}
owned = []
try:
    for p in matches(sentinel):
        restarts.append(p.cmdline())
        p.terminate()
        p.wait(5)
    for p in matches(target):
        if not restarts:
            restarts.append(p.cmdline())
        p.terminate()
        p.wait(5)
    cfg = json.loads(local.read_text(encoding="utf-8")) if local.exists() else {}
    cfg.update(requires_qoder=False, bind_qoder=False, follow_qoder=False,
               tts_enabled=False, quiet_hours=[], muted=False)
    local.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    exe = root / (name + "独立启动.exe")
    log_path = app / "run/pet.exe.log"
    log_start = log_path.stat().st_size if log_path.exists() else 0
    t0 = time.time()
    launch = subprocess.Popen([str(exe)], cwd=root)
    deadline = time.time() + 50
    pid, rect = None, None
    while time.time() < deadline:
        pets = [p for p in matches(target) if p.create_time() >= t0 - 1]
        if pets:
            owned = pets
            pid = pets[0].pid
            rect = visible_rect(pid)
            if rect:
                break
        time.sleep(0.2)
    checks["cold_start_visible_window"] = bool(pid and rect)
    if rect:
        if name == "grok娘":
            deadline = time.time() + 45
            startup = None
            while time.time() < deadline:
                log = log_path.read_bytes()[log_start:].decode("utf-8", errors="replace")
                rows = [line.split("renderer-startup ",1)[1] for line in log.splitlines() if line.startswith("renderer-startup ")]
                if rows:
                    startup = json.loads(rows[-1])
                    if startup and (startup.get("boot") or {}).get("ok"):
                        break
                time.sleep(0.2)
            checks["renderer_boot_ready"] = bool(startup and (startup.get("boot") or {}).get("ok"))
            evidence["renderer_startup"] = startup
        time.sleep(2)
        rect = visible_rect(pid)
        a = ImageGrab.grab(bbox=rect, all_screens=True)
        a.save(out / "exe_start.png")
        time.sleep(1.3)
        b = ImageGrab.grab(bbox=visible_rect(pid), all_screens=True)
        b.save(out / "exe_motion.png")
        checks["animation_changes_pixels"] = a.size == b.size and ImageChops.difference(a,b).getbbox() is not None
        checks["still_alive_after_warmup"] = psutil.pid_exists(pid)
        subprocess.Popen([str(exe)], cwd=root).wait(timeout=15)
        time.sleep(1.5)
        checks["second_launch_keeps_single_instance"] = len(matches(target)) == 1 and psutil.pid_exists(pid)
        evidence.update(pid=pid, rect=rect, cold_start_seconds=round(time.time()-t0,2),
                        exe_sha256=hashlib.sha256(exe.read_bytes()).hexdigest())
        print("READY " + json.dumps({"name": name, "pid": pid, "checks": checks}, ensure_ascii=True), flush=True)
        deadline = time.time() + (900 if "--hold" in sys.argv else 0)
        while not finish.exists() and time.time() < deadline and psutil.pid_exists(pid):
            time.sleep(0.2)
    else:
        print("FAIL no visible pet window", flush=True)
finally:
    for p in owned:
        try:
            if p.is_running():
                p.terminate()
                p.wait(5)
        except psutil.Error:
            pass
    for p, data in backups.items():
        if data is None:
            p.unlink(missing_ok=True)
        else:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
    for cmd in restarts:
        subprocess.Popen(cmd, cwd=app, creationflags=0x08000000,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    finish.unlink(missing_ok=True)
    result = {"checks": checks, "evidence": evidence, "pass": bool(checks) and all(checks.values())}
    (out / "exe.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=True), flush=True)
raise SystemExit(0 if result["pass"] else 1)
