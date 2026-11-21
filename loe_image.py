import io
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


ACC_KINDS = {
    "emergency": ("Аварійне", (158, 52, 48)),
    "possible": ("Можливе аварійне", (237, 149, 44)),
    "gav": ("Графік аварійних (ГАВ)", (107, 31, 28)),
    "sgav": ("Спецграфік аварійних (СГАВ)", (107, 31, 28)),
    "switching": ("Оперативні перемикання", (111, 129, 149)),
    "planned": ("Планове", GREEN),
    "gpv": ("Погодинне (ГПВ)", GREEN_DARK),
    "other": ("Інше", MUTED),
}
ACC_PAGE_H = 1100
ACC_PAGE_MAX = 1600


def acc_time(iso, today):
    if not iso:
        return "—"
    return iso[11:16] if iso[:10] == today else f"{iso[8:10]}.{iso[5:7]} {iso[11:16]}"


def wrap(c, text, f, max_w, sep=None):
    parts = text.split(sep) if sep else text.split(" ")
    lines, cur = [], ""
    for i, p in enumerate(parts):
        piece = p + sep.rstrip() if sep and i < len(parts) - 1 else p
        test = f"{cur} {piece}" if cur else piece
        if not cur or c.width(test, f) <= max_w:
            cur = test
        else:
            lines.append(cur)
            cur = piece
    if cur:
        lines.append(cur)
    return lines or ["—"]


def render_accidents(rows, today):
    W, M, head_row, line_h, pad = 1440, 24, 44, 24, 12
    cols = {"city": 210, "street": 250, "kind": 240, "from": 115, "to": 150}
    houses_w = W - 2 * M - sum(cols.values())
    f_city, f_street, f_houses, f_kind, f_time, f_head = REG(17), SEMI(17), REG(17), REG(16), MED(17), MED(15)
    f_comment = REG(15)
    probe = Canvas(10, 10, WHITE)
    laid = []
    for r in rows:
        ct = wrap(probe, r["city"] or "—", f_city, cols["city"] - 28)
        st = wrap(probe, r["street"] or "—", f_street, cols["street"] - 24)
        hs = wrap(probe, ", ".join(r["houses"]) or "—", f_houses, houses_w - 24, ", ")
        cm = wrap(probe, r["comment"], f_comment, houses_w - 24) if r.get("comment") else []
        kd = wrap(probe, ACC_KINDS.get(r["kind"], ACC_KINDS["other"])[0], f_kind, cols["kind"] - 46)
        laid.append((r, ct, st, hs, cm, kd, max(len(ct), len(st), len(hs) + len(cm), len(kd)) * line_h + pad * 2))
    total = sum(l[-1] for l in laid)
    max_row = max(l[-1] for l in laid)
    n = min(3, max(1, -(-total // ACC_PAGE_H)))
    if total / n > ACC_PAGE_MAX:
        n = -(-total // ACC_PAGE_MAX)
    cap = float("inf") if n == 1 else max(ACC_PAGE_H, -(-total // n) + max_row)
    pages, used = [[]], 0
    for l in laid:
        if used + l[-1] > cap and pages[-1]:
            pages.append([])
            used = 0
        pages[-1].append(l)
        used += l[-1]

    mark = None
    for name in ("watermark.png", "loebot.png", "favicon-192.png"):
        try:
            mark = Image.open(os.path.join(ASSETS, name)).convert("RGBA")
            break
        except OSError:
            continue
    if mark is None:
        print("Увага: немає assets/watermark.png, водяний знак буде без блискавки")
    out = []
    for page in pages:
        body_h = sum(l[-1] for l in page)
        top = M
        H = top + head_row + body_h + M
        c = Canvas(W, H, WHITE)
        cx = {"city": M, "street": M + cols["city"], "houses": M + cols["city"] + cols["street"]}
        cx["kind"] = cx["houses"] + houses_w
        cx["from"] = W - M - cols["to"] - cols["from"]
        cx["to"] = W - M - cols["to"]
        c.rect(M, top, W - 2 * M, head_row, GREEN_DARK)
        for t, x in [("Населений пункт", cx["city"] + 16), ("Вулиця", cx["street"] + 12),
                     ("Будинки", cx["houses"] + 12), ("Тип", cx["kind"] + 12),
                     ("Вимкнено", cx["from"] + 12), ("Орієнт. увімкнуть", cx["to"] + 12)]:
            c.text(x, top + head_row // 2, t, f_head, WHITE, "lm")
        y = top + head_row
        for r, ct, st, hs, cm, kd, h in page:
            colr = ACC_KINDS.get(r["kind"], ACC_KINDS["other"])[1]
            c.rect(M, y, 4, h - 1, colr)
            ly = lambda i: y + pad + line_h * i + line_h // 2
            for i, t in enumerate(ct):
                c.text(cx["city"] + 16, ly(i), t, f_city, INK, "lm")
            for i, t in enumerate(st):
                c.text(cx["street"] + 12, ly(i), t, f_street, INK, "lm")
            for i, t in enumerate(hs):
                c.text(cx["houses"] + 12, ly(i), t, f_houses, INK, "lm")
            for i, t in enumerate(cm):
                c.text(cx["houses"] + 12, ly(len(hs) + i), t, f_comment, MUTED, "lm")
            c.rect(cx["kind"] + 12, ly(0) - 6, 12, 12, colr)
            for i, t in enumerate(kd):
                c.text(cx["kind"] + 34, ly(i), t, f_kind, INK, "lm")
            c.text(cx["from"] + 12, ly(0), acc_time(r["from"], today), f_time, INK, "lm")
            c.text(cx["to"] + 12, ly(0), acc_time(r["to"], today), f_time, INK, "lm")
            y += h
            c.rect(M, y - 1, W - 2 * M, 1, RULE)

        area_top = top + head_row
        wm_rows = max(1, round(body_h / 620))
        wm_cols = 2 if W / body_h > 3.2 else 1
        size = round(min(340, max(140, min(body_h / wm_rows, W / wm_cols) * 0.6)))
        spots = []
        for i in range(wm_rows):
            cy = area_top + body_h * (i + 0.5) / wm_rows
            if wm_cols == 2:
                spots += [(W * 0.27, cy), (W * 0.73, cy)]
            else:
                spots.append((W * (0.68 if i % 2 else 0.32) if wm_rows > 1 else W / 2, cy))
        layer = Image.new("RGBA", c.img.size, (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        m = None
        if mark:
            m = mark.resize((size * S, size * S), Image.LANCZOS)
            m.putalpha(m.getchannel("A").point(lambda a: round(a * 0.11)))
        wf = TITLE(round(size * 0.15))
        for wx, wy in spots:
            block_top = wy - size * 1.18 / 2
            if m:
                layer.alpha_composite(m, (round((wx - size / 2) * S), round(block_top * S)))
            ld.text((wx * S, (block_top + size * 1.1) * S), "t.me/lvivpoweroutage", font=wf,
                    fill=GREEN_DARK + (round(255 * 0.13),), anchor="ms")
        img = Image.alpha_composite(c.img.convert("RGBA"), layer).convert("RGB")
        buf = io.BytesIO()
        img.save(buf, "PNG", optimize=True)
        out.append(buf.getvalue())
    return out
