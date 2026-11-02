import pytest
from bs4 import BeautifulSoup

from backend.phase2 import (
    calculate_pixel_width,
    evaluate_title_and_meta,
    evaluate_heading_hierarchy,
    evaluate_images,
    evaluate_schema_structured_data,
    evaluate_faq_section,
    evaluate_key_takeaways
)


def test_calculate_pixel_width():
    title = "Is DocuSign Free? Complete 2026 Guide"
    px = calculate_pixel_width(title, is_title=True)
    assert 250 < px < 500


def test_title_and_meta():
    html_good = """
    <html>
      <head>
        <title>Is DocuSign Free? Complete Guide & Alternative</title>
        <meta name="description" content="Wondering is docusign free? Discover DocuSign free plan limitations, features, pricing, and the top eSignature software alternative." />
      </head>
      <body></body>
    </html>
    """
    soup = BeautifulSoup(html_good, "lxml")
    res, issues = evaluate_title_and_meta(soup, "is docusign free")
    assert res.status == "PASS"
    assert res.title_has_keyword is True
    assert res.meta_has_keyword is True
    assert len(issues) == 0

    # Bad title (missing keyword, too short)
    html_bad = "<html><head><title>Signatures</title></head><body></body></html>"
    soup_bad = BeautifulSoup(html_bad, "lxml")
    res_bad, issues_bad = evaluate_title_and_meta(soup_bad, "is docusign free")
    assert res_bad.status in ("WARN", "FAIL")
    assert res_bad.title_has_keyword is False
    assert any("too short" in i for i in res_bad.issues)


def test_heading_hierarchy():
    # Valid hierarchy
    valid_html = """
    <div>
      <h1>Main Article Title</h1>
      <h2>Section One</h2>
      <h3>Sub-section A</h3>
      <h2>Section Two</h2>
    </div>
    """
    soup_valid = BeautifulSoup(valid_html, "lxml")
    res_valid, issues = evaluate_heading_hierarchy(soup_valid)
    assert res_valid.status == "PASS"
    assert res_valid.hierarchy_valid is True

    # Invalid: H1 skips directly to H3
    invalid_html = """
    <div>
      <h1>Main Article Title</h1>
      <h3>Skipped H2 and went to H3</h3>
    </div>
    """
    soup_invalid = BeautifulSoup(invalid_html, "lxml")
    res_invalid, issues_invalid = evaluate_heading_hierarchy(soup_invalid)
    assert res_invalid.status == "FAIL"
    assert res_invalid.hierarchy_valid is False
    assert any("Skipped heading level" in i for i in res_invalid.issues)


@pytest.mark.anyio
async def test_image_audit():
    html = """
    <div>
      <!-- 1. Good modern webp image -->
      <img src="https://signeasy.com/blog/chart.webp" alt="DocuSign pricing breakdown chart" />
      
      <!-- 2. Bad image: missing alt, legacy png -->
      <img src="https://signeasy.com/blog/screenshot.png" />
      
      <!-- 3. Bad image: generic alt -->
      <img src="https://signeasy.com/blog/photo.jpg" alt="screenshot" />
    </div>
    """
    soup = BeautifulSoup(html, "lxml")
    res, issues = await evaluate_images(soup, base_url="https://signeasy.com/blog/post")
    assert res.total_images == 3
    assert res.missing_alt_count == 2
    assert res.non_webp_count == 2
    assert res.status == "FAIL"


def test_schema_validation():
    valid_schema_html = """
    <html>
      <head>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "BlogPosting",
          "headline": "Is DocuSign Free?",
          "datePublished": "2026-01-10T08:00:00+00:00",
          "dateModified": "2026-02-15T10:00:00+00:00",
          "author": {
            "@type": "Person",
            "name": "Jane Doe"
          }
        }
        </script>
      </head>
      <body></body>
    </html>
    """
    soup = BeautifulSoup(valid_schema_html, "lxml")
    res, issues = evaluate_schema_structured_data(soup)
    assert res.status == "PASS"
    assert res.has_article_schema is True
    assert res.has_author is True
    assert "datePublished" in res.dates_present


def test_faq_section_and_schema():
    html = """
    <div>
      <h2>Frequently Asked Questions</h2>
      <p>Here are answers to common questions.</p>
    </div>
    """
    soup = BeautifulSoup(html, "lxml")
    # FAQ section present but schema missing
    res, issues = evaluate_faq_section(soup, has_faq_schema=False)
    assert res.faq_section_found is True
    assert res.status == "WARN"
    assert len(issues) > 0


def test_key_takeaways():
    html_with_kw = """
    <div>
      <h2>Key Takeaways</h2>
      <p>Here is what you need to know about is docusign free and pricing options.</p>
    </div>
    """
    soup = BeautifulSoup(html_with_kw, "lxml")
    res, issues = evaluate_key_takeaways(soup, "is docusign free")
    assert res.takeaways_section_found is True
    assert res.has_keyword is True
    assert res.status == "PASS"

