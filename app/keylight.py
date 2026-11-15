#!/usr/bin/env python3
"""Keylight: per-key RGB control for a Keychron K8 Pro running the ledhost firmware.

Renders a base layer (solid / painted keys / gradient / rainbow / image / video) plus click effects,
streams it to the keyboard over USB raw HID, and serves a control UI at http://localhost:8787.
"""
import argparse
import asyncio
import copy
import json
import os
import queue
import random
import shutil
import socket
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import numpy as np
from aiohttp import WSMsgType, web
from PIL import Image, ImageOps

import layout

try:
    import hid
except ImportError:  # preview-only mode
    hid = None

# Bundled resources (static UI) live next to this file, or in the PyInstaller bundle.
ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
# User data (settings, uploaded media) lives in Application Support so the .app stays read-only.
DATA = Path(os.environ.get("KEYLIGHT_DATA", Path.home() / "Library" / "Application Support" / "Keylight"))
MEDIA = DATA / "media"
CONFIG_PATH = DATA / "config.json"


def find_ffmpeg():
    """GUI apps don't get the shell PATH, so also look where Homebrew/MacPorts install ffmpeg."""
    found = shutil.which("ffmpeg")
    if found:
        return found
    for cand in ("/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg", "/opt/local/bin/ffmpeg"):
        if os.access(cand, os.X_OK):
            return cand
    return None
VID, PID = 0x3434, 0x0280
RAW_USAGE_PAGE, RAW_USAGE = 0xFF60, 0x61
CMD, EVT = 0xD0, 0xD1
N = layout.LED_COUNT
CENTERS = np.array(layout.CENTERS, dtype=np.float32)
GRID_W, GRID_H = 146, 50  # sampling resolution, same aspect as the keyboard
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff"}
VIDEO_EXT = {".gif", ".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi"}
FIRMWARE_FX = {"none": 0, "flash": 1, "trail": 1, "heatmap": 1, "glow": 2, "sparkle": 2, "ripple": 3, "cross": 4}


def _default_perkey():
    out = []
    for x, _ in layout.CENTERS:
        f = x / layout.WIDTH
        out.append("#%02x%02x%02x" % (int(40 + 200 * f), int(60 + 40 * (1 - f)), 255))
    return out


DEFAULT_CONFIG = {
    "base": {
        "mode": "gradient",
        "solid": "#ff6a00",
        "perkey": _default_perkey(),
        "gradient": {"colors": ["#00e5ff", "#7a00ff", "#ff2bd6"], "angle": 0, "speed": 0.08},
        "rainbow": {"speed": 0.15, "scale": 1.0, "angle": 0, "saturation": 1.0},
        "breathe": {"color": "#00ffa2", "speed": 0.3},
        "image": {"file": None, "name": None, "fit": "cover", "scroll": 0.0},
        "video": {"file": None, "name": None, "fit": "cover"},
    },
    "click": {"effect": "ripple", "color": "#ffffff", "rainbow": False, "duration": 0.6, "size": 1.0},
    "brightness": 1.0,
    "gamma": 2.0,
    "fps": 60,
    "live": True,
}


def deep_merge(dst, src):
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            deep_merge(dst[k], v)
        else:
            dst[k] = v
    return dst


def hex_rgb(h):
    h = (h or "#000000").lstrip("#")
    if len(h) != 6:
        return np.zeros(3, np.float32)
    return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)], np.float32) / 255.0


def hsv_rgb(h, s, v):
    """Vectorised HSV -> RGB. h, s, v are arrays (or scalars) in 0..1; returns (..., 3)."""
    h, s, v = np.broadcast_arrays(np.asarray(h, np.float32) % 1.0, np.asarray(s, np.float32), np.asarray(v, np.float32))
    i = np.floor(h * 6).astype(int) % 6
    f = h * 6 - np.floor(h * 6)
    p, q, t = v * (1 - s), v * (1 - f * s), v * (1 - (1 - f) * s)
    r = np.choose(i, [v, q, p, p, t, v])
    g = np.choose(i, [t, v, v, q, p, p])
    b = np.choose(i, [p, p, t, v, v, q])
    return np.stack([r, g, b], -1)


