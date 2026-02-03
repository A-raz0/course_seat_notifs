COURSES = [
    {
        "label": "PHYS228 - Fundamentals of Physics Lab II",
        "course_sec": "phys228",
        "term": "2263", #change every sem
        "sections": ["040", "041", "042"],
        "priority": ["042"],
    },
        {
        "label": "ENGL410 - Technical Writing",
        "course_sec": "engl410",
        "term": "2263",
        "sections": ["012", "013", "014", "015", "016"],
        "priority": ["013"],
    },
]


CHECK_INTERVAL_SECONDS = 180

NOTIFICATION_METHOD = "ntfy"

NTFY_TOPIC = "ud-seat-alert-raza"

DISCORD_WEBHOOK_URL = "" #use if want discord notifs

LOG_FILE = "monitor.log"
