"""
Бот графіків відключень Львівобленерго для GitHub Actions.
Один запуск = одна перевірка. Якщо з'явився новий/оновлений графік —
надсилає повідомлення і оновлює last_hash.txt (workflow комітить його назад).

Змінні середовища (GitHub → Settings → Secrets and variables → Actions):
  BOT_TOKEN — токен від @BotFather
  CHAT_ID   — твій особистий chat id (пізніше можна замінити на @канал)
  HC_URL    — (необов'язково) пінг-URL з healthchecks.io
"""
import hashlib
import html
import json
import os
import re
from datetime import datetime

import requests

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
CHAT_ID = os.environ.get("CHAT_ID", "")
HC_URL = os.environ.get("HC_URL", "")
STATE_FILE = "last_hash.txt"

API_URL = "https://api.loe.lviv.ua/api/menus?page=1&type=photo-grafic"
HEADERS = {"User-Agent": "Mozilla/5.0 (loe-schedule-bot)"}

WEEKDAYS = ["Понеділок", "Вівторок", "Середа", "Четвер", "П'ятниця", "Субота", "Неділя"]
MONTHS = ["січня", "лютого", "березня", "квітня", "травня", "червня",
          "липня", "серпня", "вересня", "жовтня", "листопада", "грудня"]

RE_DATE = re.compile(r"Графік погодинних відключень на (\d{2}\.\d{2}\.\d{4})")
RE_UPDATED = re.compile(r"Інформація станом на (\d{2}:\d{2} \d{2}\.\d{2}\.\d{4})")
RE_GROUP = re.compile(r"Група (\d\.\d)\.\s*(.+)")
RE_INTERVAL = re.compile(r"з (\d{2}:\d{2}) до (\d{2}:\d{2})")


def html_to_lines(raw):
    text = re.sub(r"<[^>]+>", "\n", raw)
    text = html.unescape(text)
    return [line.strip() for line in text.splitlines() if line.strip()]


def parse_schedule(raw_html):
    """Розбирає rawHtml одного графіка у словник."""
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
            groups[m.group(1)] = RE_INTERVAL.findall(m.group(2))  # [] = світло є

    return {
        "date": date.group(1),
        "updated": updated.group(1) if updated else "",
        "groups": groups,
    }


def fetch_schedules():
    """Повертає список актуальних графіків (сьогодні, а інколи й завтра)."""
    r = requests.get(API_URL, headers=HEADERS, timeout=60)
    r.raise_for_status()
    data = r.json()

    result = []
    for menu in data.get("hydra:member", []):
        for item in menu.get("menuItems", []):
            if item.get("children"):          # це архів — пропускаємо
                continue
            raw = item.get("rawHtml") or ""
            if raw:
                s = parse_schedule(raw)
                if s:
                    result.append({"kind": "schedule", **s})
            elif item.get("description"):     # напр. повідомлення про скасування ГПВ
                result.append({"kind": "text", "text": item["description"].strip()})
    return result


def to_minutes(t):
    h, m = map(int, t.split(":"))
    return h * 60 + m  # "24:00" -> 1440


def duration(start, end):
    h, m = divmod(to_minutes(end) - to_minutes(start), 60)
    if h and m:
        return f"{h} год {m} хв"
    return f"{h} год" if h else f"{m} хв"


def format_post(s):
    if s["kind"] == "text":
        return "⚡️ Львівобленерго\n\n" + s["text"]

    d = datetime.strptime(s["date"], "%d.%m.%Y")
    lines = [
        "⏱️ Графік погодинних відключень",
        f"{WEEKDAYS[d.weekday()]}, {d.day} {MONTHS[d.month - 1]} {d.year}",
        "",
    ]
    if s["updated"]:
        lines += [f"Інформація станом на {s['updated']}", ""]

    for group in sorted(s["groups"], key=lambda g: tuple(map(int, g.split(".")))):
        lines.append(f"Група {group}")
        intervals = s["groups"][group]
        if intervals:
            for start, end in intervals:
                lines.append(f"{start} — {end} ({duration(start, end)})")
        else:
            lines.append("Відключень немає ✅")
        lines.append("")

    lines += [
        "Надсилай рідним та друзям, щоб вони могли спланувати свій час",
        "",
        "🔗 Підписатись  | 💬 Чат",
    ]
    return "\n".join(lines)


def item_hash(s):
    return hashlib.sha256(json.dumps(s, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def send(text):
    requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": text, "disable_web_page_preview": True},
        timeout=30,
    ).raise_for_status()


def main():
    seen = set()
    if os.path.exists(STATE_FILE):
        seen = {line.strip() for line in open(STATE_FILE) if line.strip()}

    schedules = fetch_schedules()
    current = []
    for s in schedules:
        h = item_hash(s)
        current.append(h)
        if h not in seen:
            send(format_post(s))
            print("Надіслано:", s.get("date") or s.get("text", "")[:40])

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