def _key_slices(w, h):
    """Pixel slices covering each key, for a frame of w x h that spans the whole keyboard."""
    out = []
    for k in layout.KEYS:
        x0 = int(k["x"] / layout.WIDTH * w)
        x1 = max(x0 + 1, int(round((k["x"] + k["w"]) / layout.WIDTH * w)))
        y0 = int(k["y"] / layout.HEIGHT * h)
        y1 = max(y0 + 1, int(round((k["y"] + k["h"]) / layout.HEIGHT * h)))
        out.append((slice(y0, y1), slice(x0, x1)))
    return out


KEY_SLICES = _key_slices(GRID_W, GRID_H)


def sample_frame(frame):
    """frame: (GRID_H, GRID_W, 3) uint8 -> (N, 3) float 0..1, averaging the pixels under each key."""
    f = frame.astype(np.float32) / 255.0
    return np.array([f[ys, xs].reshape(-1, 3).mean(0) for ys, xs in KEY_SLICES], np.float32)


# ----------------------------------------------------------------------------------------------
# Media sources


def fit_image(img, fit, w, h):
    img = img.convert("RGB")
    if fit == "stretch":
        return img.resize((w, h), Image.LANCZOS)
    if fit == "contain":
        return ImageOps.pad(img, (w, h), Image.LANCZOS, color=(0, 0, 0))
    return ImageOps.fit(img, (w, h), Image.LANCZOS)


class ImageSource:
    def __init__(self, path, fit, scroll):
        img = Image.open(path)
        self.scroll = scroll
        if scroll:
            # keep aspect at keyboard height and scroll horizontally, wrapping around
            img = img.convert("RGB")
            nw = max(GRID_W, int(img.width * GRID_H / img.height))
            self.pixels = np.asarray(img.resize((nw, GRID_H), Image.LANCZOS))
        else:
            self.pixels = np.asarray(fit_image(img, fit, GRID_W, GRID_H))
        self.static = None if scroll else sample_frame(self.pixels)

    def sample(self, t):
        if self.static is not None:
            return self.static
        w = self.pixels.shape[1]
        off = int(t * self.scroll * GRID_W) % w
        cols = (np.arange(GRID_W) + off) % w
        return sample_frame(self.pixels[:, cols])


class VideoSource:
    """Decodes a video/GIF with ffmpeg in real time (looping) and keeps the latest frame."""

    def __init__(self, path, fit):
        self.path, self.fit = path, fit
        self.latest = None
        self.error = None
        self.proc = None
        self.stopped = False
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        W, H = GRID_W, GRID_H
        scale = {
            "stretch": f"scale={W}:{H}",
            "contain": f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2",
        }.get(self.fit, f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}")
        ffmpeg = find_ffmpeg()
        if ffmpeg is None:
            self.error = "ffmpeg is needed for video/GIF. Install it with: brew install ffmpeg"
            return
        cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-re", "-stream_loop", "-1", "-i", str(self.path),
               "-vf", f"fps=30,{scale}", "-an", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
        size = W * H * 3
        while not self.stopped:
            try:
                self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            except FileNotFoundError:
                self.error = "ffmpeg not found (brew install ffmpeg)"
                return
            got = False
            while not self.stopped:
                buf = self.proc.stdout.read(size)
                if len(buf) < size:
                    break
                got = True
                self.latest = sample_frame(np.frombuffer(buf, np.uint8).reshape(H, W, 3))
            if self.stopped:
                break
            err = self.proc.stderr.read().decode(errors="replace").strip()
            self.proc.wait()
            if not got:
                self.error = err or "could not decode video"
                return
            # some containers stop despite -stream_loop: restart from the top

    def sample(self, t):
        return self.latest if self.latest is not None else np.zeros((N, 3), np.float32)

    def stop(self):
        self.stopped = True
        if self.proc and self.proc.poll() is None:
            self.proc.kill()


# ----------------------------------------------------------------------------------------------
# USB link


