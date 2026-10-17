"""
Бот графіків відключень Львівобленерго для GitHub Actions.
Один запуск = одна перевірка. Якщо з'явився новий/оновлений графік —
надсилає повідомлення і оновлює last_hash.txt (workflow комітить його назад).

Змінні середовища (GitHub → Settings → Secrets and variables → Actions):
  BOT_TOKEN — токен від @BotFather
  CHAT_ID   — chat id отримувачів через кому, напр. 111111,222222 (або @канал)
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

# Посилання внизу поста. Порожній рядок = текст без посилання.
LINK_GROUP = "https://t.me/lvivpoweroutage/1321"      # «Як дізнатися свою групу відключень?»
LINK_SUBSCRIBE = "https://t.me/lvivpoweroutage/"  # «Підписатись»
LINK_CHAT = "https://t.me/+YI1JiVsa6hNmODky"       # «Чат»

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


def esc(t):
    return html.escape(t, quote=False)


def link(text, url):
    return f'<a href="{html.escape(url)}">{esc(text)}</a>' if url else esc(text)


def format_post(s):
    if s["kind"] == "text":
        return "<b>⚡️ Львівобленерго</b>\n\n" + esc(s["text"])

    d = datetime.strptime(s["date"], "%d.%m.%Y")
    lines = [
        "<b>⏱️ Графік погодинних відключень</b>",
        f"<b>{WEEKDAYS[d.weekday()]}, {d.day} {MONTHS[d.month - 1]} {d.year}</b>",
        "",
    ]
    if s["updated"]:
        lines += [f"<i>Інформація станом на {esc(s['updated'])}</i>", ""]

    blocks = []
    for group in sorted(s["groups"], key=lambda g: tuple(map(int, g.split(".")))):
        block = [f"Група {group}"]
        intervals = s["groups"][group]
        if intervals:
            for start, end in intervals:
                block.append(f"{start} — {end} ({duration(start, end)})")
        else:
            block.append("Відключень немає ✅")
        blocks.append("\n".join(f"<code>{line}</code>" for line in block))
    lines.append("<blockquote>" + "\n\n".join(blocks) + "</blockquote>")
    lines.append("")

    lines += [
        "Надсилай рідним та друзям, щоб вони могли спланувати свій час.",
        link("❗️ Як дізнатися свою групу відключень?", LINK_GROUP),
        "",
        f'{link("🔗 Підписатись", LINK_SUBSCRIBE)}  | {link("💬 Чат", LINK_CHAT)}',
    ]
    return "\n".join(lines)


def item_hash(s):
    return hashlib.sha256(json.dumps(s, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def send(text):
    """Надсилає всім отримувачам з CHAT_ID (через кому)."""
    chat_ids = [c.strip() for c in CHAT_ID.split(",") if c.strip()]
    ok = 0
    for chat_id in chat_ids:
        r = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML",
                  "disable_web_page_preview": True},
            timeout=30,
        )
        if r.ok:
            ok += 1
        else:
            # напр. людина не натиснула Start або заблокувала бота
            print(f"Не вдалося надіслати {chat_id}: {r.status_code} {r.text[:200]}")
    if chat_ids and ok == 0:
        raise RuntimeError("Не вдалося надіслати жодному отримувачу")


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
