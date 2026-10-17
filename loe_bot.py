"""
Бот графіків відключень Львівобленерго для GitHub Actions.
Один запуск = одна перевірка. Якщо графік змінився — надсилає повідомлення
і оновлює last_hash.txt (workflow комітить його назад у репозиторій).

Змінні середовища (GitHub → Settings → Secrets and variables → Actions):
  BOT_TOKEN — токен від @BotFather
  CHAT_ID   — твій особистий chat id (пізніше можна замінити на @канал)
  HC_URL    — (необов'язково) пінг-URL з healthchecks.io
"""
import hashlib
import json
import os
from datetime import datetime

import requests

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]
HC_URL = os.environ.get("HC_URL", "")
STATE_FILE = "last_hash.txt"

# Встав сюди URL, знайдений у DevTools → Network → Fetch/XHR
API_URL = "https://api.loe.lviv.ua/..."

WEEKDAYS = ["Понеділок", "Вівторок", "Середа", "Четвер", "П'ятниця", "Субота", "Неділя"]
MONTHS = ["січня", "лютого", "березня", "квітня", "травня", "червня",
          "липня", "серпня", "вересня", "жовтня", "листопада", "грудня"]


def fetch_schedule():
    """
    TODO: адаптуй під реальну відповідь API.
    Має повернути:
    {
        "date": "17.10.2026",
        "updated": "10:59 17.10.2026",
        "groups": {
            "1.1": [("20:00", "22:30")],
            "4.2": [("10:00", "12:00"), ("21:00", "22:30")],
        }
    }
    """
    r = requests.get(API_URL, timeout=30)
    r.raise_for_status()
    data = r.json()
    # ... розбір data ...
    raise NotImplementedError("Додай парсинг відповіді API")


def to_minutes(t):
    h, m = map(int, t.split(":"))
    return h * 60 + m  # "24:00" -> 1440


def duration(start, end):
    h, m = divmod(to_minutes(end) - to_minutes(start), 60)
    if h and m:
        return f"{h} год {m} хв"
    return f"{h} год" if h else f"{m} хв"


def format_post(s):
    d = datetime.strptime(s["date"], "%d.%m.%Y")
    lines = [
        "⏱️ Графік погодинних відключень",
        f"{WEEKDAYS[d.weekday()]}, {d.day} {MONTHS[d.month - 1]} {d.year}",
        "",
        f"Інформація станом на {s['updated']}",
        "",
    ]
    for group in sorted(s["groups"], key=lambda g: tuple(map(int, g.split(".")))):
        lines.append(f"Група {group}")
        for start, end in s["groups"][group]:
            lines.append(f"{start} — {end} ({duration(start, end)})")
        lines.append("")
    lines += [
        "Надсилай рідним та друзям, щоб вони могли спланувати свій час",
        "",
        "🔗 Підписатись  | 💬 Чат",
    ]
    return "\n".join(lines)


def send(text):
    requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": text, "disable_web_page_preview": True},
        timeout=30,
    ).raise_for_status()


def main():
    last = open(STATE_FILE).read().strip() if os.path.exists(STATE_FILE) else ""

    s = fetch_schedule()
    h = hashlib.sha256(json.dumps(s, sort_keys=True).encode()).hexdigest()

    if h != last:
        send(format_post(s))
        with open(STATE_FILE, "w") as f:
            f.write(h)
        print("Графік змінився — повідомлення надіслано")
    else:
        print("Змін немає")

    if HC_URL:
        requests.get(HC_URL, timeout=10)


if __name__ == "__main__":
    main()
