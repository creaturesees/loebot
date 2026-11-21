import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

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
    cities = {(m.get("city") or {}).get("name") for m in rows}
    print(f"Аварійні: сторінок {page}, записів {len(rows)}, населених пунктів {len(cities)}")
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
            "comment": " ".join((row.get("koment") or "").split())[:200],
        })
    out = merge(out)
    out.sort(key=lambda r: (r["city"] != "Львів", r["city"].lower(), r["street"].lower(), r["from"] or ""))
    return out


def house_key(h):
    m = re.match(r"(\d+)(.*)", h)
    return (int(m.group(1)), m.group(2)) if m else (10 ** 9, h)


def merge(rows):
    seen, groups = set(), {}
    for r in rows:
        if r["id"] is not None:
            if r["id"] in seen:
                continue
            seen.add(r["id"])
        key = (r["city"], r["otg"], r["street"], r["kind"], r["from"], r["to"])
        g = groups.get(key)
        if g is None:
            groups[key] = dict(r, houses=list(r["houses"]))
            continue
        g["houses"] += [h for h in r["houses"] if h not in g["houses"]]
        if r["comment"] and r["comment"] not in g["comment"]:
            g["comment"] = f"{g['comment']}; {r['comment']}" if g["comment"] else r["comment"]
        g["id"] = min(x for x in (g["id"], r["id"]) if x is not None) if (g["id"] or r["id"]) else None
    for g in groups.values():
        g["houses"] = sorted(set(g["houses"]), key=house_key)
        g["comment"] = g["comment"][:200]
    return list(groups.values())


def load_old():
    try:
        with open(OUT_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


NOTIFY_KINDS = {"emergency", "possible", "gav", "sgav", "planned"}
CHANNEL = os.environ.get("SOSCHANNEL_ID", "").strip()
CHANNEL_CITIES = {c.strip() for c in os.environ.get("ACC_CHANNEL_CITIES", "").split(",") if c.strip()}
POSTED_FILE = "acc_posted.txt"


def channel_caption(now, f, empty):
    import loe_bot as bot
    lines = [f.bold("⚠️ Аварійні відключення"),
             f.italic(f"станом на {now.astimezone(KYIV).strftime('%H:%M %d.%m.%Y')}")]
    if empty:
        lines += ["", f.esc("Зараз аварійних і планових відключень немає ✅")]
    lines += ["", *bot.footer(f)]
    return "\n".join(lines)


def send_album(images, caption):
    import loe_bot as bot
    silent = {"disable_notification": "true"} if bot.quiet_hours() else {}
    for start in range(0, len(images), 10):
        chunk = images[start:start + 10]
        cap = caption if start == 0 else ""
        if len(chunk) == 1:
            data = {"chat_id": CHANNEL, **silent}
            if cap:
                data.update(caption=cap, parse_mode="HTML")
            r = bot.tg_call("sendPhoto", data, {"photo": ("avariini.png", chunk[0], "image/png")})
        else:
            media = [{"type": "photo", "media": f"attach://p{i}"} for i in range(len(chunk))]
            if cap:
                media[0].update(caption=cap, parse_mode="HTML")
            files = {f"p{i}": (f"avariini_{start + i + 1}.png", b, "image/png") for i, b in enumerate(chunk)}
            r = bot.tg_call("sendMediaGroup", {"chat_id": CHANNEL, "media": json.dumps(media), **silent}, files)
        if not r.ok:
            raise RuntimeError(f"{r.status_code} {r.text[:200]}")


def post_channel(rows, now):
    import hashlib
    import loe_bot as bot
    from loe_image import render_accidents
    if not CHANNEL or not bot.BOT_TOKEN:
        return
    rows = [r for r in rows if r["kind"] in NOTIFY_KINDS and (not CHANNEL_CITIES or r["city"] in CHANNEL_CITIES)]
    digest = hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest() if rows else "empty"
    try:
        last = open(POSTED_FILE).read().strip()
    except OSError:
        last = ""
    if digest == last:
        print("Канал: без змін")
        return
    if rows:
        images = render_accidents(rows, datetime.now(KYIV).strftime("%Y-%m-%d"))
        caption = channel_caption(now, bot.TelegramFmt, False)
        try:
            send_album(images, caption)
        except RuntimeError:
            send_album(images, bot.plain_emoji(caption))
    else:
        text = channel_caption(now, bot.TelegramFmt, True)
        data = {"chat_id": CHANNEL, "text": text, "parse_mode": "HTML", "disable_web_page_preview": "true"}
        if not bot.tg_call("sendMessage", data).ok:
            data["text"] = bot.plain_emoji(text)
            bot.tg_call("sendMessage", data)
    with open(POSTED_FILE, "w") as f:
        f.write(digest)
    print(f"Канал: надіслано ({len(rows)} записів)")


def main():
    now = datetime.now(timezone.utc)
    try:
        rows = current(fetch_rows(), now)
    except Exception as e:
        print(f"Аварійні: не вдалося отримати дані: {e}")
        return
    try:
        post_channel(rows, now)
    except Exception as e:
        print(f"Канал: не вдалося надіслати: {e}")
    old = load_old()
    if old.get("rows") == rows:
        print(f"Аварійні: без змін ({len(rows)})")
        return
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump({"changed": now.astimezone(KYIV).isoformat(timespec="seconds"), "rows": rows},
                  f, ensure_ascii=False, indent=1)
    print(f"Аварійні: оновлено ({len(rows)})")


if __name__ == "__main__":
    main()
