"""Developer capacity configuration — name, role, monthly hours."""

DEVELOPERS = [
    {"name": "Nitesh Bagdi",     "role": "Senior Web Dev",  "capacity_h": 180, "team": "Development"},
    {"name": "Archana Pandey",   "role": "Web Dev",         "capacity_h": 180, "team": "Development"},
    {"name": "Dhananjai Kalra",  "role": "Full Stack Dev",  "capacity_h": 180, "team": "Development"},
    {"name": "Arpit Bhardwaj",   "role": "Full Stack Dev",  "capacity_h": 180, "team": "Development"},
    {"name": "Rajesh K",         "role": "Senior Dev",      "capacity_h": 180, "team": "Development"},
    {"name": "Pranjal Jindal",   "role": "Web Dev",         "capacity_h": 180, "team": "Development"},
    {"name": "Shivi Prajapati",  "role": "Web Dev",         "capacity_h": 180, "team": "Development"},
    {"name": "Dolly Munjal",     "role": "Mobile Dev",      "capacity_h": 180, "team": "Mobile"},
    {"name": "Sagar Khurana",    "role": "Mobile Dev",      "capacity_h": 180, "team": "Mobile"},
    {"name": "Jyoti Dahiya",     "role": "Mobile Dev",      "capacity_h": 180, "team": "Mobile"},
    {"name": "Nishtha Arora",    "role": "iOS Dev",         "capacity_h": 180, "team": "Mobile"},
]

DEV_MAP   = {d["name"]: d for d in DEVELOPERS}
DEV_NAMES = [d["name"] for d in DEVELOPERS]
DEFAULT_CAPACITY_H = 180