class HidLink:
    def __init__(self, on_key):
        self.dev = None
        self.wlock = threading.Lock()
        self.replies = queue.Queue()
        self.on_key = on_key
        self.info = None
        self.error = "Not connected"
        threading.Thread(target=self._reader, daemon=True).start()

    @property
    def connected(self):
        return self.dev is not None

    def connect(self):
        if hid is None:
            self.error = "Python hidapi module missing"
            return False
        paths = [d["path"] for d in hid.enumerate(VID, PID)
                 if d["usage_page"] == RAW_USAGE_PAGE and d["usage"] == RAW_USAGE]
        if not paths:
            present = any(True for _ in hid.enumerate(VID, PID))
            self.error = ("Keyboard found, but not over USB. Plug in the cable (live mode needs USB)."
                          if present else "K8 Pro not found. Plug it in with the USB cable.")
            return False
        dev = hid.device()
        try:
            dev.open_path(paths[0])
        except OSError as e:
            self.error = f"Could not open keyboard: {e}"
            return False
        self.dev = dev
        r = self.request([0x00])
        if r is None:
            self.close()
            self.error = "Keyboard didn't answer. It's probably still on stock firmware: flash the ledhost firmware."
            return False
        self.info = {"version": r[2], "leds": r[3], "brightness": r[7]}
        self.error = None
        return True

    def close(self):
        dev, self.dev = self.dev, None
        if dev:
            try:
                dev.close()
            except Exception:
                pass

    def write(self, payload):
        dev = self.dev
        if dev is None:
            raise IOError("not connected")
        pkt = bytes([0x00]) + bytes(payload) + bytes(32 - len(payload))
        with self.wlock:
            if dev.write(pkt) < 0:
                self.close()
                self.error = "Keyboard disconnected"
                raise IOError("write failed")

    def request(self, payload, timeout=0.6):
        while not self.replies.empty():
            self.replies.get_nowait()
        try:
            self.write([CMD] + payload)
        except IOError:
            return None
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            try:
                r = self.replies.get(timeout=max(0.01, end - time.monotonic()))
            except queue.Empty:
                break
            if r[1] == payload[0]:
                return r
        return None

    def _reader(self):
        while True:
            dev = self.dev
            if dev is None:
                time.sleep(0.2)
                continue
            try:
                data = dev.read(32, 200)
            except (OSError, ValueError):
                self.close()
                self.error = "Keyboard disconnected"
                continue
            if not data:
                continue
            if data[0] == EVT:
                self.on_key(data[4], bool(data[3]))
            elif data[0] == CMD:
                self.replies.put(data)

    def send_leds(self, sub, rgb, present=True):
        for start in range(0, N, 9):
            chunk = rgb[start:start + 9]
            n = len(chunk)
            last = present and start + n >= N
            self.write([CMD, sub, start, n | (0x80 if last else 0)] + chunk.reshape(-1).tolist())

    def exit_direct(self):
        try:
            self.write([CMD, 0x02])
        except IOError:
            pass


# ----------------------------------------------------------------------------------------------
# Engine


