import pytest
from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app)


def test_list_profiles():
    response = client.get("/api/profiles")
    assert response.status_code == 200
    data = response.json()
    assert "signeasy.com" in data
    assert data["signeasy.com"]["product_page_url"] == "https://signeasy.com/electronic-signature-software"


def test_update_profile():
    new_profile = {
        "site_url": "https://example.com",
        "product_page_url": "https://example.com/product",
        "product_anchor_keywords": ["best product"],
        "internal_subdomains": ["app.example.com"],
        "country": "us"
    }
    response = client.post("/api/profiles", json=new_profile)
    assert response.status_code == 200
    
    profiles = client.get("/api/profiles").json()
    assert "example.com" in profiles


def test_domain_mismatch_check():
    payload = {
        "site_url": "https://signeasy.com",
        "page_url": "https://competitor.com/blog/article",
        "primary_keyword": "online signatures",
        "country": "us"
    }
    response = client.post("/api/check", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["overall_pass"] is False
    assert data["live_gate"]["is_live"] is False
    assert "Ye page is site ka nahi hai" in data["live_gate"]["message"]


def test_history_and_csv_export():
    history_resp = client.get("/api/history")
    assert history_resp.status_code == 200
    items = history_resp.json()
    assert len(items) > 0
    first_id = items[0]["id"]
    
    # Export CSV
    csv_resp = client.get(f"/api/export/{first_id}/csv")
    assert csv_resp.status_code == 200
    assert "text/csv" in csv_resp.headers["content-type"]
    assert "SEO LINK & KEYWORD AUDIT REPORT" in csv_resp.text
