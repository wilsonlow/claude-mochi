#!/usr/bin/env python3
"""
Claude Pro Usage "Mochi Eyes" Display v2  (UNOFFICIAL)
Raspberry Pi 4 + SSD1306 0.96" 128x64 I2C OLED

Expressions and when they appear:
  happy      session under 50%
  normal     session 50-79%
  worried    weekly usage 80%+ (session still OK)
  stressed   session 80-94%
  panic      session 95-99%  (sweat drop)
  dizzy      session 100%    (X eyes, limit reached)
  love       session just reset (heart eyes for 30 seconds)
  sleeping   night time, closed eyes + Zzz
  sleepy     no data / login expired
  idle quirks (random, when happy or normal):
             wink, curious, squint, surprised

USAGE
  python claude_mochi_pro_v2.py            # run the display
  python claude_mochi_pro_v2.py --test     # print raw usage JSON
  python claude_mochi_pro_v2.py --preview  # cycle through every expression
  MOCHI_FORCE=love python claude_mochi_pro_v2.py   # lock one expression
  MOCHI_NIGHT=off  python claude_mochi_pro_v2.py   # disable night sleeping

WARNING: uses an UNDOCUMENTED endpoint that may change at any time.
Your ~/.claude/.credentials.json token gives access to your account.
"""

import os
import sys
import json
import math
import time
import random
import threading
import datetime

import requests

# ------------------------- SETTINGS -------------------------
DATA_SOURCE = os.environ.get("MOCHI_SOURCE", "pro")    # "pro" or "demo"
CREDS_FILE = os.path.expanduser(
    os.environ.get("MOCHI_CREDS", "~/.claude/.credentials.json"))
I2C_ADDRESS = int(os.environ.get("MOCHI_I2C_ADDR", "0x3C"), 16)
NIGHT = os.environ.get("MOCHI_NIGHT", "23-7")          # sleep hours, or "off"
FORCE_EXPR = os.environ.get("MOCHI_FORCE", "")

REFRESH_SECONDS = 120
EYES_SECONDS = 12
STATS_SECONDS = 6
CELEBRATE_SECONDS = 30
FPS = 25

USAGE_URLS = [
    "https://api.anthropic.com/api/oauth/usage",
    "https://claude.ai/api/oauth/usage",
]

EXPRESSIONS = ["happy", "normal", "worried", "stressed", "panic", "dizzy",
               "love", "sleepy", "sleeping", "surprised", "wink",
               "curious", "squint"]

# ------------------------- SHARED DATA -------------------------
usage = {"session": None, "session_reset": None,
         "week": None, "week_reset": None,
         "updated": None, "error": "Starting...", "celebrate_until": 0}
usage_lock = threading.Lock()


def read_token():
    with open(CREDS_FILE) as f:
        return json.load(f)["claudeAiOauth"]["accessToken"]


def get_raw_usage():
    headers = {
        "Authorization": f"Bearer {read_token()}",
        "anthropic-beta": "oauth-2025-04-20",
        "Content-Type": "application/json",
    }
    last_error = None
    for url in USAGE_URLS:
        try:
            r = requests.get(url, headers=headers, timeout=20)
            if r.status_code == 401:
                raise RuntimeError("Login expired: run claude")
            r.raise_for_status()
            return r.json()
        except RuntimeError:
            raise
        except Exception as e:
            last_error = e
    raise RuntimeError(f"Usage fetch failed: {last_error}")


def parse_reset(value):
    if not value:
        return None
    try:
        dt = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.astimezone()
    except Exception:
        return None


def fetch_pro():
    data = get_raw_usage()
    five = data.get("five_hour") or {}
    seven = data.get("seven_day") or {}
    return {
        "session": float(five.get("utilization") or 0),
        "session_reset": parse_reset(five.get("resets_at")),
        "week": float(seven.get("utilization") or 0),
        "week_reset": parse_reset(seven.get("resets_at")),
    }