class Engine:
    def __init__(self):
        self.cfg = copy.deepcopy(DEFAULT_CONFIG)
        if CONFIG_PATH.exists():
            try:
                deep_merge(self.cfg, json.loads(CONFIG_PATH.read_text()))
            except Exception as e:
                print("Ignoring bad config.json:", e)
        self.hits = []
        self.heat = np.zeros(N, np.float32)
        self.source = None
        self.source_key = None
        self.loop = None
        self.clients = set()
        self.link = HidLink(self._on_key_thread)
        self.preview = np.zeros((N, 3), np.float32)
        self.sending = False
        self.paused = False
        self.stats = {"fps": 0.0, "keys": 0}

    # --- config -------------------------------------------------------------------------------
    def update_config(self, patch):
        was_live = self.cfg["live"]
        deep_merge(self.cfg, patch)
        CONFIG_PATH.write_text(json.dumps(self.cfg, indent=1))
        if was_live and not self.cfg["live"] and self.link.connected:
            self.link.exit_direct()

    def _ensure_source(self):
        b = self.cfg["base"]
        mode = b["mode"]
        if mode == "image" and b["image"]["file"]:
            key = ("image", b["image"]["file"], b["image"]["fit"], bool(b["image"]["scroll"]), b["image"]["scroll"])
        elif mode == "video" and b["video"]["file"]:
            key = ("video", b["video"]["file"], b["video"]["fit"])
        else:
            key = None
        if key == self.source_key:
            return
        if isinstance(self.source, VideoSource):
            self.source.stop()
        self.source, self.source_key = None, key
        if key is None:
            return
        path = MEDIA / key[1]
        try:
            if key[0] == "image":
                self.source = ImageSource(path, key[2], b["image"]["scroll"])
            else:
                self.source = VideoSource(path, key[2])
        except Exception as e:
            print("Media error:", e)
            self.source = None

    # --- input --------------------------------------------------------------------------------
    def _on_key_thread(self, led, pressed):
        if pressed and led < N and self.loop:
            self.loop.call_soon_threadsafe(self.press, led)

    def press(self, i):
        t = time.monotonic()
        c = self.cfg["click"]
        self.stats["keys"] += 1
        hue = (t * 0.15 + random.random() * 0.1) % 1.0
        if c["effect"] == "sparkle":
            near = np.argsort(np.hypot(*(CENTERS - CENTERS[i]).T))[: int(4 + 10 * c["size"])]
            picks = [i] + random.sample(list(near[1:]), min(len(near) - 1, int(3 + 4 * c["size"])))
            for j in picks:
                self.hits.append({"i": int(j), "t": t + (0 if j == i else random.uniform(0, 0.3)), "hue": random.random()})
        elif c["effect"] == "heatmap":
            d = np.hypot(*(CENTERS - CENTERS[i]).T)
            self.heat += 0.35 * np.exp(-(d / (0.6 * c["size"] + 0.3)) ** 2)
        else:
            self.hits.append({"i": i, "t": t, "hue": hue})

    # --- rendering ----------------------------------------------------------------------------
    def render_base(self, t):
        b = self.cfg["base"]
        mode = b["mode"]
        self._ensure_source()
        if mode == "solid":
            return np.tile(hex_rgb(b["solid"]), (N, 1))
        if mode == "perkey":
            pk = b["perkey"]
            return np.array([hex_rgb(pk[i] if i < len(pk) else "#000000") for i in range(N)], np.float32)
        if mode == "breathe":
            v = 0.15 + 0.85 * (0.5 - 0.5 * np.cos(2 * np.pi * t * b["breathe"]["speed"]))
            return np.tile(hex_rgb(b["breathe"]["color"]) * v, (N, 1))
        if mode in ("gradient", "rainbow"):
            g = b[mode]
            a = np.radians(g["angle"])
            proj = CENTERS[:, 0] * np.cos(a) + CENTERS[:, 1] * np.sin(a)
            p = (proj - proj.min()) / max(1e-6, np.ptp(proj))
            if mode == "rainbow":
                return hsv_rgb(p * g["scale"] - t * g["speed"], g["saturation"], 1.0)
            cols = np.array([hex_rgb(c) for c in g["colors"]] or [np.zeros(3)], np.float32)
            if len(cols) == 1:
                return np.tile(cols[0], (N, 1))
            q = p - t * g["speed"] if g["speed"] else p
            q = 1 - np.abs((q % 2) - 1) if g["speed"] else q  # ping-pong so motion stays seamless
            pos = q * (len(cols) - 1)
            lo = np.clip(np.floor(pos).astype(int), 0, len(cols) - 2)
            f = (pos - lo)[:, None]
            return cols[lo] * (1 - f) + cols[lo + 1] * f
        if mode in ("image", "video") and self.source is not None:
            return self.source.sample(t)
        return np.zeros((N, 3), np.float32)

    def render_overlay(self, t, dt):
        c = self.cfg["click"]
        eff, dur, size = c["effect"], max(0.05, c["duration"]), c["size"]
        acc_a = np.zeros(N, np.float32)
        acc_c = np.zeros((N, 3), np.float32)
        fixed = hex_rgb(c["color"])

        if eff == "heatmap":
            self.heat *= np.exp(-dt / (dur * 3))
            h = np.clip(self.heat, 0, 1)
            return np.clip(h * 1.5, 0, 1), hsv_rgb(0.66 * (1 - h), 1.0, 1.0)  # blue (cool) -> red (hot)

        life = dur * (4 if eff == "trail" else 1)
        keep = []
        for hit in self.hits:
            age = t - hit["t"]
            if age > life:
                continue
            keep.append(hit)
            if age < 0:
                continue
            k = age / life
            d = np.hypot(*(CENTERS - CENTERS[hit["i"]]).T)
            a = np.zeros(N, np.float32)
            if eff in ("flash", "trail", "sparkle"):
                a[hit["i"]] = (1 - k) ** (1.6 if eff == "trail" else 2)
                if eff == "flash":  # small halo
                    a = np.maximum(a, (1 - k) ** 2 * np.clip(1 - d / (0.9 * size + 0.2), 0, 1) * 0.5)
            elif eff == "ripple":
                r = k * (3 + 6 * size)
                a = np.exp(-((d - r) / 0.75) ** 2) * (1 - k) ** 1.2
            elif eff == "glow":
                a = np.clip(1 - d / (1 + 2.5 * size), 0, 1) * (1 - k) ** 1.5
            elif eff == "cross":
                dx, dy = (CENTERS - CENTERS[hit["i"]]).T
                line = (np.abs(dy) < 0.5) | (np.abs(dx) < 0.75)
                r = k * (4 + 10 * size)
                a = line * np.clip(1 - np.abs(d - r) / 1.5, 0, 1) * (1 - k)
                a[hit["i"]] = max(a[hit["i"]], (1 - k) ** 2)
            if c["rainbow"]:
                col = hsv_rgb(hit["hue"] + d * 0.05, 1.0, 1.0)
            else:
                col = np.broadcast_to(fixed, (N, 3))
            acc_a += a
            acc_c += col * a[:, None]
        self.hits = keep
        col = np.where(acc_a[:, None] > 1e-4, acc_c / np.maximum(acc_a, 1e-4)[:, None], 0)
        return np.clip(acc_a, 0, 1), col

    def to_hw(self, rgb):
        out = np.clip(rgb * self.cfg["brightness"], 0, 1) ** max(0.5, self.cfg["gamma"])
        return np.round(out * 255).astype(np.uint8)

    async def run(self):
        self.loop = asyncio.get_running_loop()
        last_t = time.monotonic()
        last_sent = None
        last_send_t = 0.0
        last_ws = 0.0
        frames, fps_t = 0, last_t
        while True:
            t = time.monotonic()
            dt, last_t = t - last_t, t
            try:
                base = self.render_base(t)
                a, col = self.render_overlay(t, dt)
                frame = base * (1 - a[:, None]) + col * a[:, None]
            except Exception as e:  # never let a bad setting kill the loop
                print("render error:", e)
                frame = np.zeros((N, 3), np.float32)
            self.preview = np.clip(frame * self.cfg["brightness"], 0, 1)
            hw = self.to_hw(frame)

            if self.cfg["live"] and self.link.connected and not self.paused and not self.sending:
                if last_sent is None or not np.array_equal(hw, last_sent) or t - last_send_t > 1.0:
                    self.sending = True
                    try:
                        await self.loop.run_in_executor(None, self.link.send_leds, 0x01, hw)
                        last_sent, last_send_t = hw, t
                    except IOError:
                        last_sent = None
                    finally:
                        self.sending = False

            if t - last_ws > 1 / 30 and self.clients:
                last_ws = t
                await self.broadcast({"t": "frame", "c": (np.round(self.preview * 255).astype(np.uint8)).tobytes().hex()})

            frames += 1
            if t - fps_t >= 1:
                self.stats["fps"] = round(frames / (t - fps_t), 1)
                frames, fps_t = 0, t
                await self.broadcast(self.status())
            await asyncio.sleep(max(0.001, 1 / self.cfg["fps"] - (time.monotonic() - t)))

    async def connect_loop(self):
        while True:
            if not self.link.connected:
                await asyncio.get_running_loop().run_in_executor(None, self.link.connect)
            await asyncio.sleep(2)

    def status(self):
        err = self.link.error
        if self.source is not None and getattr(self.source, "error", None):
            err = f"Video: {self.source.error}"
        return {"t": "status", "connected": self.link.connected, "error": err, "info": self.link.info,
                "fps": self.stats["fps"], "live": self.cfg["live"]}

    async def broadcast(self, msg):
        data = json.dumps(msg)
        for ws in list(self.clients):
            try:
                await ws.send_str(data)
            except Exception:
                self.clients.discard(ws)

    # --- save to keyboard ---------------------------------------------------------------------
    def save_to_keyboard(self):
        if not self.link.connected:
            raise IOError(self.link.error or "Keyboard not connected")
        self.paused = True
        try:
            while self.sending:
                time.sleep(0.005)
            base = self.to_hw(self.render_base(time.monotonic()))
            c = self.cfg["click"]
            fx = FIRMWARE_FX.get(c["effect"], 0) | (0x80 if c["rainbow"] else 0)
            r, g, b = (hex_rgb(c["color"]) * 255).astype(int).tolist()
            speed = int(np.clip(65280 / (max(0.05, c["duration"]) * 1000) - 1, 0, 255))
            self.link.send_leds(0x03, base, present=False)
            self.link.write([CMD, 0x05, fx, r, g, b, speed])
            if self.link.request([0x04], timeout=2.0) is None:
                raise IOError("Keyboard did not confirm the save")
            self.link.write([CMD, 0x06])
        finally:
            self.paused = False
        self.update_config({"live": False})


