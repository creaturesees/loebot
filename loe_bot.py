import csv
import hashlib
import html
import json
import os
import re
from datetime import datetime, timezone

import requests

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
CHAT_ID = os.environ.get("CHAT_ID", "")
MAIN_CHANNEL_ID = os.environ.get("MAIN_CHANNEL_ID", "").strip()
GPV_TARGET = (os.environ.get("GPV_TARGET", "") or "both").strip().lower()
HC_URL = os.environ.get("HC_URL", "")
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK", "").strip()
DISCORD_ROLE_ID = os.environ.get("DISCORD_ROLE_ID", "").strip()
TG_EMOJI_ID = os.environ.get("TG_EMOJI_ID", "").strip()
DISCORD_EMOJI_ID = os.environ.get("DISCORD_EMOJI_ID", "").strip()
TG_EMOJI_SOS_ID = os.environ.get("TG_EMOJI_SOS_ID", "").strip()
DISCORD_EMOJI_SOS_ID = os.environ.get("DISCORD_EMOJI_SOS_ID", "").strip()
CHANNEL_MAIN = "lvivpoweroutage"
CHANNEL_SOS = "lvivsosoutage"
STATE_FILE = "last_hash.txt"
PREV_FILE = "last_schedules.json"
HISTORY_FILE = "history.csv"
HISTORY_HEADER = ["зафіксовано", "дата", "станом_на", "група", "з", "до", "хвилин", "примітка"]

API_URL = "https://api.loe.lviv.ua/api/menus?page=1&type=photo-grafic"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (loe-schedule-bot)",
    "Accept": "application/ld+json, application/json;q=0.9",
}

WEEKDAYS = ["Понеділок", "Вівторок", "Середа", "Четвер", "П'ятниця", "Субота", "Неділя"]
MONTHS = ["січня", "лютого", "березня", "квітня", "травня", "червня",
          "липня", "серпня", "вересня", "жовтня", "листопада", "грудня"]

LINK_GROUP = "https://t.me/lvivpoweroutage/1321"
LINK_SUBSCRIBE = "https://t.me/lvivpoweroutage/"
LINK_CHAT = "https://t.me/+YI1JiVsa6hNmODky"

RE_DATE = re.compile(r"Графік погодинних відключень на (\d{2}\.\d{2}\.\d{4})")
RE_UPDATED = re.compile(r"Інформація станом на (\d{2}:\d{2} \d{2}\.\d{2}\.\d{4})")
RE_GROUP = re.compile(r"Група (\d\.\d)\.\s*(.+)")
RE_INTERVAL = re.compile(r"з (\d{2}:\d{2}) до (\d{2}:\d{2})")


def html_to_lines(raw):
    text = re.sub(r"<[^>]+>", "\n", raw)
    text = html.unescape(text)
    return [line.strip() for line in text.splitlines() if line.strip()]


def parse_schedule(raw_html):
    lines = html_to_lines(raw_html)
    joined = "\n".join(lines)

    date = RE_DATE.search(joined)
    updated = RE_UPDATED.search(joined)
    if not date:
        return None

    groups = {}
    for line in lines:
        m = RE_GROUP.match(line)
        if m:
            groups[m.group(1)] = [list(x) for x in RE_INTERVAL.findall(m.group(2))]

    return {
        "date": date.group(1),
        "updated": updated.group(1) if updated else "",
        "groups": groups,
    }


def fetch_schedules():
    r = requests.get(API_URL, params={"_": int(datetime.now(timezone.utc).timestamp())},
                     headers=HEADERS, timeout=60)
    r.raise_for_status()
    data = r.json()

    if isinstance(data, dict):
        menus = data.get("hydra:member") or data.get("member") or [data]
    elif isinstance(data, list):
        menus = data
    else:
        menus = []

    items = []
    for menu in menus:
        if not isinstance(menu, dict):
            continue
        if "menuItems" in menu:
            items.extend(menu.get("menuItems") or [])
        else:
            items.append(menu)

    result = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("children"):
            continue
        raw = item.get("rawHtml") or ""
        if raw:
            s = parse_schedule(raw)
            if s:
                result.append({"kind": "schedule", **s})
        elif (item.get("description") or "").strip():
            result.append({"kind": "text", "text": item["description"].strip()})
    return result


def to_minutes(t):
    h, m = map(int, t.split(":"))
    return h * 60 + m


def duration(start, end):
    h, m = divmod(to_minutes(end) - to_minutes(start), 60)
    if h and m:
        return f"{h} год {m} хв"
    return f"{h} год" if h else f"{m} хв"


