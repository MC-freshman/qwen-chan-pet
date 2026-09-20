"""qwen娘 — a raisable, self-reporting desktop pet that costs zero tokens.

Everything she "knows" comes from local Win32 reads and arithmetic; every word
she says is picked from lines/zh.json. She exists only while Qoder is running.
"""

from __future__ import annotations

import json
import math
import random
import sys
import time
import tkinter as tk
from datetime import date, datetime
from pathlib import Path

import rigor
import winutil
from needs import Life, write_diary
from speech import Speech

from PIL import Image, ImageDraw, ImageFont, ImageTk

APP = Path(__file__).resolve().parent
SHEET = APP / "assets" / "spritesheet.webp"
FRAMES_DIR = APP / "frames"
CELL_W, CELL_H = 192, 208
ROW_STATES = [
    "idle",
    "running-right",
    "running-left",
    "waving",
    "jumping",
    "failed",
    "waiting",
    "running",
    "review",
]
FRAME_COUNTS = {
    "idle": 6,
    "running-right": 8,
    "running-left": 8,
    "waving": 4,
    "jumping": 5,
    "failed": 8,
    "waiting": 6,
    "running": 6,
    "review": 6,
}
MAGIC = "#ff00fe"
BUBBLE_FONT = "C:/Windows/Fonts/msyh.ttc"
FAST_TICK = 0.05
SLOW_TICK = 1.0


def emblem(draw: ImageDraw.ImageDraw, cx: float, cy: float, radius: float, spin: float) -> None:
    """The Qwen six-petal mark: navy disc, white petals, gold core."""
    draw.ellipse(
        [cx - radius, cy - radius, cx + radius, cy + radius], fill=(43, 55, 110, 255)
    )
    petal = radius * 0.78
    for index in range(6):
        angle = math.radians(60 * index - 90 + spin)
        ex = cx + math.cos(angle) * petal * 0.52
        ey = cy + math.sin(angle) * petal * 0.52
        rr = petal * 0.46
        draw.ellipse([ex - rr, ey - rr, ex + rr, ey + rr], fill=(250, 251, 255, 255))
    core = radius * 0.2
    draw.ellipse([cx - core, cy - core, cx + core, cy + core], fill=(216, 178, 108, 255))


def render_bubble(text: str, scale: float, swing: float = 0.0) -> tuple[Image.Image, int]:
    """Rounded speech bubble with a tail and a charm on its hem, on the key colour."""
    font = ImageFont.truetype(BUBBLE_FONT, max(11, round(15 * scale)))
    pad = round(11 * scale)
    max_text = round(230 * scale)
    top_offset, bottom_offset = font.getbbox("Ag")[1], font.getbbox("Ag")[3]
    line_h = bottom_offset - top_offset + round(4 * scale)

    lines, current = [], ""
    for char in text:
        if font.getlength(current + char) > max_text:
            lines.append(current)
            current = char
        else:
            current += char
    if current:
        lines.append(current)

    box_w = max(round(font.getlength(line)) for line in lines) + pad * 2
    tail = round(9 * scale)
    box_h = len(lines) * line_h + pad * 2
    chain, charm_r = round(20 * scale), round(9 * scale)
    anchor_x = round(26 * scale)
    charm_x = anchor_x + math.sin(math.radians(swing)) * chain
    charm_y = box_h + math.cos(math.radians(swing)) * chain
    image = Image.new("RGB", (box_w, int(max(box_h + tail, charm_y + charm_r + 2))), (255, 0, 254))
    draw = ImageDraw.Draw(image)
    draw.line(
        [anchor_x, box_h - 1, charm_x, charm_y], fill=(150, 160, 205, 255), width=max(1, round(2 * scale))
    )
    emblem(draw, charm_x, charm_y, charm_r, swing * 0.6)
    draw.rounded_rectangle(
        [0, 0, box_w - 1, box_h - 1],
        radius=round(9 * scale),
        fill=(252, 252, 255),
        outline=(122, 132, 182),
        width=max(1, round(2 * scale)),
    )
    tip_x = box_w - round(38 * scale)
    tail_x = tip_x - tail
    draw.polygon(
        [(tail_x, box_h - 2), (tail_x + tail * 2, box_h - 2), (tip_x, box_h + tail)],
        fill=(252, 252, 255),
        outline=(122, 132, 182),
    )
    draw.rectangle(
        [tail_x + 2, box_h - 4, tail_x + tail * 2 - 2, box_h - 1], fill=(252, 252, 255)
    )
    y = pad - top_offset
    for line in lines:
        draw.text((pad, y), line, font=font, fill=(46, 56, 108))
        y += line_h
    return image, tip_x, box_h + tail