# ----------------------------------------------------------------------------------------------
# Web server


def make_app(engine):
    app = web.Application(client_max_size=512 * 1024 * 1024)

    async def index(_):
        return web.FileResponse(ROOT / "static" / "index.html")

    async def state(_):
        return web.json_response({"config": engine.cfg, "keys": layout.KEYS, "width": layout.WIDTH,
                                  "height": layout.HEIGHT, "status": engine.status()})

    async def set_config(req):
        engine.update_config(await req.json())
        return web.json_response({"ok": True})

    async def upload(req):
        reader = await req.multipart()
        field = await reader.next()
        if field is None or not field.filename:
            raise web.HTTPBadRequest(text="no file")
        ext = Path(field.filename).suffix.lower()
        if ext not in IMAGE_EXT | VIDEO_EXT:
            raise web.HTTPBadRequest(text=f"Unsupported file type {ext}")
        MEDIA.mkdir(exist_ok=True)
        name = uuid.uuid4().hex + ext
        with open(MEDIA / name, "wb") as f:
            while chunk := await field.read_chunk(1 << 20):
                f.write(chunk)
        kind = "image" if ext in IMAGE_EXT else "video"
        engine.update_config({"base": {"mode": kind, kind: {"file": name, "name": field.filename}}})
        return web.json_response({"ok": True, "kind": kind, "file": name})

    async def save(_):
        try:
            await asyncio.get_running_loop().run_in_executor(None, engine.save_to_keyboard)
        except IOError as e:
            return web.json_response({"ok": False, "error": str(e)}, status=409)
        return web.json_response({"ok": True})

    async def to_perkey(_):
        base = np.clip(engine.render_base(time.monotonic()), 0, 1)
        pk = ["#%02x%02x%02x" % tuple(int(round(v * 255)) for v in rgb) for rgb in base]
        engine.update_config({"base": {"mode": "perkey", "perkey": pk}})
        return web.json_response({"ok": True, "perkey": pk})

    async def ws_handler(req):
        ws = web.WebSocketResponse(heartbeat=20)
        await ws.prepare(req)
        engine.clients.add(ws)
        await ws.send_str(json.dumps(engine.status()))
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                m = json.loads(msg.data)
                if m.get("t") == "press" and 0 <= int(m.get("i", -1)) < N:
                    engine.press(int(m["i"]))
        engine.clients.discard(ws)
        return ws

    app.router.add_get("/", index)
    app.router.add_get("/api/state", state)
    app.router.add_post("/api/config", set_config)
    app.router.add_post("/api/upload", upload)
    app.router.add_post("/api/save", save)
    app.router.add_post("/api/to_perkey", to_perkey)
    app.router.add_get("/ws", ws_handler)
    app.router.add_static("/media", MEDIA)
    app.router.add_static("/static", ROOT / "static")
    return app


def pick_port(preferred):
    """Use the preferred port if it's free, otherwise any free port."""
    for port in (preferred, 0):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return s.getsockname()[1]
            except OSError:
                continue
    raise OSError("no free port")


async def serve(port, on_ready=None):
    MEDIA.mkdir(parents=True, exist_ok=True)
    engine = Engine()
    runner = web.AppRunner(make_app(engine))
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", port).start()
    print(f"Keylight running: http://localhost:{port}", flush=True)
    if on_ready:
        on_ready(port)
    try:
        await asyncio.gather(engine.run(), engine.connect_loop())
    finally:
        if engine.link.connected:
            engine.link.exit_direct()  # hand the LEDs back to the keyboard right away


def main():
    ap = argparse.ArgumentParser(description="Keylight: per-key RGB for the Keychron K8 Pro")
    ap.add_argument("--port", type=int, default=8787)
    args = ap.parse_args()
    try:
        asyncio.run(serve(pick_port(args.port)))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
