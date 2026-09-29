# -*- coding: utf-8 -*-
"""逐行审计的修复判据：每一项都用真代码跑一遍，坏了就退出码 1。

不建 Tk 窗口：需要 Pet 的项用 Pet.__new__ 只装它自己用到的字段，
需要窗口的定格/缓存问题另用一次真实运行来验（见 README 的验收记录）。
"""

from __future__ import annotations

import importlib.util
import json
import random
import sys
import tempfile
import time
import types
from importlib.machinery import SourceFileLoader
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
sys.path.insert(0, str(APP))

from PIL import Image  # noqa: E402

import needs  # noqa: E402
import rigor  # noqa: E402
import speech as speech_mod  # noqa: E402
import winutil  # noqa: E402

spec = importlib.util.spec_from_loader(
    "qwenpet", SourceFileLoader("qwenpet", str(APP / "pet.pyw")))
pet = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pet)

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))
    print("%s %s%s" % ("PASS" if ok else "FAIL", name, ("  | " + detail) if detail else ""))


# ---------------------------------------------------------------- A: 信号目录
def test_signals() -> None:
    got = pet.SIGNALS_DIR
    check("A1 SIGNALS_DIR 指向共享目录 E:\\桌宠\\signals",
          got == Path("E:/桌宠/signals"), str(got))
    check("A2 信号目录真的存在", got.is_dir(), str(got))
    check("A3 hook 写的三个 kind 都在协议里",
          {"qoder.busy", "qoder.done", "boss"} <= set(pet.SIGNAL_KINDS),
          str(pet.SIGNAL_KINDS))
    stub = pet.Pet.__new__(pet.Pet)
    stub.signal_cool = {}
    stub.cfg = {"signal_cooldown_seconds": 60}
    said: list[str] = []
    stub.say = lambda text: said.append(text)
    stub.line_vars = lambda: {"file": "", "seen": 1, "hour": 12, "days": 1, "minutes": 1,
                              "app": "Qoder", "energy": 50, "mood": 50, "affection": 50,
                              "gap_min": 0, "gap_hour": 0}
    life = needs.Life(Path(tempfile.mkdtemp()) / "save.json")
    stub.speech = speech_mod.Speech(APP / "lines" / "zh.json", life, random.Random(1))
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        pet.SIGNALS_DIR = tmp          # 不碰真目录里别人的信号文件
        (tmp / "qoder.busy").write_text(json.dumps({"ts": time.time()}), encoding="utf-8")
        (tmp / "boss").write_text(json.dumps({"ts": time.time()}), encoding="utf-8")
        stub.poll_signals(time.time() + 1.0)
        left = sorted(p.name for p in tmp.iterdir())
    check("A4 写好的信号被说出来了（说到才删）", len(said) >= 1, "said=%r left=%r" % (said, left))
    check("A5 boss 信号也进协议（旧版只认 busy/done）", "boss" in left or len(said) >= 2,
          "left=%r" % (left,))


# ------------------------------------------------- B: context_line 不再被饿死
def test_context_line() -> None:
    tmp = Path(tempfile.mkdtemp()) / "save.json"
    obj = pet.Pet.__new__(pet.Pet)
    obj.life = needs.Life(tmp)
    obj.life.needs.update({"energy": 5.0, "mood": 60.0, "affection": 60.0, "curiosity": 50.0})
    obj.rng = random.Random(3)
    obj.speech = speech_mod.Speech(APP / "lines" / "zh.json", obj.life, obj.rng)
    obj.cfg = {"idle_user_seconds": 10 ** 9, "long_work_minutes": 10 ** 9}
    obj.state = "idle"
    obj.qoder_hwnd = 1
    obj.pinned = True
    obj.offline_gap = 0.0
    obj.session_start = time.time() - 3600.0
    now = time.time()
    pool = [text for _id, text in obj.speech.candidates("needs", "low_energy")]
    first = pet.Pet.context_line(obj, now)
    second = pet.Pet.context_line(obj, now)
    third = pet.Pet.context_line(obj, now)
    check("B1 第一句来自 energy 分支", first in pool, repr(first))
    check("B2 子键冷却内第二句仍要说得出（旧版这里是 None）", bool(second), repr(second))
    check("B3 连说三句不重复", len({first, second, third}) == 3,
          "%r / %r / %r" % (first, second, third))
    # 整条链都被堵住时才算真的没词：把 AMBIENT 的所有子键都冷却掉
    cooled = 0
    for _ in range(400):
        if pet.Pet.context_line(obj, now) is None:
            cooled += 1
    check("B4 跑满之后会出现冷却完的静默（说明不是无限回落）", cooled > 0, "None 次数=%d" % cooled)