def fmt_intervals(intervals):
    if not intervals:
        return "без відключень"
    return ", ".join(f"{a}–{b}" for a, b in intervals)


def total_minutes(intervals):
    return sum(to_minutes(b) - to_minutes(a) for a, b in intervals)


def fmt_delta(mins):
    sign = "+" if mins > 0 else "−"
    h, m = divmod(abs(mins), 60)
    if h and m:
        return f"{sign}{h} год {m} хв"
    return f"{sign}{h} год" if h else f"{sign}{m} хв"


def schedule_changes(old_groups, new_groups):
    key = lambda g: tuple(map(int, g.split(".")))
    changes = []
    for g in sorted(set(old_groups) | set(new_groups), key=key):
        old = [tuple(x) for x in old_groups.get(g, [])]
        new = [tuple(x) for x in new_groups.get(g, [])]
        if old == new:
            continue
        delta = total_minutes(new) - total_minutes(old)
        if delta > 0:
            icon, tail = "🔴", f" ({fmt_delta(delta)} без світла)"
        elif delta < 0:
            icon, tail = "🟢", f" ({fmt_delta(delta)} без світла)"
        else:
            icon, tail = "🟡", " (зсув у часі)"
        changes.append(f"{icon} Група {g}: {fmt_intervals(old)} → {fmt_intervals(new)}{tail}")
    return changes


class TelegramFmt:
    @staticmethod
    def esc(t): return html.escape(t, quote=False)
    @classmethod
    def bold(cls, t): return f"<b>{cls.esc(t)}</b>"
    @classmethod
    def italic(cls, t): return f"<i>{cls.esc(t)}</i>"
    @classmethod
    def code(cls, t): return f"<code>{cls.esc(t)}</code>"
    @classmethod
    def link(cls, t, url):
        return f'<a href="{html.escape(url)}">{cls.esc(t)}</a>' if url else cls.esc(t)
    @staticmethod
    def logo(fallback="⚡️", emoji_id=None, alt=None):
        emoji_id = TG_EMOJI_ID if emoji_id is None else emoji_id
        if emoji_id.isdigit():
            return f'<tg-emoji emoji-id="{emoji_id}">{alt or fallback}</tg-emoji>'
        return fallback
    @staticmethod
    def channel(name):
        return f"@{name}"


class DiscordFmt:
    @staticmethod
    def esc(t): return re.sub(r"([\\*_`~|>\[\]])", r"\\\1", t)
    @classmethod
    def bold(cls, t): return f"**{cls.esc(t)}**"
    @classmethod
    def italic(cls, t): return f"*{cls.esc(t)}*"
    @staticmethod
    def code(t): return f"`{t.replace('`', '')}`"
    @classmethod
    def link(cls, t, url):
        return f"[{cls.esc(t)}](<{url}>)" if url else cls.esc(t)
    @staticmethod
    def logo(fallback="⚡️", emoji_id=None, alt=None):
        emoji_id = DISCORD_EMOJI_ID if emoji_id is None else emoji_id
        return f"<:e:{emoji_id}>" if emoji_id.isdigit() else fallback
    @staticmethod
    def channel(name):
        return f"[@{name}](<https://t.me/{name}>)"


def schedule_footer(f):
    sos_id = TG_EMOJI_SOS_ID if f is TelegramFmt else DISCORD_EMOJI_SOS_ID
    return [f'{f.logo("⚡️")} {f.link("Підписатись", LINK_SUBSCRIBE)}  | {f.link("💬 Чат", LINK_CHAT)}',
            f'{f.logo("🆘", sos_id, "🆘")} {f.link("Аварійні відключення", f"https://t.me/{CHANNEL_SOS}")}']


def channel_footer(f):
    return [f.esc(f"@{CHANNEL_MAIN}"),
            f'{f.link("💬 Чат", LINK_CHAT)} | {f.link("🆘 Аварійні відключення", f"https://t.me/{CHANNEL_SOS}")}']


def footer(f):
    sos_id = TG_EMOJI_SOS_ID if f is TelegramFmt else DISCORD_EMOJI_SOS_ID
    return [f"{f.logo('⚡️', sos_id, '🆘')} {f.channel(CHANNEL_SOS)}",
            f"{f.logo('⚡️')} {f.channel(CHANNEL_MAIN)}"]


