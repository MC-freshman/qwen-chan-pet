"""Regression for real child stderr, startup failures and bounded log rotation."""
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
NAME = next(p for p in (ROOT / "tools").glob("launcher_*.py"))
spec = importlib.util.spec_from_file_location("launcher_probe", NAME)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def main():
    with tempfile.TemporaryDirectory(prefix="pet-launcher-") as td:
        target = Path(td) / "pet.pyw"
        target.write_text("import sys\nprint('child-stdout-marker', flush=True)\nraise RuntimeError('child-crash-marker')\n", encoding="utf-8")
        run = target.parent / "run"
        run.mkdir()
        log = run / "pet.exe.log"
        log.write_bytes(b"x" * (256 * 1024 + 1))
        child = mod.launch_logged(sys.executable, target)
        code = child.wait(timeout=15)
        content = log.read_text(encoding="utf-8")
        checks = {"child_failure_captured": code != 0 and "child-crash-marker" in content and "Traceback" in content,
                  "child_stdout_captured": "child-stdout-marker" in content,
                  "startup_pid_recorded": "spawned pid=%d" % child.pid in content,
                  "oversize_log_rotated": (run / "pet.exe.log.1").stat().st_size == 256 * 1024 + 1,
                  "current_log_bounded": log.stat().st_size < 256 * 1024}
        with patch.object(mod.subprocess, "Popen", side_effect=OSError("spawn-failure-marker")):
            try:
                mod.launch_logged(sys.executable, target)
            except OSError:
                pass
        checks["spawn_failure_captured"] = "spawn-failure-marker" in log.read_text(encoding="utf-8")
    out = {"checks": checks, "pass": all(checks.values())}
    (ROOT / "out").mkdir(exist_ok=True)
    (ROOT / "out" / "launcher.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out))
    return 0 if out["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