# ------------------------------------------------- C: 地标缺失时不再抛错
def test_landmarks() -> None:
    layer = rigor.LifeLayer(random.Random(5))
    layer.set_landmarks(None, None)
    layer.next_glance = layer.t0            # 立刻进入东张西望
    layer.next_turn = layer.t0
    layer.next_blink = layer.t0
    try:
        for step in range(4000):            # 模拟 ~600s 的每一帧
            layer.offsets(269.0, layer.t0 + step * 0.15)
        ok, detail = True, "4000 帧无地标不抛错"
    except TypeError as e:
        ok, detail = False, "TypeError: %s" % e
    check("C1 chin 地标缺失时 offsets 不炸", ok, detail)
    layer.set_landmarks(120.0, 160.0)
    prof = layer.offsets(269.0, layer.t0 + 30.0)
    check("C2 有地标时头部动作仍然生效（不是整段关掉）",
          float(abs(prof).max()) > 0.0, "max|profile|=%.3f" % float(abs(prof).max()))
    check("C3 rig.json 覆盖 12 个态且都有地标",
          all((v.get("eye") is not None and v.get("chin") is not None)
              for v in json.loads((APP / "frames" / "rig.json").read_text(encoding="utf-8")).values()),
          "见 app/frames/rig.json")


# ------------------------------------------------- D: 点击分区对着画出去那张
def test_zone() -> None:
    obj = pet.Pet.__new__(pet.Pet)
    obj.rig = {}
    obj.state = "idle"
    base = Image.new("RGBA", (60, 200), (10, 10, 10, 255))       # 底图：整块都不透明
    drawn = Image.new("L", (60, 200), 0)                          # 实际画出去的剪影
    drawn.putpixel((5, 100), 255)
    obj.current = base
    obj.current_alpha = drawn
    hit = pet.Pet.zone_at(obj, 30, 100)      # 底图上是她、画出来是空气
    air = pet.Pet.zone_at(obj, 5, 100)       # 画出来是她的头顶
    obj.current_alpha = None
    fallback = pet.Pet.zone_at(obj, 30, 100)
    check("D1 剪影外的点判成空气", hit is None, repr(hit))
    check("D2 剪影内的点仍能分到部位", air is not None, repr(air))
    check("D3 没有缓存剪影时退回底图轮廓", fallback is not None, repr(fallback))


# ------------------------------------------------- E: 退出后菜单回调不再抛错
def test_menu() -> None:
    obj = pet.Pet.__new__(pet.Pet)
    obj.quitting = True
    obj.menu = None          # 守卫失效时这里会 AttributeError，正是旧版 TclError 的形状
    obj.refresh_menu = lambda: (_ for _ in ()).throw(AssertionError("还去改菜单文案了"))
    event = types.SimpleNamespace(x_root=0, y_root=0)
    try:
        pet.Pet.on_menu(obj, event)
        ok, detail = True, "quitting=True 时一个 Tk 调用都不发"
    except Exception as e:
        ok, detail = False, "%s: %s" % (type(e).__name__, e)
    check("E1 on_menu 在退出之后静默返回", ok, detail)
    try:
        pet.Pet.refresh_menu(obj)
        ok, detail = True, "refresh_menu 同样早退"
    except Exception as e:
        ok, detail = False, "%s: %s" % (type(e).__name__, e)
    check("E2 refresh_menu 在退出之后静默返回", ok, detail)


