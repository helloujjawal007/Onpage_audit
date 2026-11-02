import io
import csv
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from pathlib import Path

from backend.database import (
    init_db,
    save_site_profile,
    get_site_profile,
    get_all_site_profiles,
    get_check_history,
    get_check_by_id
)
from backend.models import CheckRequest, CheckResponse, SiteProfile
from backend.checker import run_full_check
from backend.utils import clean_domain

# Initialize database on startup
init_db()

app = FastAPI(
    title="SEO Link & Keyword Checker Tool",
    description="Automated SEO checklist validator for internal/external links, keyword presence, and KD.",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


@app.post("/api/check", response_model=CheckResponse)
async def check_page(request: CheckRequest):
    """
    Runs full SEO link & keyword audit according to the build spec:
    - Domain match validation
    - Rule #0 Live gate check
    - Check A: New tab (target="_blank" + noopener)
    - Check B: Nofollow / Dofollow
    - Check C: Internal linking (C1 outgoing, C2 incoming 5+, C3 product page link, C4 bad anchors, C5 duplicates)
    - Check D: Keyword KD + On-page presence
    """
    try:
        response = await run_full_check(request)
        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Check failed: {str(e)}")


@app.get("/api/profiles")
async def list_profiles():
    """Returns saved site profiles."""
    return get_all_site_profiles()


@app.post("/api/profiles")
async def update_profile(profile: SiteProfile):
    """Saves or updates a site configuration profile."""
    domain = clean_domain(profile.site_url.replace("https://", "").replace("http://", "").split("/")[0])
    if not domain:
        raise HTTPException(status_code=400, detail="Invalid site URL")
        
    save_site_profile(domain, profile.model_dump())
    return {"status": "success", "domain": domain, "message": "Site profile saved successfully"}


@app.get("/api/history")
async def history(limit: int = Query(25, ge=1, le=100)):
    """Returns list of recent checks."""
    return get_check_history(limit=limit)


@app.get("/api/check/{check_id}")
async def get_check(check_id: str):
    """Fetches details of a specific past audit."""
    result = get_check_by_id(check_id)
    if not result:
        raise HTTPException(status_code=404, detail="Check report not found")
    return result


@app.get("/api/export/{check_id}/csv")
async def export_csv(check_id: str):
    """Generates a downloadable CSV audit report."""
    data = get_check_by_id(check_id)
    if not data:
        raise HTTPException(status_code=404, detail="Check report not found")

    output = io.StringIO()
    writer = csv.writer(output)

    # Header metadata
    writer.writerow(["SEO LINK & KEYWORD AUDIT REPORT"])
    writer.writerow(["Audit ID", data.get("id")])
    writer.writerow(["Timestamp", data.get("timestamp")])
    writer.writerow(["Site URL", data.get("site_url")])
    writer.writerow(["Page URL", data.get("page_url")])
    writer.writerow(["Primary Keyword", data.get("primary_keyword")])
    writer.writerow(["KD Score", f"{data.get('check_d_kd', {}).get('kd', 'N/A')} ({data.get('check_d_kd', {}).get('source', '')})"])
    writer.writerow(["Search Volume", data.get("check_d_kd", {}).get("volume", "N/A")])
    writer.writerow(["Live Gate Status", f"{data.get('live_gate', {}).get('status_code')} ({'LIVE' if data.get('live_gate', {}).get('is_live') else 'FAILED'})"])
    writer.writerow(["Overall Result", "PASS" if data.get("overall_pass") else "FAIL"])
    writer.writerow([])

    # Checks summary table
    writer.writerow(["CHECKLIST SUMMARY"])
    writer.writerow(["Check ID", "Check Name", "Status", "Summary Details"])
    checks = [
        ("A", data.get("check_a_new_tab", {})),
        ("B", data.get("check_b_follow", {})),
        ("C1", data.get("check_c1_internal_outgoing", {})),
        ("C2", data.get("check_c2_incoming_links", {})),
        ("C3", data.get("check_c3_product_link", {})),
        ("C4", data.get("check_c4_anchor_quality", {})),
        ("C5", data.get("check_c5_duplicates", {})),
        ("D", {"name": "D. Keyword & On-page", "status": data.get("check_d_onpage", {}).get("status", "N/A"), "summary": f"Density: {data.get('check_d_onpage', {}).get('keyword_density')}% | Words: {data.get('check_d_onpage', {}).get('total_words')}"})
    ]
    for cid, c in checks:
        writer.writerow([cid, c.get("name"), c.get("status"), c.get("summary")])
    writer.writerow([])

    # Failed issues table
    failed_issues = data.get("failed_issues", [])
    writer.writerow(["ACTIONABLE ISSUES & FIXES"])
    writer.writerow(["Link URL", "Anchor Text", "Problem", "Suggested Fix"])
    if failed_issues:
        for issue in failed_issues:
            writer.writerow([
                issue.get("link", ""),
                issue.get("anchor", ""),
                issue.get("problem", ""),
                issue.get("fix", "")
            ])
    else:
        writer.writerow(["None", "None", "No issues found! All checks passed.", "None"])
    writer.writerow([])

    # Detailed Link Inventory
    writer.writerow(["COMPLETE LINK INVENTORY"])
    writer.writerow(["Type", "Destination URL", "Anchor Text", "Target Blank", "Rel Tags", "Actual Follow", "Expected Follow", "Duplicate", "Bad Anchor"])
    for l in data.get("all_links", []):
        writer.writerow([
            "External" if l.get("is_external") else ("Product" if l.get("is_product_page") else "Internal"),
            l.get("href"),
            l.get("anchor"),
            "Yes" if l.get("new_tab") else "No (FAIL)",
            " ".join(l.get("rel_tags", [])),
            l.get("actual_follow"),
            l.get("expected_follow") or "N/A",
            "Yes" if l.get("duplicate") else "No",
            "Yes" if l.get("bad_anchor") else "No"
        ])

    output.seek(0)
    filename = f"seo-report-{clean_domain(data.get('site_url'))}-{check_id[:8]}.csv"
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode("utf-8-sig")),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


# Mount static assets for frontend UI
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

    @app.get("/")
    async def serve_index():
        return FileResponse(str(FRONTEND_DIR / "index.html"))
