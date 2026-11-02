import pytest
from unittest.mock import patch, MagicMock
from backend.models import CheckRequest
from backend.checker import run_full_check
from backend.database import init_db

init_db()

SAMPLE_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Is DocuSign Free? - Signeasy Blog</title>
    <link rel="canonical" href="https://signeasy.com/blog/business/is-docusign-free" />
</head>
<body>
    <header>
        <a href="https://signeasy.com">Signeasy Home</a>
    </header>
    <article class="post-content">
        <h1>Is DocuSign Free? In-depth Comparison</h1>
        <p>Are you asking is docusign free before committing to a paid plan? Let's explore alternatives.</p>
        
        <h2>Comparing Free Plans</h2>
        <p>DocuSign gives a 30-day trial. For an affordable solution, check out our 
           <a href="https://signeasy.com/electronic-signature-software" target="_blank" rel="noopener">eSignature software</a>.
        </p>
        
        <p>Also, check out our related blog post on 
           <a href="https://signeasy.com/blog/how-to-sign-pdf" target="_blank" rel="noopener">how to sign PDF documents</a>.
        </p>

        <!-- Violations below: -->
        <!-- 1. Bad anchor + missing target="_blank" -->
        <p>To read more about general laws, <a href="https://wikipedia.org/wiki/Electronic_signature">click here</a>.</p>
        
        <!-- 2. External standard link without nofollow -->
        <p>Read the commercial vendor review at 
           <a href="https://commercialtechreview.com/docusign" target="_blank">tech review</a>.
        </p>

        <!-- 3. Duplicate link -->
        <p>Again visit <a href="https://signeasy.com/electronic-signature-software?utm_source=footer_blog" target="_blank">our tool</a>.</p>
    </article>
    <footer>
        <a href="https://signeasy.com/terms">Terms</a>
    </footer>
</body>
</html>
"""


@pytest.mark.anyio
async def test_mocked_full_audit():
    req = CheckRequest(
        site_url="https://signeasy.com",
        page_url="https://signeasy.com/blog/business/is-docusign-free",
        primary_keyword="is docusign free",
        product_page_url="https://signeasy.com/electronic-signature-software",
        product_anchor_keywords=["eSignature software", "eSign tool"],
        internal_subdomains=["app.signeasy.com"],
        country="us"
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"content-type": "text/html; charset=utf-8"}
    mock_resp.text = SAMPLE_HTML
    mock_resp.url = "https://signeasy.com/blog/business/is-docusign-free"
    mock_resp.history = []

    with patch("httpx.AsyncClient.get", return_value=mock_resp), \
         patch("backend.checker.scan_incoming_internal_links", return_value={"count": 5, "passed": True, "source": "test", "referring_urls": ["https://signeasy.com/blog/1"]}):
        
        res = await run_full_check(req)

        assert res.live_gate.is_live is True
        assert res.live_gate.status_code == 200
        assert res.live_gate.is_self_canonical is True

        # Check A: Wikipedia link has no target="_blank" -> FAIL
        assert res.check_a_new_tab.status == "FAIL"

        # Check B: commercialtechreview.com has no nofollow -> FAIL
        assert res.check_b_follow.status == "FAIL"

        # Check C1: Outgoing internal links >= 1 -> PASS
        assert res.check_c1_internal_outgoing.status == "PASS"

        # Check C2: Incoming internal links (mocked 5) -> PASS
        assert res.check_c2_incoming_links.status == "PASS"

        # Check C3: Product page link with "eSignature software" anchor -> PASS
        assert res.check_c3_product_link.status == "PASS"

        # Check C4: "click here" detected -> FAIL
        assert res.check_c4_anchor_quality.status == "FAIL"

        # Check C5: Duplicate product page link (with utm params) -> FAIL
        assert res.check_c5_duplicates.status == "FAIL"

        # Check D: KD and On-page
        assert res.check_d_kd.kd is not None
        assert res.check_d_onpage.h1_has_keyword is True
        assert res.check_d_onpage.in_slug is True

        # Overall failure expected because of violations
        assert res.overall_pass is False
        assert len(res.failed_issues) > 0