# ------------------------------------------------- F: 甩掷阈值看位移
def test_throw() -> None:
    obj = pet.Pet.__new__(pet.Pet)
    obj.drag_trace = []
    trace = [(0.0, 0, 0), (0.1, -300, 0), (0.2, -600, 0)]   # 0.2s 内向左 600px
    vx, vy = pet.velocity_from_trace(trace)
    check("F1 轨迹速度算得对", vx < -2000, "vx=%.1f vy=%.1f" % (vx, vy))
    text = (APP / "pet.pyw").read_text(encoding="utf-8")
    check("F2 甩掷判据用像素位移而不是事件个数",
          "speed > 1500 and self.moved_px > 60" in text, "见 on_release")


# ------------------------------------------------- G: TTS 配错不该永久静音
def test_tts() -> None:
    import tts as tts_mod

    played: list[str] = []
    real = tts_mod.winsound
    tts_mod.winsound = types.SimpleNamespace(      # 探针不出声
        PlaySound=lambda *a, **k: played.append(str(a)),
        SND_FILENAME=1, SND_ASYNC=2, SND_PURGE=4)
    bad = None
    try:
        bad = tts_mod.TTS(Path(tempfile.mkdtemp()), enabled=True,
                          voice="__not_a_voice__", rate="fast")
        bad.speak("语速写成非法的也要开口")
        ok = False
        for _ in range(120):
            time.sleep(0.25)
            if bad.last_synth_ms > 0:
                ok = True
                break
        wav = next(iter(bad.cache_dir.glob("*.wav")), None)
        check("G1 语速写非法值时她仍能开口（旧版整条链静音）",
              ok and "rate set" in bad.last_error,
              "抛过错但没静音=%r last_error=%r synth_ms=%.0f"
              % ("rate set" in bad.last_error, bad.last_error, bad.last_synth_ms))
        check("G2 合成结果进了缓存", wav is not None and wav.stat().st_size > 44, str(wav))
        check("G3 播放调用没丢", bool(played), str(played[:1]))
        src = (APP / "pet.pyw").read_text(encoding="utf-8")
        check("G4 宠物侧读非法 tts_rate 不再抛在 __init__", "tts_rate = 0" in src,
              "见 Pet.__init__")
    finally:
        tts_mod.winsound = real
        if bad is not None:
            bad.purge()


# ------------------------------------------------- H: 哨兵的崩溃退避
class _FakeTime:
    def __init__(self, limit: int | None = None) -> None:
        self.now = 1000.0
        self.limit = limit
        self.slept = 0

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds
        self.slept += 1
        if self.limit is not None and self.slept > self.limit:
            raise KeyboardInterrupt


def test_sentinel() -> None:
    import sentinel

    tmp = Path(tempfile.mkdtemp())
    ft = _FakeTime()
    real_time, real_winutil = sentinel.time, sentinel.winutil
    real_run, real_pid, real_flag = sentinel.RUN, sentinel.PET_PID, sentinel.QUIT_FLAG
    starts: list[float] = []
    polls = {"n": 0}

    class FakeWinutil:
        QODER_EXE = "qoder.exe"

        @staticmethod
        def process_ids(_name):
            polls["n"] += 1
            if polls["n"] > 200:
                raise KeyboardInterrupt
            return {4242}                      # 假装 Qoder 一直开着

        @staticmethod
        def qoder_main_window():
            return 0

        @staticmethod
        def window_pid(_hwnd):
            return 0

        @staticmethod
        def process_alive(_pid):
            return False                       # 她每次起来就没了

    sentinel.time = ft
    sentinel.winutil = FakeWinutil
    sentinel.RUN = tmp / "run"
    sentinel.PET_PID = tmp / "run" / "pet.pid"
    sentinel.QUIT_FLAG = tmp / "run" / "quit"
    sentinel.hold_singleton = lambda: 0
    sentinel.start_pet = lambda: starts.append(sentinel.time.time())
    try:
        try:
            sentinel.main()
        except KeyboardInterrupt:
            pass
    finally:
        sentinel.time, sentinel.winutil = real_time, real_winutil
        sentinel.RUN, sentinel.PET_PID, sentinel.QUIT_FLAG = real_run, real_pid, real_flag
    gaps = [round(b - a, 1) for a, b in zip(starts, starts[1:])]
    check("H1 崩溃退避确实拉开（前 6 次间隔递增，不是每 3 秒硬拉）",
          len(starts) >= 6 and gaps[:5] == sorted(gaps[:5]) and max(gaps) > 30,
          "starts=%d gaps=%s" % (len(starts), gaps))
    check("H2 退避有上限、不会从此不管她", max(gaps) <= sentinel.MAX_BACKOFF + 0.1,
          "max gap=%.0f cap=%.0f" % (max(gaps), sentinel.MAX_BACKOFF))
    check("H3 200 次轮询里没有拉满 200 次", len(starts) < 20,
          "只试了 %d 次（旧版会试 ~200 次）" % len(starts))