def format_post(s, f=TelegramFmt, changes=None, channel=False):
    if s["kind"] == "text":
        return f.bold("⚡️ Львівобленерго") + "\n\n" + f.esc(s["text"])

    d = datetime.strptime(s["date"], "%d.%m.%Y")
    lines = [
        f.bold("⏱️ Графік погодинних відключень"),
        f.bold(f"{WEEKDAYS[d.weekday()].upper()}, {d.day} {MONTHS[d.month - 1]} {d.year}"),
        "",
    ]
    if s["updated"]:
        lines += [f.italic(f"Інформація станом на {s['updated']}"), ""]

    now = now_kyiv()
    date_key = (d.year, d.month, d.day)
    today_key = (now.year, now.month, now.day)
    now_min = now.hour * 60 + now.minute if date_key == today_key else (10 ** 6 if date_key < today_key else -1)

    def ended(end):
        h, m = map(int, end.split(":"))
        return h * 60 + m <= now_min

    blocks = []
    for group in sorted(s["groups"], key=lambda g: tuple(map(int, g.split(".")))):
        block = [f"Група {group}"]
        intervals = s["groups"][group]
        left = [(a, b) for a, b in intervals if not ended(b)]
        if left:
            for start, end in left:
                block.append(f"{start} — {end} ({duration(start, end)})")
        elif intervals:
            block.append("☑️ Усі відключення закінчились")
        else:
            block.append("✅ Відключень немає")
        blocks.append("\n".join(f.code(line) for line in block))
    lines.append("\n\n".join(blocks))
    lines.append("")

    lines += [
        f.esc("Надсилай рідним та друзям, щоб вони могли спланувати свій час."),
        "",
        f.link("❗️ Як дізнатися свою групу відключень?", LINK_GROUP),
        "",
        *(channel_footer(f) if channel else schedule_footer(f)),
    ]
    return "\n".join(lines)


