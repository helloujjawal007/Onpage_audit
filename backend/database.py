import sqlite3
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
from backend.config import DB_PATH, load_default_site_profiles

DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    cursor = conn.cursor()
    
    # 1. Site profiles table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS site_profiles (
            domain TEXT PRIMARY KEY,
            profile_json TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # 2. Sitemap crawl cache table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sitemap_cache (
            site_domain TEXT NOT NULL,
            page_url TEXT NOT NULL,
            out_links_json TEXT NOT NULL,
            last_scanned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (site_domain, page_url)
        )
    """)
    
    # 3. Check history table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS check_history (
            id TEXT PRIMARY KEY,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            site_url TEXT NOT NULL,
            page_url TEXT NOT NULL,
            keyword TEXT NOT NULL,
            overall_pass INTEGER NOT NULL,
            result_json TEXT NOT NULL
        )
    """)
    
    conn.commit()
    
    # Seed default profiles if table is empty
    cursor.execute("SELECT COUNT(*) FROM site_profiles")
    if cursor.fetchone()[0] == 0:
        defaults = load_default_site_profiles()
        for domain, profile in defaults.items():
            cursor.execute(
                "INSERT OR REPLACE INTO site_profiles (domain, profile_json, updated_at) VALUES (?, ?, ?)",
                (domain, json.dumps(profile), datetime.utcnow().isoformat())
            )
        conn.commit()
        
    conn.close()


def save_site_profile(domain: str, profile_data: Dict[str, Any]):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR REPLACE INTO site_profiles (domain, profile_json, updated_at) VALUES (?, ?, ?)",
        (domain.lower(), json.dumps(profile_data), datetime.utcnow().isoformat())
    )
    conn.commit()
    conn.close()


def get_site_profile(domain: str) -> Optional[Dict[str, Any]]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT profile_json FROM site_profiles WHERE domain = ?", (domain.lower(),))
    row = cursor.fetchone()
    conn.close()
    if row:
        return json.loads(row["profile_json"])
    return None


def get_all_site_profiles() -> Dict[str, Dict[str, Any]]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT domain, profile_json FROM site_profiles ORDER BY domain ASC")
    rows = cursor.fetchall()
    conn.close()
    return {row["domain"]: json.loads(row["profile_json"]) for row in rows}


def save_page_crawl(site_domain: str, page_url: str, out_links: List[str]):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT OR REPLACE INTO sitemap_cache (site_domain, page_url, out_links_json, last_scanned_at)
        VALUES (?, ?, ?, ?)
        """,
        (site_domain.lower(), page_url, json.dumps(out_links), datetime.utcnow().isoformat())
    )
    conn.commit()
    conn.close()


def get_cached_pages_for_site(site_domain: str, max_age_hours: int = 24) -> List[Dict[str, Any]]:
    """Returns all cached crawled pages for a given site if scanned within max_age_hours."""
    conn = get_db()
    cursor = conn.cursor()
    # SQLite datetime calculation
    cursor.execute(
        """
        SELECT page_url, out_links_json, last_scanned_at
        FROM sitemap_cache
        WHERE site_domain = ?
          AND datetime(last_scanned_at) >= datetime('now', ? || ' hours')
        """,
        (site_domain.lower(), f"-{max_age_hours}")
    )
    rows = cursor.fetchall()
    conn.close()
    
    results = []
    for r in rows:
        results.append({
            "page_url": r["page_url"],
            "out_links": json.loads(r["out_links_json"]),
            "last_scanned_at": r["last_scanned_at"]
        })
    return results


def save_check_history(record_id: str, site_url: str, page_url: str, keyword: str, overall_pass: bool, result_dict: Dict[str, Any]):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT OR REPLACE INTO check_history (id, created_at, site_url, page_url, keyword, overall_pass, result_json)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (record_id, datetime.utcnow().isoformat(), site_url, page_url, keyword, 1 if overall_pass else 0, json.dumps(result_dict))
    )
    conn.commit()
    conn.close()


def get_check_history(limit: int = 30) -> List[Dict[str, Any]]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, created_at, site_url, page_url, keyword, overall_pass
        FROM check_history
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (limit,)
    )
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_check_by_id(record_id: str) -> Optional[Dict[str, Any]]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT result_json FROM check_history WHERE id = ?", (record_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return json.loads(row["result_json"])
    return None
