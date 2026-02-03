import requests
from bs4 import BeautifulSoup
import json, time, logging, sys, re, threading, os
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from config import (
    COURSES,
    CHECK_INTERVAL_SECONDS,
    NOTIFICATION_METHOD,
    NTFY_TOPIC,
    DISCORD_WEBHOOK_URL,
    LOG_FILE,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, "a"),
    ],
)
log = logging.getLogger()

STATE_FILE = "state.json"

BASE_URL = "https://udapps.nss.udel.edu/CoursesSearch/search-results"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def extract_section_number(code: str) -> str:
    match = re.match(r"[A-Za-z]+(\d+?)(\d{2,3})[A-Za-z]*$", code)
    if match:
        return match.group(2)
    match2 = re.search(r"(\d{2,3})[A-Za-z]*$", code)
    return match2.group(1) if match2 else ""


def load_state():
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def fetch_sections(course_sec: str, term: str) -> list[dict]:
    params = {
        "term": term,
        "search_type": "A",
        "course_sec": course_sec,
        "session": "All",
        "course_title": "",
        "instr_name": "",
        "text_info": "All",
        "campus": "",
        "instrtn_mode": "All",
        "time_start_hh": "",
        "time_start_ampm": "",
        "credit": "Any",
        "keyword": "",
        "geneduc": "",
        "sustainable": "",
        "subj_area_code": "",
        "college": "",
    }

    resp = requests.get(BASE_URL, params=params, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    sections = []
    for row in soup.select("table tr"):
        code_tag = row.select_one("td.course a.coursenum")
        if not code_tag:
            continue

        code = code_tag.get_text(strip=True)
        type_tag = row.select_one("td.course .coursetype")
        sec_type = type_tag.get_text(strip=True) if type_tag else ""

        title_td = row.select("td")[1] if len(row.select("td")) > 1 else None
        title = title_td.get_text(strip=True) if title_td else ""

        seats_td = row.select_one("td.openseats")
        available, capacity, is_full = 0, 0, True
        waitlisted = bool(row.select_one("td.course .label-info"))

        if seats_td:
            seat_match = re.search(r"(\d+)\s+OF\s+(\d+)", seats_td.get_text())
            if seat_match:
                available = int(seat_match.group(1))
                capacity = int(seat_match.group(2))
            is_full = bool(seats_td.select_one(".label-danger"))

        campus_td = row.select_one("td.campus")
        campus = campus_td.get_text(strip=True) if campus_td else ""

        day_td = row.select_one("td.day")
        days = day_td.get_text(strip=True) if day_td else ""
        time_td = row.select_one("td.time")
        time_str = time_td.get_text(strip=True) if time_td else ""

        sections.append({
            "code": code,
            "type": sec_type,
            "title": title,
            "available": available,
            "capacity": capacity,
            "full": is_full,
            "campus": campus,
            "days": days,
            "time": time_str,
            "waitlisted": waitlisted,
        })

    return sections


def send_notification(title: str, body: str, urgent: bool = False):
    if NOTIFICATION_METHOD == "ntfy":
        send_ntfy(title, body, urgent)
    elif NOTIFICATION_METHOD == "discord":
        send_discord(title, body, urgent)


def send_ntfy(title: str, body: str, urgent: bool = False):
    priority = "max" if urgent else "default"
    try:
        requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=body.encode(),
            headers={"Title": title, "Priority": priority},
            timeout=10,
        )
        log.info(f"  [OK] ntfy sent (priority: {priority})")
    except Exception as e:
        log.error(f"  [FAIL] ntfy: {e}")


def send_discord(title: str, body: str, urgent: bool = False):
    payload = {
        "embeds": [{
            "title": ("[PRIORITY] " if urgent else "") + title,
            "description": body,
            "color": 0xFF3333 if urgent else 0x00FF88,
            "timestamp": datetime.now().isoformat(),
        }]
    }
    try:
        requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10)
        log.info(f"  [OK] Discord sent")
    except Exception as e:
        log.error(f"  [FAIL] Discord: {e}")


def keep_alive():
    url = os.environ.get("RENDER_EXTERNAL_URL")
    if not url:
        return
    while True:
        time.sleep(600)
        try:
            requests.get(url, timeout=10)
        except Exception:
            pass


def main():
    log.info("=" * 45)
    log.info("  UD Seat Monitor - started")
    log.info(f"  Watching {len(COURSES)} course(s), checking every {CHECK_INTERVAL_SECONDS}s")
    log.info(f"  Notifications via: {NOTIFICATION_METHOD}")
    log.info("=" * 45)

    state = load_state()

    while True:
        log.info("─" * 40)
        log.info(f"  Checking at {datetime.now().strftime('%I:%M:%S %p')} ...")

        for course in COURSES:
            label = course["label"]
            course_sec = course["course_sec"]
            term = course["term"]
            watch_list = course.get("sections")
            priority_list = course.get("priority", [])

            try:
                sections = fetch_sections(course_sec, term)
            except Exception as e:
                log.error(f"  [FAIL] {label}: {e}")
                continue

            if not sections:
                log.warning(f"  [WARN] No sections found for {label}")
                continue

            for sec in sections:
                sec_num = extract_section_number(sec["code"])

                if watch_list is not None and sec_num not in watch_list:
                    continue

                is_priority = sec_num in priority_list
                key = f"{term}_{sec['code']}"
                prev = state.get(key)

                pri_tag = " [PRIORITY]" if is_priority else ""
                wl_tag = "[WL] " if sec["waitlisted"] else ""
                status = (
                    f"{wl_tag}"
                    f"{sec['available']}/{sec['capacity']} seats"
                    f"{' - FULL' if sec['full'] else ' - OPEN'}"
                    f"{pri_tag}"
                )
                log.info(f"  {sec['code']} ({sec['type']}) {status}")

                if prev is not None and prev["available"] == 0 and sec["available"] > 0:
                    if is_priority:
                        title = f"PRIORITY SEAT OPENED - {sec['code']}"
                    else:
                        title = f"Seat opened - {sec['code']}"

                    body = (
                        f"{sec['title']}\n"
                        f"Section: {sec['code']} ({sec['type']})\n"
                        f"Seats: {sec['available']} of {sec['capacity']} now open\n"
                        f"{sec['days']}  {sec['time']}  {sec['campus']}\n"
                        f"- {datetime.now().strftime('%I:%M %p')}"
                    )
                    log.info(f"  [ALERT] {title}")
                    send_notification(title, body, urgent=is_priority)

                if prev is not None and prev["available"] > 0 and sec["available"] == 0:
                    log.info(f"  [INFO] {sec['code']} filled up again.")

                state[key] = sec

        save_state(state)
        log.info(f"  Next check in {CHECK_INTERVAL_SECONDS}s ...")
        time.sleep(CHECK_INTERVAL_SECONDS)


class _Health(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")
    def log_message(self, *args):
        pass


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    threading.Thread(target=lambda: HTTPServer(("", port), _Health).serve_forever(), daemon=True).start()
    threading.Thread(target=keep_alive, daemon=True).start()
    log.info(f"  Health server on port {port}")
    main()
