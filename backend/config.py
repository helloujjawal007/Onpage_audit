import os
import json
from pathlib import Path
from typing import Dict, List, Any

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"
DATA_DIR = BASE_DIR / "data"

REPUTABLE_DOMAINS_FILE = CONFIG_DIR / "reputable_domains.json"
BAD_ANCHORS_FILE = CONFIG_DIR / "bad_anchors.json"
SITE_PROFILES_FILE = CONFIG_DIR / "site_profiles.json"
DB_PATH = DATA_DIR / "checklist.db"


def load_reputable_config() -> Dict[str, List[str]]:
    if REPUTABLE_DOMAINS_FILE.exists():
        try:
            with open(REPUTABLE_DOMAINS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "tlds": [".org", ".gov", ".gov.in", ".edu", ".edu.in", ".ac.uk", ".mil"],
        "domains": ["wikipedia.org", "w3.org", "github.com", "who.int", "un.org", "nih.gov", "cdc.gov", "ieee.org"]
    }


def load_bad_anchors() -> List[str]:
    if BAD_ANCHORS_FILE.exists():
        try:
            with open(BAD_ANCHORS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return [
        "here", "there", "this", "read more", "click here", "link",
        "website", "source", "more", "learn more", "check this out", "page"
    ]


def load_default_site_profiles() -> Dict[str, Any]:
    if SITE_PROFILES_FILE.exists():
        try:
            with open(SITE_PROFILES_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}
