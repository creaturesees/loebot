import os
from datetime import datetime

from PIL import Image, ImageDraw, ImageFont

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")

GREEN = (93, 137, 74)
GREEN_DARK = (66, 99, 52)
ORANGE = (237, 149, 44)
WHITE = (255, 255, 255)
INK = (31, 36, 32)
MUTED = (110, 117, 108)
RULE = (219, 224, 214)
HEAD_BG = (241, 244, 238)

ON = (227, 237, 220)
OFF = (158, 52, 48)
CANCELLED = (140, 203, 110)
EXTRA = ORANGE

GROUPS = ["1.1", "1.2", "2.1", "2.2", "3.1", "3.2", "4.1", "4.2", "5.1", "5.2", "6.1", "6.2"]
WEEKDAYS = ["Понеділок", "Вівторок", "Середа", "Четвер", "П'ятниця", "Субота", "Неділя"]
MONTHS = ["січня", "лютого", "березня", "квітня", "травня", "червня",
          "липня", "серпня", "вересня", "жовтня", "листопада", "грудня"]

S = 2
W = 1280
M = 32


def font(file, size):
    return ImageFont.truetype(os.path.join(ASSETS, file), size * S)


TITLE = lambda size: font("Carlito-Bold.ttf", size)
REG = lambda size: font("FiraSans-Regular.ttf", size)
MED = lambda size: font("FiraSans-Medium.ttf", size)
SEMI = lambda size: font("FiraSans-SemiBold.ttf", size)


def to_min(t):
    h, m = map(int, t.split(":"))
    return h * 60 + m


def hhmm(mins):
    return f"{mins // 60:02d}:{mins % 60:02d}"


def slots(intervals):
    out = [False] * 48
    for a, b in intervals or []:
        s, e = to_min(a), to_min(b)
        for i in range(48):
            if s < (i + 1) * 30 and e > i * 30:
                out[i] = True
    return out


def hours_label(intervals):
    if intervals is None:
        return "—"
    mins = sum(to_min(b) - to_min(a) for a, b in intervals)
    h, m = divmod(mins, 60)
    if m == 0:
        return str(h)
    if m == 30:
        return f"{h},5"
    return f"{h}:{m:02d}"


class Canvas:
    def __init__(self, w, h, bg):
        self.img = Image.new("RGB", (w * S, h * S), bg)
        self.d = ImageDraw.Draw(self.img)

    def rect(self, x, y, w, h, fill):
        self.d.rectangle([x * S, y * S, (x + w) * S - 1, (y + h) * S - 1], fill=fill)

    def text(self, x, y, s, f, fill, anchor="la"):
        self.d.text((x * S, y * S), s, font=f, fill=fill, anchor=anchor)

    def width(self, s, f):
        return self.d.textlength(s, font=f) / S

    def paste(self, im, x, y):
        self.img.paste(im, (x * S, y * S), im)


def render_schedule(s, old_groups=None, path="schedule.png"):
    groups = s["groups"]
    d = datetime.strptime(s["date"], "%d.%m.%Y")

    head_h = 168
    logo_h = 72
    logo_top = (head_h - logo_h) // 2
    logo_bottom = logo_top + logo_h

    time_w = 116
    col = 40
    half_w = time_w + 12 * col
    gap = W - 2 * M - 2 * half_w
    head_row = 46
    sum_row = 46
    row = 34

    grid_top = head_h + 36
    rows_top = grid_top + head_row + sum_row
    grid_bottom = rows_top + 24 * row

    foot_top = grid_bottom + 30
    H = foot_top + 66

    c = Canvas(W, H, WHITE)

    c.rect(0, 0, W, head_h, GREEN)
    logo = Image.open(os.path.join(ASSETS, "logo-mark.png")).convert("RGBA")
    lw = round(logo.width * logo_h / logo.height)
    c.paste(logo.resize((lw * S, logo_h * S), Image.LANCZOS), M, logo_top)

    title_f = TITLE(52)
    cap = -title_f.getbbox("Г", anchor="ls")[1] / S
    title_base = round(logo_top + cap)
    tx = M + lw + 32
    c.text(tx, title_base, "Графік погодинних відключень", title_f, WHITE, "ls")
    c.text(tx, logo_bottom, f"{WEEKDAYS[d.weekday()]}, {d.day} {MONTHS[d.month - 1]} {d.year}",
           TITLE(33), ORANGE, "ls")
    if s.get("updated"):
        c.text(W - M, title_base, "Інформація станом на", REG(19), (222, 233, 214), "rs")
        c.text(W - M, logo_bottom, s["updated"], SEMI(28), WHITE, "rs")

    new_slots = {g: slots(groups.get(g)) for g in GROUPS}
    old_slots = {g: slots(old_groups.get(g)) for g in GROUPS} if old_groups else None

    def state(g, i):
        n = new_slots[g][i]
        if old_slots is not None:
            o = old_slots[g][i]
            if n and not o:
                return EXTRA
            if o and not n:
                return CANCELLED
        return OFF if n else ON

    for half in range(2):
        gx = M + half * (half_w + gap)
        c.rect(gx, grid_top, half_w, head_row, GREEN_DARK)
        c.text(gx + 12, grid_top + head_row // 2, "Час", MED(18), WHITE, "lm")
        sy = grid_top + head_row
        c.rect(gx, sy, half_w, sum_row, HEAD_BG)
        c.text(gx + 12, sy + sum_row // 2, "Год. за добу", REG(15), MUTED, "lm")
        for gi, g in enumerate(GROUPS):
            cx = gx + time_w + gi * col + col // 2
            c.text(cx, grid_top + head_row // 2, g, MED(18), WHITE, "mm")
            c.text(cx, sy + sum_row // 2, hours_label(groups.get(g)), SEMI(19), INK, "mm")
        c.rect(gx, sy + sum_row - 1, half_w, 1, RULE)
        for r in range(24):
            i = half * 24 + r
            y = rows_top + r * row
            c.text(gx + 12, y + row // 2, f"{hhmm(i * 30)}–{hhmm(i * 30 + 30)}", REG(18), INK, "lm")
            for gi, g in enumerate(GROUPS):
                c.rect(gx + time_w + gi * col + 1, y + 1, col - 2, row - 2, state(g, i))
            c.rect(gx, y + row - 1, time_w, 1, RULE)

    leg = [("Є світло", ON), ("Немає світла", OFF)]
    if old_slots is not None:
        leg += [("Відключення скасоване", CANCELLED), ("Додаткове відключення", EXTRA)]
    lx = M
    ly = foot_top + 10
    for t, colr in leg:
        c.rect(lx, ly, 22, 22, colr)
        c.text(lx + 32, ly + 11, t, REG(19), INK, "lm")
        lx += 32 + round(c.width(t, REG(19))) + 36
    c.text(W - M, ly + 11, "t.me/lvivpoweroutage", SEMI(19), GREEN_DARK, "rm")
    c.text(W - M, ly + 39, "Джерело: Львівобленерго", REG(16), MUTED, "rm")

    c.img.save(path, optimize=True)
    return path