def item_hash(s):
    return hashlib.sha256(json.dumps(s, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def make_image(s, old_groups):
    if s["kind"] != "schedule":
        return None
    try:
        import loe_image
        path = loe_image.render_schedule(s, old_groups, "schedule.png")
        with open(path, "rb") as f:
            return f.read()
    except Exception as e:
        print("Картинку не вдалося згенерувати:", e)
        return None


def tg_len(text):
    plain = html.unescape(re.sub(r"<[^>]+>", "", text))
    return len(plain.encode("utf-16-le")) // 2


def tg_call(method, data, files=None):
    return requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/{method}",
                         data=data, files=files, timeout=60)


def plain_emoji(text):
    return re.sub(r'<tg-emoji emoji-id="\d+">(.*?)</tg-emoji>', r"\1", text)


def send_telegram(text, image=None, chat_ids=None, quiet=True):
    if chat_ids is None:
        chat_ids = [c.strip() for c in CHAT_ID.split(",") if c.strip()]
    ok = _send_telegram(text, image, chat_ids, quiet)
    if not ok and "<tg-emoji" in text:
        print("Telegram: повтор без кастомного емодзі")
        ok = _send_telegram(plain_emoji(text), image, chat_ids, quiet)
    return ok


def quiet_hours():
    h = now_kyiv().hour
    return h < 9 or h >= 23


def _send_telegram(text, image, chat_ids, quiet=True):
    silent = {"disable_notification": "true"} if quiet and quiet_hours() else {}
    fits = tg_len(text) <= 1024
    file_id = None
    ok = 0
    for chat_id in chat_ids:
        msg = {"chat_id": chat_id, "text": text, "parse_mode": "HTML",
               "disable_web_page_preview": "true", **silent}
        if image:
            data = {"chat_id": chat_id, **silent}
            if fits:
                data.update(caption=text, parse_mode="HTML")
            if file_id:
                data["photo"] = file_id
                r = tg_call("sendPhoto", data)
            else:
                r = tg_call("sendPhoto", data, {"photo": ("schedule.png", image, "image/png")})
            if r.ok:
                try:
                    file_id = r.json()["result"]["photo"][-1]["file_id"]
                except Exception:
                    pass
                if not fits:
                    r = tg_call("sendMessage", msg)
            else:
                print(f"Telegram: фото не надіслано {chat_id}: {r.status_code} {r.text[:200]}")
                r = tg_call("sendMessage", msg)
        else:
            r = tg_call("sendMessage", msg)
        if r.ok:
            ok += 1
        else:
            print(f"Telegram: не вдалося надіслати {chat_id}: {r.status_code} {r.text[:200]}")
    return ok


def discord_post(payload, image=None):
    if image:
        return requests.post(DISCORD_WEBHOOK, data={"payload_json": json.dumps(payload)},
                             files={"files[0]": ("schedule.png", image, "image/png")}, timeout=60)
    return requests.post(DISCORD_WEBHOOK, json=payload, timeout=30)


def send_discord(text, image=None, ping_text=None):
    if not DISCORD_WEBHOOK:
        return 0
    if DISCORD_ROLE_ID and not quiet_hours():
        content = f"<@&{DISCORD_ROLE_ID}>" + (f" {ping_text}" if ping_text else "")
        r = discord_post({"content": content, "allowed_mentions": {"roles": [DISCORD_ROLE_ID]}})
        if not r.ok:
            print(f"Discord: пінг не надіслано {r.status_code} {r.text[:200]}")
    r = discord_post({"content": text[:2000], "allowed_mentions": {"parse": []}, "flags": 4}, image)
    if r.ok:
        return 1
    print(f"Discord: помилка {r.status_code} {r.text[:200]}")
    return 0


def ping_text(s, changes):
    if s["kind"] != "schedule":
        return "оновлення від Львівобленерго"
    d = datetime.strptime(s["date"], "%d.%m.%Y")
    what = "оновлено графік" if changes is not None else "новий графік"
    return f"{what} на {d.day} {MONTHS[d.month - 1]}"


def send(s, changes=None, old_groups=None):
    image = make_image(s, old_groups)
    ok = 0
    to_bot = GPV_TARGET in ("both", "bot")
    to_channel = GPV_TARGET in ("both", "channel") and MAIN_CHANNEL_ID
    if BOT_TOKEN and CHAT_ID and to_bot:
        ok += send_telegram(format_post(s, TelegramFmt, changes), image)
    if BOT_TOKEN and to_channel:
        ok += send_telegram(plain_emoji(format_post(s, TelegramFmt, changes, channel=True)), image, [MAIN_CHANNEL_ID], quiet=False)
    ok += send_discord(format_post(s, DiscordFmt, changes), image, ping_text(s, changes))
    if ok == 0 and GPV_TARGET != "off":
        raise RuntimeError("Не вдалося надіслати нікуди (ні Telegram, ні Discord)")


def load_prev():
    try:
        with open(PREV_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_prev(prev):
    keep = sorted(prev, key=lambda d: datetime.strptime(d, "%d.%m.%Y"))[-5:]
    with open(PREV_FILE, "w", encoding="utf-8") as f:
        json.dump({d: prev[d] for d in keep}, f, ensure_ascii=False, indent=1, sort_keys=True)


def now_kyiv():
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Europe/Kyiv"))
    except Exception:
        return datetime.now(timezone.utc)


def append_history(s):
    new_file = not os.path.exists(HISTORY_FILE)
    stamp = now_kyiv().strftime("%Y-%m-%d %H:%M")
    rows = []
    if s["kind"] == "text":
        rows.append([stamp, "", "", "", "", "", "", s["text"]])
    else:
        key = lambda g: tuple(map(int, g.split(".")))
        for g in sorted(s["groups"], key=key):
            intervals = s["groups"][g]
            if not intervals:
                rows.append([stamp, s["date"], s["updated"], g, "", "", 0, "без відключень"])
            for a, b in intervals:
                rows.append([stamp, s["date"], s["updated"], g, a, b,
                             to_minutes(b) - to_minutes(a), ""])
    with open(HISTORY_FILE, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(HISTORY_HEADER)
        w.writerows(rows)


def main():
    seen = set()
    if os.path.exists(STATE_FILE):
        seen = {line.strip() for line in open(STATE_FILE) if line.strip()}
    prev = load_prev()
    prev_changed = False

    schedules = fetch_schedules()
    current = []
    for s in schedules:
        h = item_hash(s)
        current.append(h)
        if s["kind"] == "schedule":
            old = prev.get(s["date"])
            changes = schedule_changes(old, s["groups"]) if old is not None else None
        else:
            old, changes = None, None
        if h not in seen:
            send(s, changes, old)
            append_history(s)
            print("Надіслано:", s.get("date") or s.get("text", "")[:40])
        if s["kind"] == "schedule" and prev.get(s["date"]) != s["groups"]:
            prev[s["date"]] = s["groups"]
            prev_changed = True

    if prev_changed:
        save_prev(prev)

    if not schedules:
        print("Графіків у відповіді API не знайдено")
    elif set(current) != seen:
        with open(STATE_FILE, "w") as f:
            f.write("\n".join(current) + "\n")
    else:
        print("Змін немає")

    if HC_URL:
        requests.get(HC_URL, timeout=10)


if __name__ == "__main__":
    main()