def head_anchor(cell: Image.Image) -> tuple[float, float]:
    """Where her head sits inside a cell, so the bubble tail points at her and not at empty space."""
    import numpy as np

    mask = np.array(cell.getchannel("A"), dtype=np.uint8).copy()
    mask[: round(cell.height * 0.21), : round(cell.width * 0.27)] = 0  # the charm, not her
    ys, xs = np.nonzero(mask)
    if len(ys) == 0:
        return cell.width / 2, cell.height * 0.2
    top, bottom = int(ys.min()), int(ys.max())
    band = ys < top + max(10, int((bottom - top) * 0.2))
    return float(xs[band].mean()), float(top + (bottom - top) * 0.06)


class Pet:
    def __init__(self, config: dict) -> None:
        self.cfg = config
        self.life = Life(APP / "save.json")
        self.rng = random.Random()
        self.speech = Speech(APP / "lines" / "zh.json", self.life, self.rng)
        self.lock = self.acquire_lock()

        self.root = tk.Tk(className="qwenchan")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg=MAGIC)
        self.root.wait_visibility(self.root)
        self.root.attributes("-transparentcolor", MAGIC)
        self.label = tk.Label(self.root, bg=MAGIC, bd=0)
        self.label.pack()

        self.dpi = winutil.system_scale()
        self.set_scale(self.cfg["scale"])
        self.anchor = 0.0
        self.floor = 0.0
        self.x = 0.0
        self.y = 0.0
        self.state = "idle"
        self.frame_i = 0
        self.state_until = 0.0
        self.forced_state: str | None = None
        self.forced_until = 0.0
        self.pinned = False
        self.drag_anchor = None
        self.moved = 0
        self.bubble = None
        self.bubble_label = None
        self.bubble_photo = None
        self.bubble_box = (0, 0, 0, 0)
        self.silent_until = 0.0
        self.said_this_hour: list[float] = []
        self.qoder_gone_since: float | None = None
        self.placed_at = (-9999, -9999)
        self.gaze = 0
        self.last_gaze = 0.0
        self.session_start = time.time()
        self.next_slow = 0.0
        self.next_save = self.session_start + self.cfg["save_every_seconds"]
        self.next_speech = self.session_start + self.rng.uniform(12, 24)
        self.bind_events()

        offline = self.life.apply_offline()
        self.refresh_perch(force=True)
        self.x, self.y = self.anchor, self.floor
        self.greeting(offline)
        self.root.protocol("WM_DELETE_WINDOW", self.quit)
        self.root.after(int(FAST_TICK * 1000), self.loop)

    # ---------- setup ----------

    def acquire_lock(self) -> Path:
        lock = APP / "run" / "pet.pid"
        lock.parent.mkdir(exist_ok=True)
        mine = winutil.kernel32.GetCurrentProcessId()
        if lock.exists():
            try:
                other = int(lock.read_text().strip())
            except ValueError:
                other = 0
            if other and other != mine and winutil.process_alive(other):
                raise SystemExit(f"已有一只 qwen娘 在跑（pid {other}）")
        lock.write_text(str(mine))
        return lock

    def set_scale(self, scale: float) -> None:
        self.cfg["scale"] = round(max(0.45, min(1.6, scale)), 2)
        self.pixel_scale = self.cfg["scale"] * self.dpi
        self.frame_size = (
            max(1, round(CELL_W * self.pixel_scale)),
            max(1, round(CELL_H * self.pixel_scale)),
        )
        self.cells: dict[str, list[Image.Image]] = {}
        self.head: dict[str, tuple[float, float]] = {}
        self.photos: dict[tuple[str, int, int], ImageTk.PhotoImage] = {}
        self.sheet = None if FRAMES_DIR.is_dir() else Image.open(SHEET).convert("RGBA")
        rig_file = FRAMES_DIR / "rig.json"
        self.chin = json.loads(rig_file.read_text(encoding="utf-8")) if rig_file.exists() else {}

    def prepare(self, image: Image.Image) -> Image.Image:
        cell = image.resize(self.frame_size, Image.Resampling.LANCZOS)
        # The sheet's charm hangs from the cell top, which has no ceiling here;
        # it now dangles from the speech bubble instead.
        alpha = cell.getchannel("A")
        ImageDraw.Draw(alpha).rectangle(
            [0, 0, round(cell.width * 0.32), round(cell.height * 0.16)], fill=0
        )
        # A key-colour window cannot blend, so harden the silhouette edge.
        cell.putalpha(alpha.point(lambda v: 255 if v >= 128 else 0))
        return cell

    def load_state(self, state: str) -> list[Image.Image]:
        """Frames are ~5MB per state, so keep only the few most recent resident."""
        cached = self.cells.get(state)
        if cached:
            return cached
        folder = FRAMES_DIR / state
        if folder.is_dir():
            raw = [Image.open(path) for path in sorted(folder.glob("*.png"))]
        else:
            row = ROW_STATES.index(state)
            raw = [
                self.sheet.crop(
                    (
                        col * CELL_W,
                        row * CELL_H,
                        (col + 1) * CELL_W,
                        (row + 1) * CELL_H,
                    )
                )
                for col in range(FRAME_COUNTS[state])
            ]
        cells = [self.prepare(image) for image in raw]
        self.head[state] = head_anchor(cells[0])
        self.cells[state] = cells
        for other in list(self.cells):
            if len(self.cells) <= 4:
                break
            if other != state:
                del self.cells[other]
        return cells

    def render(self, state: str, index: int, gaze: int) -> ImageTk.PhotoImage:
        key = (state, index, gaze)
        photo = self.photos.get(key)
        if photo is not None:
            return photo
        cells = self.load_state(state)
        cell = cells[index % len(cells)]
        if gaze:
            hx, hy = self.head[state]
            # Ramp from the chin down: the hat sits in the rigid zone above it, so a
            # misread face line cannot streak the brim the way a 14px neck band did.
            chin = (self.chin.get(state) or {}).get("chin") or hy + cell.height * 0.24
            cell = rigor.shear_rows(
                cell, rigor.head_follow_profile(cell.height, chin, gaze * 2.2, shoulder=26.0)
            )
            cell.putalpha(cell.getchannel("A").point(lambda v: 255 if v >= 128 else 0))
        flat = Image.new("RGB", cell.size, (255, 0, 254))
        flat.paste(cell, (0, 0), cell)
        photo = ImageTk.PhotoImage(flat)
        if len(self.photos) > 150:
            self.photos.clear()
        self.photos[key] = photo
        return photo

    def bind_events(self) -> None:
        self.label.bind("<ButtonPress-1>", self.on_press)
        self.label.bind("<B1-Motion>", self.on_drag)
        self.label.bind("<ButtonRelease-1>", self.on_release)
        self.label.bind("<Double-Button-1>", self.on_feed)
        self.label.bind("<Button-3>", self.on_menu)
        self.label.bind("<MouseWheel>", self.on_wheel)

    # ---------- main loop ----------

    def loop(self) -> None:
        now = time.time()
        self.animate(now)
        if now >= self.next_slow:
            self.next_slow = now + SLOW_TICK
            hwnd = winutil.qoder_main_window()
            self.refresh_perch(hwnd)
            self.life.note_context(*self.foreground())
            if self.check_qoder(now, hwnd):
                return
        self.schedule_speech(now)
        self.persist(now)
        self.root.after(int(FAST_TICK * 1000), self.loop)

    def foreground(self) -> tuple[str, str]:
        title = winutil.foreground_title()
        return title, winutil.foreground_file(title)

    def animate(self, now: float) -> None:
        if now >= self.state_until:
            self.state = self.choose_state(now)
            self.frame_i = 0
            self.state_until = now + self.dwell(self.state)
        self.frame_i += 1
        self.move(now)
        self.update_gaze(now)
        cells = self.load_state(self.state)
        photo = self.render(self.state, self.frame_i % len(cells), self.gaze)
        self.label.configure(image=photo)
        self.image = photo
        self.place()
        if self.bubble is not None:
            self.position_bubble()

    def update_gaze(self, now: float) -> None:
        """She turns her head toward the cursor, and stops when nobody is around."""
        if now - self.last_gaze < 0.12:
            return
        self.last_gaze = now
        if winutil.idle_seconds() > 6.0:
            self.gaze = 0
            return
        hx, hy = self.head.get(self.state, (self.frame_size[0] / 2, self.frame_size[1] * 0.2))
        cursor_x, _ = winutil.cursor_pos()
        offset = cursor_x - (self.x + hx)
        self.gaze = max(-3, min(3, int(round(offset / 110))))

    def dwell(self, state: str) -> float:
        if state in ("running-right", "running-left", "running"):
            return self.rng.uniform(2.0, 4.0)
        if state in ("waving", "jumping"):
            return self.rng.uniform(1.2, 2.0)
        return self.rng.uniform(3.0, 7.0)

    def move(self, now: float) -> None:
        if self.drag_anchor is not None:
            return
        if self.state == "running-right":
            self.x += 3.2 * self.pixel_scale
        elif self.state == "running-left":
            self.x -= 3.2 * self.pixel_scale
        elif not self.pinned:
            self.x += (self.anchor - self.x) * 0.06
            self.y += (self.floor - self.y) * 0.2
        limit = self.cfg["wander_range"] * self.pixel_scale
        if self.x > self.anchor + limit:
            self.state, self.frame_i = "running-left", 0
        elif self.x < self.anchor - limit:
            self.state, self.frame_i = "running-right", 0
        self.x = max(-20, min(self.root.winfo_screenwidth() - 30, self.x))

    def choose_state(self, now: float) -> str:
        if now < self.forced_until and self.forced_state:
            return self.forced_state
        self.forced_state = None
        if self.life.sleeping:
            return "waiting"
        energy, mood = self.life.needs["energy"], self.life.needs["mood"]
        idle_user = winutil.idle_seconds() > self.cfg["idle_user_seconds"]
        if idle_user:
            return "waiting" if energy > 25 else "failed"
        if energy < 18:
            return "failed" if mood < 35 else "waiting"
        weights = {
            "idle": 34,
            "review": 16,
            "running-right": 12,
            "running-left": 12,
            "running": 8,
            "waving": 6,
            "jumping": 4,
            "waiting": 6,
            "failed": 2 if mood > 40 else 9,
        }
        states = list(weights)
        return self.rng.choices(states, [weights[s] for s in states])[0]

    def force(self, state: str, seconds: float = 1.5) -> None:
        self.forced_state = state
        self.forced_until = time.time() + seconds
        self.state, self.frame_i = state, 0
        self.state_until = self.forced_until

    # ---------- perch and watchdog ----------

    def refresh_perch(self, hwnd: int | None = None, force: bool = False) -> None:
        hwnd = hwnd or winutil.qoder_main_window()
        if not hwnd:
            return
        if force or not self.pinned:
            left, top, width, height = winutil.window_rect(hwnd)
            offset_x, offset_y = self.cfg["perch_offset"]
            self.anchor = float(left + width - self.frame_size[0] + offset_x)
            self.floor = float(top + height - self.frame_size[1] + offset_y)

    def check_qoder(self, now: float, hwnd: int | None = None) -> bool:
        """She only exists while Qoder is open — covers crash and force-kill too."""
        if hwnd or winutil.qoder_main_window():
            self.qoder_gone_since = None
            return False
        if self.qoder_gone_since is None:
            self.qoder_gone_since = now
        elif now - self.qoder_gone_since > self.cfg["watchdog_grace_seconds"]:
            self.quit()
            return True
        return False

    # ---------- speech ----------

    def schedule_speech(self, now: float) -> None:
        if now < self.next_speech or now < self.silent_until or self.cfg.get("muted"):
            return
        self.next_speech = now + self.rng.uniform(
            self.cfg["speech_min_gap_seconds"], self.cfg["speech_min_gap_seconds"] * 2.5
        )
        if datetime.now().hour in self.cfg.get("quiet_hours", []):
            return
        self.said_this_hour = [t for t in self.said_this_hour if now - t < 3600]
        if len(self.said_this_hour) >= self.cfg["speech_max_per_hour"]:
            return
        text = self.context_line(now)
        if text:
            self.said_this_hour.append(now)
            self.show_bubble(text)

    def context_line(self, now: float) -> str | None:
        needs = self.life.needs
        variables = self.line_vars()
        if (now - self.session_start) < 60 and self.offline_gap > 45:
            return self.speech.pick("greet", "back_long", **variables)
        if needs["energy"] < 22:
            return self.speech.pick("needs", "low_energy", **variables)
        if needs["mood"] < 28:
            return self.speech.pick("needs", "low_mood", **variables)
        if needs["affection"] < 20:
            return self.speech.pick("needs", "low_affection", **variables)
        if winutil.idle_seconds() > self.cfg["idle_user_seconds"]:
            return self.speech.pick("sense", "user_idle", **variables)
        if (now - self.session_start) / 60 > self.cfg["long_work_minutes"]:
            return self.speech.pick("sense", "long_work", **variables)
        if datetime.now().hour in (0, 1, 2, 3) and needs["energy"] < 55:
            return self.speech.pick("sense", "night_owl", **variables)
        roll = self.rng.random()
        if roll < 0.24:
            return self.speech.pick("state", self.state.split("-")[0])
        if roll < 0.44:
            return self.speech.pick("self", self.rng.choice(["memory", "aware", "identity"]))
        if roll < 0.62 and variables.get("file"):
            return self.speech.pick("sense", "coding", **variables)
        return self.speech.pick("greet", self.hour_bucket(), **variables)

    def hour_bucket(self) -> str:
        hour = datetime.now().hour
        if 5 <= hour < 11:
            return "morning"
        if 11 <= hour < 18:
            return "afternoon"
        if 18 <= hour < 23:
            return "evening"
        return "late_night"

    def line_vars(self) -> dict:
        files = self.life.files.most_common(1)
        return {
            "file": files[0][0] if files else "",
            "seen": files[0][1] if files else 1,
            "hour": self.life.busiest_hour() or datetime.now().hour,
            "days": self.life.days_known(),
            "minutes": round(self.life.stats.get("minutes_online", 0)),
            "app": self.life.top_app() or "Qoder",
            "energy": round(self.life.needs["energy"]),
            "mood": round(self.life.needs["mood"]),
            "affection": round(self.life.needs["affection"]),
            "gap_min": round(self.offline_gap),
            "gap_hour": round(self.offline_gap / 60, 1),
        }

    def greeting(self, offline_minutes: float) -> None:
        self.offline_gap = offline_minutes
        if self.life.stats.get("minutes_online", 0) <= 1:
            text = self.speech.pick("greet", "first_meet")
        elif offline_minutes > 45:
            text = self.speech.pick("greet", "back_long", **self.line_vars())
        else:
            text = self.speech.pick("greet", self.hour_bucket(), **self.line_vars())
        if text:
            self.show_bubble(text, seconds=8)

    def show_bubble(self, text: str, seconds: float | None = None) -> None:
        self.hide_bubble()
        image, tip_x, tip_y = render_bubble(text, self.pixel_scale, -5.0)
        photo = ImageTk.PhotoImage(image)
        top = tk.Toplevel(self.root)
        top.overrideredirect(True)
        top.attributes("-topmost", True)
        top.configure(bg=MAGIC)
        top.wait_visibility(top)
        top.attributes("-transparentcolor", MAGIC)
        self.bubble_label = tk.Label(top, image=photo, bg=MAGIC, bd=0)
        self.bubble_label.pack()
        self.bubble = top
        self.bubble_photo = photo
        self.bubble_box = (image.width, image.height, tip_x, tip_y)
        self.bubble_gen = getattr(self, "bubble_gen", 0) + 1
        generation = self.bubble_gen
        self.position_bubble()
        self.bubble_id = top.after(
            int((seconds or self.cfg["bubble_seconds"]) * 1000),
            lambda: self.hide_bubble(generation),
        )

    def position_bubble(self) -> None:
        if self.bubble is None:
            return
        width, height, tip_x, tip_y = self.bubble_box
        hx, hy = self.head.get(self.state, (self.frame_size[0] / 2, self.frame_size[1] * 0.2))
        x = int(self.x + hx - tip_x)
        y = int(self.y + hy - tip_y - 3 * self.pixel_scale)
        x = max(4, min(x, self.root.winfo_screenwidth() - width - 4))
        self.bubble.geometry(f"{width}x{height}+{x}+{max(4, y)}")

    def hide_bubble(self, generation: int | None = None) -> None:
        if generation is not None and generation != self.bubble_gen:
            return
        if self.bubble is not None:
            try:
                self.bubble.destroy()
            except tk.TclError:
                pass
            self.bubble = None
            self.bubble_label = None
            self.bubble_photo = None

    def say(self, text: str | None) -> None:
        if text and not self.cfg.get("muted"):
            self.show_bubble(text)
            self.said_this_hour.append(time.time())
            self.next_speech = time.time() + self.cfg["speech_min_gap_seconds"]

    # ---------- interaction ----------

    def on_press(self, event) -> None:
        self.drag_anchor = (event.x_root - int(self.x), event.y_root - int(self.y))
        self.moved = 0

    def on_drag(self, event) -> None:
        if self.drag_anchor is None:
            return
        self.x = event.x_root - self.drag_anchor[0]
        self.y = event.y_root - self.drag_anchor[1]
        self.moved += 1
        self.place()

    def on_release(self, event) -> None:
        dragged = self.moved > 3
        self.drag_anchor = None
        if not dragged:
            self.on_pet()
            return
        self.pinned = True
        self.anchor, self.floor = self.x, self.y
        self.life.stats["drags"] += 1
        self.life.bump("mood", 1.5)
        self.force("waving", 1.2)
        self.say(self.speech.pick("touch", "drag", **self.line_vars()))

    def on_pet(self) -> None:
        self.life.stats["pets"] += 1
        self.life.bump("affection", 4.0)
        self.life.bump("mood", 2.0)
        self.life.sleeping = False
        if self.life.needs["mood"] < 30:
            self.force("failed", 1.4)
            self.say(self.speech.pick("touch", "reject", **self.line_vars()))
            return
        self.force("waving", 1.4)
        self.say(self.speech.pick("touch", "pet", **self.line_vars()))

    def on_feed(self, event=None) -> None:
        self.life.stats["feeds"] += 1
        self.life.bump("mood", 9.0)
        self.life.bump("energy", 12.0)
        self.life.bump("curiosity", 6.0)
        self.life.sleeping = False
        self.force("jumping", 1.6)
        self.say(self.speech.pick("touch", "feed", **self.line_vars()))

    def on_wheel(self, event) -> None:
        step = 0.08 if event.delta > 0 else -0.08
        old_height = self.frame_size[1]
        self.set_scale(self.cfg["scale"] + step)
        self.y += old_height - self.frame_size[1]
        self.pinned = True
        self.anchor, self.floor = self.x, self.y
        self.place()

    def place(self) -> None:
        where = (int(self.x), int(self.y))
        if where == self.placed_at:
            return
        self.placed_at = where  # geometry() forces a repaint on a key-colour window
        width, height = self.frame_size
        self.root.geometry(f"{width}x{height}+{where[0]}+{where[1]}")

    # ---------- menu ----------

    def on_menu(self, event) -> None:
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="喂食", command=self.on_feed)
        menu.add_command(label="摸头", command=self.on_pet)
        menu.add_command(
            label="叫醒她" if self.life.sleeping else "让她小睡", command=self.toggle_sleep
        )
        menu.add_command(
            label="取消静音" if self.cfg.get("muted") else "别说话", command=self.toggle_mute
        )
        menu.add_command(
            label="回到 Qoder 窗边" if self.pinned else "钉在当前位", command=self.toggle_pin
        )
        menu.add_command(label="看看数值", command=self.show_status)
        menu.add_command(label="写日记", command=self.write_diary_now)
        menu.add_separator()
        menu.add_command(label="退出（只关她，不动 Qoder）", command=self.quit)
        menu.tk_popup(event.x_root, event.y_root)

    def toggle_sleep(self) -> None:
        self.life.sleeping = not self.life.sleeping
        self.force("waving" if not self.life.sleeping else "waiting", 1.6)

    def toggle_mute(self) -> None:
        self.cfg["muted"] = not self.cfg.get("muted", False)
        if self.cfg["muted"]:
            self.hide_bubble()

    def toggle_pin(self) -> None:
        self.pinned = not self.pinned
        if not self.pinned:
            self.refresh_perch(force=True)

    def show_status(self) -> None:
        needs = self.life.needs
        self.show_bubble(
            "心情 {:.0f}｜精力 {:.0f}｜亲密 {:.0f}｜好奇 {:.0f}｜认识 {} 天".format(
                needs["mood"],
                needs["energy"],
                needs["affection"],
                needs["curiosity"],
                self.life.days_known(),
            ),
            seconds=7,
        )

    def write_diary_now(self) -> None:
        today = date.today()
        self.life.diary_day = today.isoformat()
        write_diary(APP / "diary", self.life, today)
        self.show_bubble("今天的日记写好了，在 diary 文件夹里", seconds=6)

    # ---------- persistence ----------

    def persist(self, now: float) -> None:
        if now < self.next_save:
            return
        self.next_save = now + self.cfg["save_every_seconds"]
        self.life.save()
        today = date.today().isoformat()
        if self.life.diary_day != today and datetime.now().hour >= 4:
            self.life.diary_day = today
            write_diary(APP / "diary", self.life, date.today())

    def quit(self) -> None:
        self.life.save()
        try:
            self.cfg.pop("muted", None)
            (APP / "config.local.json").write_text(
                json.dumps({"scale": self.cfg["scale"]}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass
        try:
            self.lock.unlink(missing_ok=True)
        except OSError:
            pass
        self.root.destroy()


def main() -> None:
    winutil.set_dpi_aware()
    if not SHEET.exists():
        raise SystemExit(f"缺少精灵表：{SHEET}")
    config = json.loads((APP / "config.json").read_text(encoding="utf-8"))
    local = APP / "config.local.json"
    if local.exists():
        try:
            config.update(json.loads(local.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            pass
    config.setdefault("muted", False)
    if config.get("hi_res_timer"):
        # Tk's after() lands on the 15.6ms system tick; raising it to 1ms gets a true
        # 20fps but changes the timer resolution for the whole machine, so it is opt-in.
        import ctypes

        ctypes.windll.winmm.timeBeginPeriod(1)
    pet = Pet(config)
    pet.root.mainloop()


if __name__ == "__main__":
    main()