# ------------------------------------------------- I: 多屏全屏判据
def test_monitor() -> None:
    hwnd = winutil.user32.GetForegroundWindow()
    rect = winutil.monitor_rect(hwnd) if hwnd else None
    check("I1 monitor_rect 拿到所在屏", bool(rect) and rect[2] > 0 and rect[3] > 0, str(rect))
    check("I2 全屏判据在真实窗口上不抛错",
          isinstance(winutil.window_is_borderless_fullscreen(hwnd), bool), "hwnd=%s" % hwnd)
    check("I3 判据改用所在显示器而不是主屏",
          "monitor_rect(hwnd)" in (APP / "winutil.py").read_text(encoding="utf-8"), "见 winutil")


def run_sentinel(bound: bool, qoder_up: bool, her_alive: bool, polls: int = 80,
                 with_quit_flag: bool = True):
    """在假时钟 + 假 winutil 下跑哨兵，返回（拉起次数, taskkill 次数, 扫进程次数, 标记还在吗）"""
    import sentinel

    tmp = Path(tempfile.mkdtemp()) / "run"
    tmp.mkdir(parents=True)
    pid_file, quit_flag = tmp / "pet.pid", tmp / "quit"
    if her_alive:
        pid_file.write_text("777", encoding="utf-8")
    if with_quit_flag:
        quit_flag.write_text("1", encoding="utf-8")   # 两种模式都先放着，看谁清它
    ft = _FakeTime(limit=polls)
    starts: list[float] = []
    kills: list[tuple] = []
    scans = {"n": 0}

    class FakeWinutil:
        QODER_EXE = "qoder.exe"

        @staticmethod
        def process_ids(_name):
            scans["n"] += 1
            return {4242} if qoder_up else set()

        @staticmethod
        def qoder_main_window():
            return 1 if qoder_up else 0

        @staticmethod
        def window_pid(_hwnd):
            return 555

        @staticmethod
        def process_alive(pid):
            return her_alive and pid == 777

    class FakeSubprocess:
        @staticmethod
        def run(cmd, **_kw):
            if cmd and cmd[0] == "taskkill":
                kills.append(tuple(cmd))
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    real = (sentinel.time, sentinel.winutil, sentinel.subprocess, sentinel.RUN,
            sentinel.PET_PID, sentinel.QUIT_FLAG, sentinel.start_pet,
            sentinel.hold_singleton, sentinel.bind_qoder)
    sentinel.time, sentinel.winutil, sentinel.subprocess = ft, FakeWinutil, FakeSubprocess
    sentinel.RUN, sentinel.PET_PID, sentinel.QUIT_FLAG = tmp, pid_file, quit_flag
    sentinel.hold_singleton = lambda: 0
    sentinel.bind_qoder = lambda: bound
    sentinel.start_pet = lambda: starts.append(ft.now)
    try:
        try:
            sentinel.main()
        except KeyboardInterrupt:
            pass
    finally:
        (sentinel.time, sentinel.winutil, sentinel.subprocess, sentinel.RUN,
         sentinel.PET_PID, sentinel.QUIT_FLAG, sentinel.start_pet,
         sentinel.hold_singleton, sentinel.bind_qoder) = real
    return starts, kills, scans["n"], quit_flag.exists()