def fetch_demo():
    now = datetime.datetime.now().astimezone()
    with usage_lock:
        s = usage["session"] or 0
        w = usage["week"] or 0
    s = (s + random.uniform(4, 12)) % 105     # wraps around -> triggers "reset"
    w = min(100, w + random.uniform(0.5, 2))
    return {"session": min(100, s), "session_reset": now + datetime.timedelta(hours=3),
            "week": w, "week_reset": now + datetime.timedelta(days=2)}


def updater():
    while True:
        try:
            data = fetch_demo() if DATA_SOURCE == "demo" else fetch_pro()
            data["updated"] = datetime.datetime.now().strftime("%H:%M")
            data["error"] = None
            with usage_lock:
                old = usage["session"]
                # A big drop means the 5-hour session just reset: celebrate!
                if old is not None and old - data["session"] >= 20:
                    usage["celebrate_until"] = time.time() + CELEBRATE_SECONDS
                usage.update(data)
        except FileNotFoundError:
            with usage_lock:
                usage["error"] = "No login: run claude"
        except Exception as e:
            print("Fetch error:", e)
            with usage_lock:
                usage["error"] = str(e)[:40]
        time.sleep(10 if DATA_SOURCE == "demo" else REFRESH_SECONDS)


def is_night():
    if NIGHT == "off":
        return False
    try:
        start, end = (int(v) for v in NIGHT.split("-"))
    except ValueError:
        return False
    h = datetime.datetime.now().hour
    return (h >= start or h < end) if start > end else (start <= h < end)


def base_expression():
    """Pick the main expression from the usage data."""
    if FORCE_EXPR:
        return FORCE_EXPR
    with usage_lock:
        err, s, w = usage["error"], usage["session"], usage["week"]
        celebrate = usage["celebrate_until"]
    if err or s is None:
        return "sleepy"
    if time.time() < celebrate:
        return "love"
    if s >= 100:
        return "dizzy"
    if is_night() and s < 80:
        return "sleeping"
    if s >= 95:
        return "panic"
    if s >= 80:
        return "stressed"
    if w is not None and w >= 80:
        return "worried"
    if s >= 50:
        return "normal"
    return "happy"


# ------------------------- EYE ANIMATION -------------------------
EYE_W, EYE_H, RADIUS = 34, 38, 10
STILL = {"sleeping", "dizzy", "love", "surprised"}          # don't look around
BLINKERS = {"happy", "normal", "worried", "stressed", "panic", "curious", "squint"}
IDLE_QUIRKS = ["wink", "curious", "squint", "surprised"]


class Eyes:
    def __init__(self):
        now = time.time()
        self.x = self.y = 0.0
        self.tx = self.ty = 0
        self.next_look = now + 2
        self.next_blink = now + 3
        self.blink_start = None
        self.quirk = None
        self.quirk_until = 0
        self.next_quirk = now + random.uniform(8, 15)

    def update(self, base):
        now = time.time()
        expr = base

        # Random idle quirks only when relaxed
        if base in ("happy", "normal"):
            if self.quirk and now < self.quirk_until:
                expr = self.quirk
            elif now >= self.next_quirk:
                self.quirk = random.choice(IDLE_QUIRKS)
                self.quirk_until = now + random.uniform(1.2, 2.0)
                self.next_quirk = now + random.uniform(10, 25)
                expr = self.quirk
            else:
                self.quirk = None

        # Where to look
        if expr in STILL:
            self.tx = self.ty = 0
        elif now >= self.next_look:
            self.tx = random.choice([-14, -8, 0, 0, 8, 14])
            self.ty = random.choice([-6, 0, 0, 5])
            self.next_look = now + random.uniform(1.5, 4.0)
        speed = 0.45 if expr == "panic" else 0.25          # panic = darting eyes
        self.x += (self.tx - self.x) * speed
        self.y += (self.ty - self.y) * speed

        # Blinking
        openness = 1.0
        if expr in BLINKERS:
            if self.blink_start is None and now >= self.next_blink:
                self.blink_start = now
            if self.blink_start is not None:
                t = (now - self.blink_start) / 0.18
                if t >= 1:
                    self.blink_start = None
                    self.next_blink = now + random.uniform(2, 6)
                else:
                    openness = abs(1 - 2 * t)
        return expr, int(self.x), int(self.y), openness, now


