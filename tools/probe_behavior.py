"""Render states and consume isolated signals through the real Tk pet.

No live save/config/quit or shared signal directory is modified.
"""
import importlib.util
import json
import random
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
spec = importlib.util.spec_from_file_location("behavior_pet", ROOT / "app" / "pet.pyw")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def main():
    mod.winutil.set_dpi_aware()
    checks, evidence = {}, {}
    with tempfile.TemporaryDirectory(prefix="pet-behavior-") as td:
        scratch = Path(td)
        shutil.copytree(ROOT / "app" / "lines", scratch / "lines")
        (scratch / "run").mkdir()
        signals = scratch / "signals"
        signals.mkdir()
        mod.APP, mod.SIGNALS_DIR = scratch, signals
        cfg = json.loads((ROOT / "app" / "config.json").read_text(encoding="utf-8"))
        cfg.update(requires_qoder=False, bind_qoder=False, follow_qoder=False,
                   tts_enabled=False, quiet_hours=[], muted=False)
        p = mod.Pet(cfg)
        p.next_speech = time.time() + 3600
        p.speech.rng = random.Random(17)
        visible = []
        show = p.show_bubble
        def observe(text, *a, **kw):
            show(text, *a, **kw)
            p.root.update_idletasks()
            if p.bubble.winfo_viewable() and p.bubble_label.cget("image") and p.bubble_photo.width() > 1:
                visible.append(text)
        p.show_bubble = observe
        def pump(seconds):
            end = time.time() + seconds
            while time.time() < end:
                p.root.update()
                time.sleep(0.02)
        def send(kind, ts=None):
            (signals / kind).write_text(json.dumps({"ts": time.time() if ts is None else ts,
                "kind": kind, "detail": "isolated behavior probe"}), encoding="utf-8")
        def poll():
            p.poll_signals(time.time())
            pump(0.08)
        try:
            pump(0.3)
            checks["window_visible"] = bool(p.root.winfo_viewable())
            for state in sorted(p.extra_states):
                p.force(state, 1.0)
                pump(0.12)
                checks["render_" + state] = p.state == state and p.current is not None
            before = len(visible)
            send("qoder.busy")
            poll()
            checks["busy_reaches_visible_bubble"] = len(visible) == before + 1 and not (signals / "qoder.busy").exists()
            before = len(visible)
            send("qoder.busy")
            poll()
            checks["same_kind_cooldown"] = len(visible) == before and not (signals / "qoder.busy").exists()
            for kind in ("qoder.done", "boss"):
                before = len(visible)
                send(kind)
                poll()
                checks[kind + "_reaches_visible_bubble"] = len(visible) == before + 1 and not (signals / kind).exists()
            before = len(visible)
            send("qoder.busy", time.time() - 600)
            poll()
            checks["expired_ignored"] = len(visible) == before and not (signals / "qoder.busy").exists()
            p.cfg["muted"] = True
            p.signal_cool.clear()
            send("qoder.done")
            poll()
            checks["muted_keeps_unspoken_signal"] = (signals / "qoder.done").exists()
            p.cfg["muted"] = False
            poll()
            checks["unmuted_consumes_signal"] = not (signals / "qoder.done").exists() and len(visible) == before + 1
            before = len(visible)
            original_title = mod.winutil.foreground_title
            mod.winutil.foreground_title = lambda: "ai-probe-video"
            p.cfg["boss_window_keywords"] = ["ai-probe-video"]
            p.boss_cool = 0
            poll()
            checks["boss_title_reaches_visible_bubble"] = len(visible) == before + 1
            before = len(visible)
            poll()
            checks["boss_title_cooldown"] = len(visible) == before
            mod.winutil.foreground_title = original_title
            evidence["visible_lines"] = visible
            evidence["states"] = sorted(p.extra_states)
        finally:
            p.cfg["muted"] = False
            p.quit(intent=False)
    out = {"checks": checks, "evidence": evidence, "pass": bool(checks) and all(checks.values())}
    (ROOT / "out").mkdir(exist_ok=True)
    (ROOT / "out" / "behavior.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=True))
    return 0 if out["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
