import pytest
from bs4 import BeautifulSoup

from backend.utils import (
    normalize_url,
    is_internal_url,
    is_reputable_external,
    check_anchor_quality,
    clean_domain
)
from backend.checker import validate_domains, evaluate_onpage_keyword, extract_article_body


def test_domain_validation():
    site = "https://signeasy.com"
    page = "https://signeasy.com/blog/business/is-docusign-free"
    subdomains = ["app.signeasy.com", "pages.signeasy.com"]
    
    # 1. Valid matching page
    ok, err = validate_domains(site, page, subdomains)
    assert ok is True
    assert err == ""
    
    # 2. Valid subdomain
    sub_page = "https://pages.signeasy.com/features"
    ok, err = validate_domains(site, sub_page, subdomains)
    assert ok is True
    
    # 3. Invalid foreign domain
    foreign_page = "https://docusign.com/blog/business/is-docusign-free"
    ok, err = validate_domains(site, foreign_page, subdomains)
    assert ok is False
    assert "Ye page is site ka nahi hai" in err


def test_url_normalization():
    base = "https://signeasy.com/blog/test"
    
    # Resolves relative URL
    assert normalize_url("/pricing", base_url=base) == "https://signeasy.com/pricing"
    
    # Strips UTM params and fragments
    dirty = "https://signeasy.com/blog/post?utm_source=twitter&utm_medium=social&ref=seo#top"
    cleaned = normalize_url(dirty)
    assert "utm_source" not in cleaned
    assert "utm_medium" not in cleaned
    assert "#top" not in cleaned
    assert cleaned == "https://signeasy.com/blog/post?ref=seo"
    
    # Trailing slash consistency
    assert normalize_url("https://signeasy.com/features/") == "https://signeasy.com/features"


def test_anchor_quality():
    bad_list = ["here", "there", "this", "read more", "click here", "link"]
    
    # Generic anchors
    bad, reason = check_anchor_quality("click here", "https://example.com", bad_list)
    assert bad is True
    assert "Generic anchor" in reason
    
    bad, reason = check_anchor_quality("Here", "https://example.com", bad_list)
    assert bad is True
    
    # Naked link
    bad, reason = check_anchor_quality("https://example.com/pricing", "https://example.com/pricing", bad_list)
    assert bad is True
    assert "Naked link" in reason
    
    # Empty anchor
    bad, reason = check_anchor_quality("   ", "https://example.com", bad_list)
    assert bad is True
    assert "Empty" in reason
    
    # Good descriptive anchor
    bad, reason = check_anchor_quality("eSignature compliance standards", "https://example.com", bad_list)
    assert bad is False
    assert reason is None


def test_reputable_external():
    config = {
        "tlds": [".org", ".gov", ".edu"],
        "domains": ["wikipedia.org", "w3.org"]
    }
    
    assert is_reputable_external("who.int", config) is False  # not in config
    assert is_reputable_external("redcross.org", config) is True
    assert is_reputable_external("irs.gov", config) is True
    assert is_reputable_external("harvard.edu", config) is True
    assert is_reputable_external("en.wikipedia.org", config) is True
    assert is_reputable_external("randomcommercialsite.com", config) is False


def test_article_body_extraction():
    html = """
    <html>
      <header><a href="https://signeasy.com/login">Login Header</a></header>
      <nav><a href="https://signeasy.com/nav">Nav Item</a></nav>
      <article>
        <h1>Article Title</h1>
        <p>This is the blog text with a <a href="https://signeasy.com/body-link">body link</a>.</p>
      </article>
      <footer><a href="https://signeasy.com/privacy">Privacy Footer</a></footer>
    </html>
    """
    soup = BeautifulSoup(html, "lxml")
    body = extract_article_body(soup)
    links = [a.get("href") for a in body.find_all("a")]
    
    assert "https://signeasy.com/body-link" in links
    assert "https://signeasy.com/login" not in links
    assert "https://signeasy.com/privacy" not in links


def test_onpage_keyword():
    html = """
    <html>
      <body>
        <article>
          <h1>Is DocuSign Free? Complete Guide</h1>
          <p>Many users wonder if is docusign free when signing documents online.</p>
          <h2>Is DocuSign Free for Personal Use?</h2>
          <p>DocuSign offers a 30-day trial but is not completely free forever.</p>
        </article>
      </body>
    </html>
    """
    soup = BeautifulSoup(html, "lxml")
    body = soup.find("article")
    kw = "is docusign free"
    page_url = "https://signeasy.com/blog/is-docusign-free"
    
    res = evaluate_onpage_keyword(soup, body, page_url, kw)
    assert res.in_slug is True
    assert res.h1_count == 1
    assert res.h1_has_keyword is True
    assert res.h2_has_keyword is True
    assert res.first_p_has_keyword is True
    assert res.status == "PASS"