def test_standalone() -> None:
    starts, kills, scans, flag = run_sentinel(bound=False, qoder_up=False, her_alive=False)
    check("J1 独立模式：Qoder 完全不存在也把她拉起来", len(starts) >= 1, "拉起 %d 次" % len(starts))
    check("J2 独立模式：一次都不扫进程表/窗口", scans == 0, "扫了 %d 次" % scans)
    check("J3 独立模式：run/quit 在哨兵启动时作废", not flag, "标记还在=%s" % flag)

    starts, kills, scans, _flag = run_sentinel(bound=False, qoder_up=False, her_alive=True)
    check("J4 独立模式：Qoder 不在也不杀她、不重拉", not kills and not starts,
          "starts=%d kills=%d" % (len(starts), len(kills)))

    starts, kills, _scans, _flag = run_sentinel(bound=True, qoder_up=False, her_alive=True)
    check("J5 绑定模式：Qoder 关过宽限期仍按老语义收掉她", len(kills) >= 1 and not starts,
          "starts=%d kills=%d" % (len(starts), len(kills)))

    starts, kills, scans, _flag = run_sentinel(bound=True, qoder_up=True, her_alive=False,
                                               with_quit_flag=False)
    check("J6 绑定模式：Qoder 在才拉，且会扫窗", len(starts) >= 1 and scans > 0,
          "starts=%d scans=%d" % (len(starts), scans))
    starts, _k, _s, flag = run_sentinel(bound=True, qoder_up=True, her_alive=False)
    check("J6b 绑定模式：run/quit 期间确实不重拉（标记不清）", not starts and flag,
          "starts=%d 标记还在=%s" % (len(starts), flag))

    cfg = json.loads((APP / "config.json").read_text(encoding="utf-8"))
    check("J7 出厂默认=独立（三个 Qoder 开关全 false）",
          cfg.get("requires_qoder") is False and cfg.get("follow_qoder") is False
          and cfg.get("bind_qoder") is False,
          str({k: cfg[k] for k in ("requires_qoder", "follow_qoder", "bind_qoder")}))
    local = json.loads((APP / "config.local.json").read_text(encoding="utf-8"))
    check("J8 本机 local=绑定（requires_qoder + bind_qoder 为 true）",
          local.get("requires_qoder") is True and local.get("bind_qoder") is True, str(local))
    check("J9 本机 local 不跟窗（follow_qoder 保持你原来的 false）",
          local.get("follow_qoder") is False, str(local.get("follow_qoder")))

    import tkinter as tk

    def labels(bind: bool) -> list[str]:
        root = tk.Tk()
        root.withdraw()
        obj = pet.Pet.__new__(pet.Pet)
        obj.root, obj.cfg = root, {"bind_qoder": bind}
        menu = pet.Pet.build_menu(obj)
        out = ["|" if menu.type(i) == "separator" else menu.entrycget(i, "label")
               for i in range(menu.index("end") + 1)]
        root.destroy()
        return out

    bound, open_ = labels(True), labels(False)
    check("J10 退出文案随模式变", "本次 Qoder 期间" in bound[-1] and "本次开机期间" in open_[-1],
          "%r / %r" % (bound[-1], open_[-1]))
    check("J11 菜单项个数没变（refresh_menu 的 4/5/6 索引仍然对）",
          len(bound) == len(open_) and open_[4:7] == bound[4:7], str(open_[4:7]))


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    for fn in (test_signals, test_context_line, test_landmarks, test_zone, test_menu,
               test_throw, test_tts, test_sentinel, test_monitor, test_standalone):
        try:
            fn()
        except Exception as e:                       # 探针本身坏了也要报出来
            check("%s 探针崩溃" % fn.__name__, False, "%s: %s" % (type(e).__name__, e))
    bad = [name for name, ok, _ in results if not ok]
    print("\n%d 项判据，%d 项不过" % (len(results), len(bad)))
    for name in bad:
        print("  不过：", name)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
