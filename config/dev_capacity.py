"""Staff configuration — single source of truth for all team members."""

ALL_STAFF = [
    # ── Development ───────────────────────────────────────────────────────────
    {"name": "Nitesh Bagdi",    "role": "Senior Web Dev",  "team": "Development",  "capacity_h": 180},
    {"name": "Archana Pandey",  "role": "Web Dev",         "team": "Development",  "capacity_h": 180},
    {"name": "Dhananjai Kalra", "role": "Full Stack Dev",  "team": "Development",  "capacity_h": 180},
    {"name": "Arpit Bhardwaj", "role": "Full Stack Dev",  "team": "Development",  "capacity_h": 180},
    {"name": "Rajesh K",        "role": "Senior Dev",      "team": "Development",  "capacity_h": 180},
    {"name": "Pranjal Jindal",  "role": "Web Dev",         "team": "Development",  "capacity_h": 180},
    {"name": "Shivi Prajapati", "role": "Web Dev",         "team": "Development",  "capacity_h": 180},
    {"name": "Mansi Mishra",   "role": "Web Dev",         "team": "Development",  "capacity_h": 180},
    # ── Mobile ────────────────────────────────────────────────────────────────
    {"name": "Dolly Munjal",    "role": "Mobile Dev",      "team": "Mobile",       "capacity_h": 180},
    {"name": "Suraj Gupta",     "role": "Mobile Dev",      "team": "Mobile",       "capacity_h": 180},
    {"name": "Sagar Khurana",   "role": "Mobile Dev",      "team": "Mobile",       "capacity_h": 180},
    {"name": "Jyoti Dahiya",    "role": "Mobile Dev",      "team": "Mobile",       "capacity_h": 180},
    {"name": "Nishtha Arora",   "role": "iOS Dev",         "team": "Mobile",       "capacity_h": 180},
    # ── QA ────────────────────────────────────────────────────────────────────
    {"name": "Chhavi Bhardwaj", "role": "QA",              "team": "QA",           "capacity_h": 180},
    {"name": "Satyarth Singh",  "role": "QA",              "team": "QA",           "capacity_h": 180},
    {"name": "Nancy Rana",      "role": "QA",              "team": "QA",           "capacity_h": 180},
    {"name": "Nitin Singh",     "role": "QA",              "team": "QA",           "capacity_h": 180},
    {"name": "Vineeta Arora",   "role": "QA",              "team": "QA",           "capacity_h": 180},
    {"name": "Mayank Joshi",    "role": "QA",              "team": "QA",           "capacity_h": 180},
    {"name": "Kunal Joshi",     "role": "QA",              "team": "QA",           "capacity_h": 180},
    {"name": "Shubham Negi",    "role": "QA",              "team": "QA",           "capacity_h": 180},
    # ── Design / Video ────────────────────────────────────────────────────────
    {"name": "Furquan Nayyar",  "role": "Designer",        "team": "Design/Video", "capacity_h": 180,
     "ado_id": "furquan.nayyar@expenseondemand.com"},
    {"name": "Kaushik Awasthi", "role": "Designer",        "team": "Design/Video", "capacity_h": 180},
    {"name": "Akarsh Bahl",     "role": "Designer",        "team": "Design/Video", "capacity_h": 180},
    {"name": "Gagandeep Kaur",  "role": "Designer",        "team": "Design/Video", "capacity_h": 180},
    {"name": "Neeraj Kumar",    "role": "Designer",        "team": "Design/Video", "capacity_h": 180},
    # ── Management ────────────────────────────────────────────────────────────
    {"name": "Sunil Nigam",     "role": "Management",      "team": "Management",   "capacity_h": 180},
    {"name": "Arjan Bolwerk",   "role": "Management",      "team": "Management",   "capacity_h": 180},
    {"name": "Siddharth Nigam", "role": "Management",      "team": "Management",   "capacity_h": 180},
    {"name": "Geetika Khanna",  "role": "Management",      "team": "Management",   "capacity_h": 180},
    {"name": "Sunita Nigam",    "role": "Management",      "team": "Management",   "capacity_h": 180},
]

# ── Derived lists ─────────────────────────────────────────────────────────────
DEVELOPERS     = [s for s in ALL_STAFF if s["team"] in ("Development", "Mobile")]
QA_STAFF       = [s for s in ALL_STAFF if s["team"] == "QA"]
DESIGNERS      = [s for s in ALL_STAFF if s["team"] == "Design/Video"]
MANAGEMENT     = [s for s in ALL_STAFF if s["team"] == "Management"]

STAFF_MAP      = {s["name"]: s for s in ALL_STAFF}
DEV_MAP        = {d["name"]: d for d in DEVELOPERS}
DEV_NAMES      = [d["name"] for d in DEVELOPERS]
QA_NAMES       = [s["name"] for s in QA_STAFF]
DESIGNER_NAMES = [s["name"] for s in DESIGNERS]

# Story owners — must match ADO picklist values exactly (Custom.Userstoryowner)
STORY_OWNER_NAMES = ["Geetika", "Chhavi", "Sunil", "Vineeta"]

DEFAULT_CAPACITY_H = 180
