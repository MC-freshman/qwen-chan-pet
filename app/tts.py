"""SAPI5 离线语音（G5/Q4 共享模块，两项目各落一份，保持自包含）。

零网络零 token：pyttsx3 直连 Windows SAPI5，合成到 wav 缓存后用 winsound 播。
缓存键 = sha1(文本 + voice + rate)。COM 是单线程单元：引擎只在 worker 线程里
创建和使用（CoInitialize 也在那儿），外部一律经队列说话，谁都不跨线程摸引擎。
"""

from __future__ import annotations

import hashlib
import queue
import threading
import time
import winsound
from pathlib import Path


class TTS:
    def __init__(self, cache_dir: Path, enabled: bool = True, voice: str = "", rate: int = 0):
        self.enabled = enabled
        self.voice = voice
        self.rate = rate
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.last_error = ""
        self.last_synth_ms = -1.0      # 最近一次合成耗时（缓存量 0）；探针判据用
        self._jobs: "queue.Queue[str]" = queue.Queue()
        self._worker = threading.Thread(target=self._loop, daemon=True)
        self._worker.start()

    # ---------- worker（引擎的唯一主人） ----------
    def _loop(self) -> None:
        engine = None
        try:
            import comtypes
            comtypes.CoInitialize()
        except Exception:
            pass
        try:
            import pyttsx3
            engine = pyttsx3.init()
            vid = ""
            for v in engine.getProperty("voices"):
                tag = (v.id + " " + v.name + " " + " ".join(
                    [str(x) for x in (getattr(v, "languages", []) or [])])).lower()
                if self.voice and self.voice in (v.id + v.name):
                    vid = v.id
                    break
                if not vid and ("zh" in tag or "huihui" in tag):
                    vid = v.id
            if self.voice and not vid:
                vid = self.voice
            if vid:
                engine.setProperty("voice", vid)
            if self.rate:
                engine.setProperty("rate", int(self.rate))
        except Exception as e:
            self.last_error = f"engine init: {e}"
            engine = None
        while True:
            text = self._jobs.get()
            if not text or engine is None:
                continue
            wav = self._cache_path(text)
            try:
                t0 = time.perf_counter()
                if not (wav.exists() and wav.stat().st_size > 0):
                    tmp = wav.with_suffix(".tmp")
                    engine.save_to_file(text, str(tmp))
                    engine.runAndWait()
                    if not tmp.exists() or tmp.stat().st_size == 0:
                        raise RuntimeError("SAPI synthesized nothing")
                    tmp.replace(wav)
                self.last_synth_ms = (time.perf_counter() - t0) * 1000
                winsound.PlaySound(str(wav), winsound.SND_FILENAME | winsound.SND_ASYNC)
            except Exception as e:      # 一句失败保持沉默，不拖垮 worker
                self.last_error = str(e)

    def _cache_path(self, text: str) -> Path:
        key = hashlib.sha1(f"{text}|{self.voice}|{self.rate}".encode("utf-8")).hexdigest()
        return self.cache_dir / (key + ".wav")

    # ---------- public ----------
    def speak(self, text: str) -> None:
        """说一句话：入队即返回；合成完自动播。新一句话会掐断上一句的播放。"""
        if self.enabled and text:
            self.purge()
            self._jobs.put(text)

    @staticmethod
    def purge() -> None:
        """掐断当前播放（新一句开始 / 气泡消失时用）。"""
        winsound.PlaySound(None, winsound.SND_PURGE)
