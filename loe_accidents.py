import json
import os
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

import loe_bot as bot

API = "https://power-api.loe.lviv.ua/api/pw_accidents"
CITY_ID = os.environ.get("LOE_CITY_ID", "")
OUT_FILE = "accidents.json"
MAX_PAGES = 150
GRACE = timedelta(minutes=30)
KYIV = ZoneInfo("Europe/Kyiv")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (loe-schedule-bot)",
    "Accept": "application/ld+json, application/json;q=0.9",
}

NOTIFY_KINDS = {"emergency", "possible", "gav", "sgav"}
NOTIFY_CITIES = {c.strip() for c in os.environ.get("ACC_CITIES", "").split(",") if c.strip()}
SITE_URL = os.environ.get("SITE_URL", "https://creaturesees.github.io/loebot/#avariini")
KIND_LABEL = {"emergency": "аварійне", "possible": "можливе аварійне", "gav": "ГАВ", "sgav": "СГАВ"}
KIND_ICON = {"emergency": "🔴", "possible": "🟠", "gav": "⛔️", "sgav": "⛔️"}

SUB_REASON = {1: "gav", 2: "gpv", 3: "sgav"}
TYPE_OFF = {0: "planned", 1: "emergency", 2: "switching", 30: "possible"}


def fetch_rows():
    rows = []
    page, retries = 1, 0
    while page <= MAX_PAGES:
        r = requests.get(API, params={
            "page": page, "otg.id": "", "city.id": CITY_ID, "street.id": "",
            "_": int(datetime.now(timezone.utc).timestamp()),
        }, headers=HEADERS, timeout=60)
        if r.status_code == 429 and retries < 3:
            retries += 1
            time.sleep(10 * retries)
            continue
        r.raise_for_status()
        data = r.json()
        if isinstance(data, dict):
            members = data.get("hydra:member") or data.get("member") or []
            has_next = bool((data.get("hydra:view") or data.get("view") or {}).get("hydra:next")
                            or (data.get("view") or {}).get("next"))
        else:
            members = data if isinstance(data, list) else []
            has_next = len(members) >= 30
        rows += members
        if not members or not has_next:
            break
        page += 1
        time.sleep(0.5)
    return rows


def parse_time(v):
    if not v:
        return None
    try:
        t = datetime.fromisoformat(v)
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=KYIV)


def kind_of(row):
    sub = row.get("switchSubReason") or 0
    if sub:
        return SUB_REASON.get(sub, "other")
    return TYPE_OFF.get(row.get("typeOff"), "other")


def houses_of(row):
    return [h.strip() for h in (row.get("buildingNames") or "").split(",")
            if h.strip() and any(ch.isdigit() for ch in h)]


def current(rows, now):
    out = []
    for row in rows:
        start, end = parse_time(row.get("dateEvent")), parse_time(row.get("datePlanIn"))
        if start and start > now:
            continue
        if end and end + GRACE <= now:
            continue
        street = (row.get("street") or {}).get("name") or ""
        city = (row.get("city") or {}).get("name") or ""
        otg = (row.get("otg") or {}).get("name") or ""
        if not street and not city:
            continue
        out.append({
            "id": row.get("id"),
            "city": city.strip(),
            "otg": otg.strip(),
            "street": street.strip(),
            "houses": houses_of(row),
            "from": start.astimezone(KYIV).isoformat() if start else None,
            "to": end.astimezone(KYIV).isoformat() if end else None,
            "kind": kind_of(row),
        })
    out.sort(key=lambda r: (r["city"] != "Львів", r["city"].lower(), r["street"].lower(), r["from"] or ""))
    return out


def load_old():
    try:
        with open(OUT_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def hm(iso):
    if not iso:
        return None
    t = datetime.fromisoformat(iso)
    today = datetime.now(KYIV).date()
    return t.strftime("%H:%M") if t.date() == today else t.strftime("%d.%m %H:%M")


def plural(n):
    if n % 10 == 1 and n % 100 != 11:
        return "адреса"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return "адреси"
    return "адрес"


def notifiable(rows):
    return [r for r in rows if r["kind"] in NOTIFY_KINDS
            and (not NOTIFY_CITIES or r["city"] in NOTIFY_CITIES)]


def format_alert(new, gone, now, f, limit):
    lines = [f.bold("⚠️ Аварійні відключення"),
             f.italic(f"станом на {now.astimezone(KYIV).strftime('%H:%M %d.%m.%Y')}"), ""]
    lines.append(f.bold(f"Нові ({len(new)}):"))
    for r in new[:limit]:
        houses = ", ".join(r["houses"])
        if len(houses) > 120:
            houses = houses[:117].rsplit(",", 1)[0] + "…"
        place = f"{r['city']}, {r['street']}" if r["street"] else r["city"]
        head = f"{KIND_ICON.get(r['kind'], '🔴')} " + f.bold(place) + (f.esc(f": {houses}") if houses else "")
        when = f"з {hm(r['from']) or '—'}" + (f", орієнт. до {hm(r['to'])}" if r["to"] else "")
        if r["kind"] != "emergency":
            when += f" · {KIND_LABEL.get(r['kind'], '')}"
        lines += [head, f.esc(f"   {when}")]
    if len(new) > limit:
        lines.append(f.esc(f"…і ще {len(new) - limit}"))
    if gone:
        lines += ["", f.esc(f"✅ Світло повернули: {len(gone)} {plural(len(gone))}")]
    lines += ["", f.link("📋 Повний список на сайті", SITE_URL),
              "", f'{f.logo("🔗")} {f.link("Підписатись", bot.LINK_SUBSCRIBE)}  | {f.link("💬 Чат", bot.LINK_CHAT)}']
    return "\n".join(lines)


def notify(old_rows, rows, now):
    old_ids = {r.get("id") for r in notifiable(old_rows)}
    cur = notifiable(rows)
    cur_ids = {r.get("id") for r in cur}
    new = [r for r in cur if r.get("id") not in old_ids]
    gone = [r for r in notifiable(old_rows) if r.get("id") not in cur_ids]
    if not new:
        print(f"Аварійні: нових немає (повернули {len(gone)})")
        return
    ok = 0
    if bot.BOT_TOKEN and bot.CHAT_ID:
        ok += bot.send_telegram(format_alert(new, gone, now, bot.TelegramFmt, 15))
    ok += bot.send_discord(format_alert(new, gone, now, bot.DiscordFmt, 7), None,
                           f"нові аварійні відключення ({len(new)})")
    print(f"Аварійні: надіслано про {len(new)} нових, отримувачів: {ok}")


def main():
    now = datetime.now(timezone.utc)
    try:
        rows = current(fetch_rows(), now)
    except Exception as e:
        print(f"Аварійні: не вдалося отримати дані: {e}")
        return
    old = load_old()
    if old.get("rows") == rows:
        print(f"Аварійні: без змін ({len(rows)})")
        return
    if old.get("rows") is not None and os.environ.get("ACC_NOTIFY", "1") != "0":
        try:
            notify(old["rows"], rows, now)
        except Exception as e:
            print(f"Аварійні: не вдалося надіслати: {e}")
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump({"changed": now.astimezone(KYIV).isoformat(timespec="seconds"), "rows": rows},
                  f, ensure_ascii=False, indent=1)
    print(f"Аварійні: оновлено ({len(rows)})")


if __name__ == "__main__":
    main()
