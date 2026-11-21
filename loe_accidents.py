import json
import os
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
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump({"changed": now.astimezone(KYIV).isoformat(timespec="seconds"), "rows": rows},
                  f, ensure_ascii=False, indent=1)
    print(f"Аварійні: оновлено ({len(rows)})")


if __name__ == "__main__":
    main()