# ------------------------- DRAWING HELPERS -------------------------
def eye_box(draw, x, y, w, h, r=RADIUS):
    r = max(1, min(r, h // 2, w // 2))
    draw.rounded_rectangle([x - w // 2, y - h // 2, x + w // 2, y + h // 2],
                           radius=r, fill="white")


def draw_heart(draw, x, y, r):
    draw.ellipse([x - 2 * r, y - r, x, y + r], fill="white")
    draw.ellipse([x, y - r, x + 2 * r, y + r], fill="white")
    draw.polygon([(x - 2 * r + 1, y + int(r * 0.3)),
                  (x + 2 * r - 1, y + int(r * 0.3)),
                  (x, y + 2 * r + 2)], fill="white")


def draw_z(draw, x, y, s):
    draw.line([(x, y), (x + s, y), (x, y + s), (x + s, y + s)], fill="white", width=2)


def draw_sweat(draw, t):
    fall = int((t * 18) % 22)
    cx, cy = 122, 8 + fall
    draw.polygon([(cx, cy - 9), (cx - 4, cy), (cx + 4, cy)], fill="white")
    draw.ellipse([cx - 4, cy - 4, cx + 4, cy + 4], fill="white", outline="black")


def draw_face(draw, expr, lx, ly, openness, t):
    (x1, y1), (x2, y2) = (38 + lx, 32 + ly), (90 + lx, 32 + ly)

    if expr == "sleeping":
        for x in (38, 90):
            draw.arc([x - 15, 30, x + 15, 46], 0, 180, fill="white", width=3)
        zs = [(100, 22, 4), (108, 13, 6), (117, 2, 8)]
        for zx, zy, s in zs[:int(t * 1.5) % 4]:
            draw_z(draw, zx, zy, s)
        return

    if expr == "dizzy":
        dx, dy = int(3 * math.sin(t * 6)), int(3 * math.cos(t * 6))
        for x, y in ((38 + dx, 32 + dy), (90 - dx, 32 - dy)):
            draw.line([x - 11, y - 11, x + 11, y + 11], fill="white", width=5)
            draw.line([x - 11, y + 11, x + 11, y - 11], fill="white", width=5)
        return

    if expr == "love":
        r = 8 + round(1.5 * math.sin(t * 8))              # heartbeat pulse
        draw_heart(draw, 38, 26, r)
        draw_heart(draw, 90, 26, r)
        return

    if expr == "surprised":
        eye_box(draw, 38, 29, 26, 40, 9)
        eye_box(draw, 90, 29, 26, 40, 9)
        draw.ellipse([60, 54, 67, 61], outline="white", width=2)   # little "o" mouth
        return

    if expr == "wink":
        draw.arc([x1 - 15, y1 - 6, x1 + 15, y1 + 10], 180, 360, fill="white", width=4)
        eye_box(draw, x2, y2, EYE_W, EYE_H)
        return

    if expr == "curious":
        eye_box(draw, x1, y1, EYE_W, max(2, int(42 * openness)))
        eye_box(draw, x2, y2 + 4, 30, max(2, int(24 * openness)))
        return

    # Open-eye family: happy, normal, worried, stressed, panic, sleepy, squint
    for i, (x, y) in enumerate(((x1, y1), (x2, y2))):
        h = max(2, int(EYE_H * openness))
        if expr == "sleepy":
            h = min(h, 10)
        elif expr == "squint":
            h = min(h, 16)
        eye_box(draw, x, y, EYE_W, h)
        if h <= 12:
            continue
        left, right = x - EYE_W // 2, x + EYE_W // 2
        top, bottom = y - h // 2, y + h // 2
        if expr == "happy":
            draw.ellipse([left - 4, y + 2, right + 4, bottom + 14], fill="black")
        elif expr in ("stressed", "panic"):       # inner corners down = frown
            corner = (right + 1, top + 12) if i == 0 else (left - 1, top + 12)
            draw.polygon([(left - 1, top - 1), (right + 1, top - 1), corner], fill="black")
        elif expr == "worried":                   # outer corners down = sad
            corner = (left - 1, top + 12) if i == 0 else (right + 1, top + 12)
            draw.polygon([(left - 1, top - 1), (right + 1, top - 1), corner], fill="black")

    if expr == "panic":
        draw_sweat(draw, t)


# ------------------------- STATS PAGE -------------------------
def fmt_time(dt, with_day=False):
    if dt is None:
        return "--"
    t = dt.strftime("%I:%M%p").lstrip("0")
    return f"{dt.strftime('%a')} {t}" if with_day else t


def draw_meter(draw, font, y, label, pct, reset_text):
    pct_text = f"{int(round(pct))}%" if pct is not None else "--"
    draw.text((0, y), label, font=font, fill="white")
    w = draw.textlength(pct_text, font=font)
    draw.text((127 - w, y), pct_text, font=font, fill="white")
    draw.rectangle([0, y + 12, 127, y + 17], outline="white")
    if pct:
        fill_w = int(125 * min(100, pct) / 100)
        if fill_w > 0:
            draw.rectangle([1, y + 13, 1 + fill_w, y + 16], fill="white")
    draw.text((0, y + 19), reset_text, font=font, fill="white")


def draw_stats(draw, font):
    with usage_lock:
        u = dict(usage)
    if u["session"] is None:
        draw.text((0, 10), "CLAUDE USAGE", font=font, fill="white")
        draw.text((0, 30), (u["error"] or "Loading...")[:21], font=font, fill="white")
        return
    draw_meter(draw, font, 0, "Session", u["session"],
               "Resets " + fmt_time(u["session_reset"]))
    draw_meter(draw, font, 32, "This week", u["week"],
               "Resets " + fmt_time(u["week_reset"], with_day=True))
    if u["error"]:
        draw.text((120, 52), "!", font=font, fill="white")


# ------------------------- MAIN -------------------------
def main(preview=False):
    from PIL import ImageFont
    from luma.core.interface.serial import i2c
    from luma.core.render import canvas
    from luma.oled.device import ssd1306

    device = ssd1306(i2c(port=1, address=I2C_ADDRESS), width=128, height=64)
    font = ImageFont.load_default()
    if not preview:
        threading.Thread(target=updater, daemon=True).start()

    eyes = Eyes()
    showing_eyes = True
    phase_start = time.time()
    last_printed = None
    print(f"Mochi v2 running (source: {DATA_SOURCE}, preview: {preview}). Ctrl+C to stop.")

    while True:
        now = time.time()
        if preview:
            base = EXPRESSIONS[int(now / 3) % len(EXPRESSIONS)]
            showing_eyes = True
        else:
            base = base_expression()
            if now - phase_start > (EYES_SECONDS if showing_eyes else STATS_SECONDS):
                showing_eyes = not showing_eyes
                phase_start = now

        with canvas(device) as draw:
            if showing_eyes:
                expr, lx, ly, openness, t = eyes.update(base)
                draw_face(draw, expr, lx, ly, openness, t)
                if expr != last_printed:
                    print("Expression:", expr)
                    last_printed = expr
            else:
                draw_stats(draw, font)
        time.sleep(1 / FPS)


if __name__ == "__main__":
    if "--test" in sys.argv:
        print(json.dumps(get_raw_usage(), indent=2))
        sys.exit(0)
    try:
        main(preview="--preview" in sys.argv)
    except KeyboardInterrupt:
        pass
