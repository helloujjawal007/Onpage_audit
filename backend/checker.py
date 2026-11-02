import re
import uuid
from datetime import datetime
from urllib.parse import urlparse
from typing import Dict, List, Set, Any, Optional
import httpx
from bs4 import BeautifulSoup

from backend.config import load_reputable_config, load_bad_anchors
from backend.utils import (
    clean_domain,
    normalize_url,
    is_internal_url,
    is_reputable_external,
    clean_anchor_text,
    check_anchor_quality,
    IGNORED_SCHEMES
)
from backend.models import (
    CheckRequest,
    CheckResponse,
    LinkDetail,
    IssueItem,
    LiveGateResult,
    SubCheckResult,
    KDResult,
    OnPageKeywordResult
)
from backend.kd_service import fetch_keyword_data
from backend.crawler import scan_incoming_internal_links
from backend.database import save_check_history

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
}


def validate_domains(site_url: str, page_url: str, internal_subdomains: Optional[List[str]] = None) -> tuple[bool, str]:
    site_domain = clean_domain(urlparse(site_url).netloc)
    page_domain = clean_domain(urlparse(page_url).netloc)
    
    if not site_domain:
        return False, "Site URL is invalid."
    if not page_domain:
        return False, "Page URL is invalid."
        
    allowed_domains = {site_domain}
    for sub in (internal_subdomains or []):
        sub_clean = clean_domain(sub)
        if sub_clean:
            allowed_domains.add(sub_clean)
            
    if page_domain not in allowed_domains:
        return False, f"Ye page is site ka nahi hai (Page domain '{page_domain}' does not match Site domain '{site_domain}' or listed subdomains)."
        
    return True, ""


async def run_live_gate(page_url: str) -> tuple[LiveGateResult, Optional[str], Optional[httpx.Response]]:
    """
    Performs Rule #0 Live Check Gate:
    - Status code evaluation
    - Redirect chain logging
    - Meta robots noindex check
    - Canonical tag check
    """
    try:
        async with httpx.AsyncClient(headers=HEADERS, timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(page_url)
            
            # Extract redirect chain if any
            chain = [str(r.url) for r in resp.history]
            final_url = str(resp.url)
            is_redirected = len(chain) > 0
            content_type = resp.headers.get("content-type", "").lower()
            status = resp.status_code
            
            # Check for non-HTML
            if "text/html" not in content_type and resp.status_code == 200:
                return LiveGateResult(
                    is_live=False,
                    status_code=status,
                    content_type=content_type,
                    redirect_chain=chain,
                    final_url=final_url,
                    is_redirected=is_redirected,
                    message=f"Invalid Content-Type: '{content_type}'. Must be text/html."
                ), None, resp

            # Evaluate status codes
            if status == 200:
                html = resp.text
                soup = BeautifulSoup(html, "lxml")
                
                # Check meta robots
                noindex = False
                meta_robots = soup.find("meta", attrs={"name": re.compile(r"^robots$", re.I)})
                if meta_robots and "noindex" in (meta_robots.get("content", "")).lower():
                    noindex = True
                if "noindex" in resp.headers.get("x-robots-tag", "").lower():
                    noindex = True
                    
                # Check canonical
                canonical_url = None
                is_self_canonical = None
                canonical_tag = soup.find("link", rel=lambda val: val and "canonical" in val.lower())
                if canonical_tag and canonical_tag.get("href"):
                    raw_canonical = canonical_tag.get("href")
                    canonical_url = normalize_url(raw_canonical, base_url=final_url)
                    norm_final = normalize_url(final_url)
                    is_self_canonical = (canonical_url == norm_final)
                    
                msg = "Page is LIVE (200 OK)."
                if is_redirected:
                    msg += f" Note: Redirected through {len(chain)} hop(s)."
                if noindex:
                    msg += " WARNING: Page has noindex tag!"

                return LiveGateResult(
                    is_live=True,
                    status_code=status,
                    content_type=content_type,
                    redirect_chain=chain,
                    final_url=final_url,
                    is_redirected=is_redirected,
                    noindex=noindex,
                    canonical_url=canonical_url,
                    is_self_canonical=is_self_canonical,
                    message=msg
                ), html, resp

            elif status in (404, 410):
                return LiveGateResult(
                    is_live=False,
                    status_code=status,
                    content_type=content_type,
                    redirect_chain=chain,
                    final_url=final_url,
                    is_redirected=is_redirected,
                    message=f"Page not found ({status}) - Publish nahi hua."
                ), None, resp
            elif status in (401, 403):
                return LiveGateResult(
                    is_live=False,
                    status_code=status,
                    content_type=content_type,
                    redirect_chain=chain,
                    final_url=final_url,
                    is_redirected=is_redirected,
                    message=f"Access restricted ({status}) - Draft ya login required."
                ), None, resp
            else:
                return LiveGateResult(
                    is_live=False,
                    status_code=status,
                    content_type=content_type,
                    redirect_chain=chain,
                    final_url=final_url,
                    is_redirected=is_redirected,
                    message=f"Server returned status {status}. Baad me try karo."
                ), None, resp

    except httpx.TimeoutException:
        return LiveGateResult(
            is_live=False,
            status_code=504,
            content_type="",
            final_url=page_url,
            message="Request timed out after 15s. Server error ya slow response."
        ), None, None
    except Exception as e:
        return LiveGateResult(
            is_live=False,
            status_code=0,
            content_type="",
            final_url=page_url,
            message=f"Fetch failed: {str(e)}"
        ), None, None


def extract_article_body(soup: BeautifulSoup, custom_selector: Optional[str] = None):
    """
    Extracts main article body container to exclude header, nav, footer, sidebar.
    """
    if custom_selector:
        container = soup.select_one(custom_selector)
        if container:
            return container

    candidates = [
        "article",
        "main",
        "[role='main']",
        ".post-content",
        ".blog-post-content",
        ".entry-content",
        ".article-content",
        "#content",
        ".content"
    ]
    for selector in candidates:
        container = soup.select_one(selector)
        if container:
            # Check if container contains at least some text/links
            if len(container.find_all("p")) > 0 or len(container.find_all("a")) > 0:
                return container

    # Fallback to copy of body with header/footer/nav removed
    body = soup.find("body")
    if not body:
        return soup
        
    for unwanted in body.select("header, footer, nav, aside, .header, .footer, .nav, .sidebar, .comments"):
        unwanted.decompose()
    return body


def evaluate_onpage_keyword(
    soup: BeautifulSoup,
    body_container,
    page_url: str,
    keyword: str
) -> OnPageKeywordResult:
    kw_clean = keyword.lower().strip()
    kw_words = kw_clean.split()
    
    # 1. URL Slug
    parsed = urlparse(page_url)
    slug = parsed.path.lower().replace("-", " ").replace("_", " ")
    in_slug = kw_clean in slug
    
    # 2. H1 Check
    h1_elements = soup.find_all("h1")
    h1_count = len(h1_elements)
    h1_has_keyword = any(kw_clean in h1.get_text().lower() for h1 in h1_elements)
    
    # 3. H2 Check
    h2_elements = soup.find_all("h2")
    h2_has_keyword = any(kw_clean in h2.get_text().lower() for h2 in h2_elements)
    
    # 4. First paragraph
    paragraphs = body_container.find_all("p") if body_container else []
    first_p_text = paragraphs[0].get_text().lower() if paragraphs else ""
    first_p_has_keyword = kw_clean in first_p_text
    
    # 5. Density
    body_text = body_container.get_text() if body_container else soup.get_text()
    all_words = re.findall(r'\b\w+\b', body_text.lower())
    total_words = len(all_words)
    kw_count = len(re.findall(rf'\b{re.escape(kw_clean)}\b', body_text.lower()))
    
    density = 0.0
    if total_words > 0 and len(kw_words) > 0:
        density = round((kw_count * len(kw_words) / total_words) * 100, 2)
        
    issues = []
    if not in_slug:
        issues.append("Primary keyword missing from URL slug")
    if h1_count == 0:
        issues.append("Missing H1 heading on page")
    elif h1_count > 1:
        issues.append(f"Multiple H1 headings found ({h1_count}); recommended exactly 1")
    elif not h1_has_keyword:
        issues.append("Primary keyword missing from H1 tag")
    if not h2_has_keyword:
        issues.append("Primary keyword missing from any H2 tag")
    if not first_p_has_keyword:
        issues.append("Primary keyword not found in the first paragraph")
    if density < 0.5 and total_words > 200:
        issues.append(f"Keyword density ({density}%) is below recommended ~0.5%")

    status = "PASS" if len(issues) <= 1 else ("WARN" if len(issues) <= 3 else "FAIL")
    
    return OnPageKeywordResult(
        status=status,
        in_slug=in_slug,
        h1_count=h1_count,
        h1_has_keyword=h1_has_keyword,
        h2_has_keyword=h2_has_keyword,
        first_p_has_keyword=first_p_has_keyword,
        keyword_count=kw_count,
        total_words=total_words,
        keyword_density=density,
        issues=issues
    )


async def run_full_check(req: CheckRequest) -> CheckResponse:
    check_id = str(uuid.uuid4())
    timestamp = datetime.utcnow().isoformat()
    
    # Step 1: Validate domain
    domain_ok, domain_err = validate_domains(req.site_url, req.page_url, req.internal_subdomains)
    if not domain_ok:
        # Return failed live gate
        gate = LiveGateResult(
            is_live=False,
            status_code=400,
            content_type="",
            final_url=req.page_url,
            message=domain_err
        )
        empty_sub = SubCheckResult(name="", status="SKIPPED", summary="Domain validation failed")
        empty_kd = KDResult(keyword=req.primary_keyword, kd=0, volume=0, source="None", country=req.country)
        empty_onpage = OnPageKeywordResult(
            status="SKIPPED", in_slug=False, h1_count=0, h1_has_keyword=False,
            h2_has_keyword=False, first_p_has_keyword=False, keyword_count=0,
            total_words=0, keyword_density=0.0, issues=[domain_err]
        )
        return CheckResponse(
            id=check_id,
            timestamp=timestamp,
            site_url=req.site_url,
            page_url=req.page_url,
            primary_keyword=req.primary_keyword,
            live_gate=gate,
            check_a_new_tab=empty_sub,
            check_b_follow=empty_sub,
            check_c1_internal_outgoing=empty_sub,
            check_c2_incoming_links=empty_sub,
            check_c3_product_link=empty_sub,
            check_c4_anchor_quality=empty_sub,
            check_c5_duplicates=empty_sub,
            check_d_kd=empty_kd,
            check_d_onpage=empty_onpage,
            overall_pass=False,
            total_links=0,
            internal_links_count=0,
            external_links_count=0,
            failed_issues=[IssueItem(link=req.page_url, anchor="", problem=domain_err, fix="Enter a page URL that matches the site domain")]
        )

    # Step 2: Live check gate
    gate, html_content, raw_resp = await run_live_gate(req.page_url)
    if not gate.is_live or not html_content:
        empty_sub = SubCheckResult(name="", status="SKIPPED", summary="Page is not live or accessible")
        empty_kd = KDResult(keyword=req.primary_keyword, kd=0, volume=0, source="None", country=req.country)
        empty_onpage = OnPageKeywordResult(
            status="SKIPPED", in_slug=False, h1_count=0, h1_has_keyword=False,
            h2_has_keyword=False, first_p_has_keyword=False, keyword_count=0,
            total_words=0, keyword_density=0.0, issues=[gate.message]
        )
        return CheckResponse(
            id=check_id,
            timestamp=timestamp,
            site_url=req.site_url,
            page_url=req.page_url,
            primary_keyword=req.primary_keyword,
            live_gate=gate,
            check_a_new_tab=empty_sub,
            check_b_follow=empty_sub,
            check_c1_internal_outgoing=empty_sub,
            check_c2_incoming_links=empty_sub,
            check_c3_product_link=empty_sub,
            check_c4_anchor_quality=empty_sub,
            check_c5_duplicates=empty_sub,
            check_d_kd=empty_kd,
            check_d_onpage=empty_onpage,
            overall_pass=False,
            total_links=0,
            internal_links_count=0,
            external_links_count=0,
            failed_issues=[IssueItem(link=req.page_url, anchor="", problem=gate.message, fix="Ensure URL is published and returns HTTP 200 OK")]
        )

    # Step 3: Parse HTML and extract article body links
    soup = BeautifulSoup(html_content, "lxml")
    body_container = extract_article_body(soup, req.custom_body_selector)
    
    reputable_config = load_reputable_config()
    bad_anchors = load_bad_anchors()

    # Normalize Product Page URL if provided
    norm_product_page = normalize_url(req.product_page_url) if req.product_page_url else None
    product_keywords_lower = [k.strip().lower() for k in (req.product_anchor_keywords or []) if k.strip()]

    all_links: List[LinkDetail] = []
    seen_normalized_hrefs: Dict[str, int] = {}
    failed_issues: List[IssueItem] = []

    a_tags = body_container.select("a[href]") if body_container else []
    
    product_link_found = False
    product_anchor_matched = False
    product_matching_anchors = []

    for a in a_tags:
        raw_href = a.get("href", "").strip()
        parsed_raw = urlparse(raw_href)
        
        # Skip mailto, tel, javascript, in-page fragment hashes
        if parsed_raw.scheme in IGNORED_SCHEMES or (raw_href.startswith("#") and len(raw_href) > 0):
            continue
        if not raw_href or raw_href == "#":
            continue

        resolved_href = normalize_url(raw_href, base_url=gate.final_url)
        if not resolved_href:
            continue

        raw_anchor = a.get_text()
        anchor = clean_anchor_text(raw_anchor)
        
        # If anchor text is empty, check for inner img alt
        if not anchor:
            img = a.find("img")
            if img and img.get("alt"):
                anchor = f"[Image: {img.get('alt').strip()}]"

        is_ext = not is_internal_url(resolved_href, req.site_url, req.internal_subdomains)
        target_val = a.get("target", "")
        new_tab = (target_val == "_blank")
        
        rel_attr = a.get("rel", [])
        if isinstance(rel_attr, str):
            rel_tags = rel_attr.split()
        else:
            rel_tags = list(rel_attr)
        rel_tags_lower = [r.lower() for r in rel_tags]
        
        has_noopener = ("noopener" in rel_tags_lower) or ("noreferrer" in rel_tags_lower)
        actual_nofollow = "nofollow" in rel_tags_lower
        
        # Expected follow/nofollow
        expected_follow = None
        follow_ok = True
        link_issues: List[IssueItem] = []

        if is_ext:
            target_domain = clean_domain(urlparse(resolved_href).netloc)
            is_rep = is_reputable_external(target_domain, reputable_config)
            expected_follow = "dofollow" if is_rep else "nofollow"
            
            if expected_follow == "dofollow" and actual_nofollow:
                follow_ok = False
                issue = IssueItem(
                    link=resolved_href,
                    anchor=anchor or "(empty)",
                    problem=f"Reputable authority site ({target_domain}) has nofollow tag",
                    fix="Remove nofollow (reputable authority domain should be dofollow)"
                )
                link_issues.append(issue)
                failed_issues.append(issue)
            elif expected_follow == "nofollow" and not actual_nofollow:
                follow_ok = False
                issue = IssueItem(
                    link=resolved_href,
                    anchor=anchor or "(empty)",
                    problem="External link is missing nofollow",
                    fix="Add rel='nofollow'"
                )
                link_issues.append(issue)
                failed_issues.append(issue)
        else:
            # Internal link
            follow_ok = True
            expected_follow = "dofollow"

        # Check A: new tab
        if not new_tab:
            issue = IssueItem(
                link=resolved_href,
                anchor=anchor or "(empty)",
                problem="Link does not open in a new tab (missing target='_blank')",
                fix="Add target='_blank' rel='noopener noreferrer'"
            )
            link_issues.append(issue)
            failed_issues.append(issue)

        # Check C4: bad anchor
        is_bad_anchor, bad_reason = check_anchor_quality(anchor, resolved_href, bad_anchors)
        if is_bad_anchor:
            issue = IssueItem(
                link=resolved_href,
                anchor=anchor or "(empty)",
                problem=f"Anchor quality issue: {bad_reason}",
                fix="Use descriptive, keyword-rich contextual anchor text"
            )
            link_issues.append(issue)
            failed_issues.append(issue)

        # Check C5: duplicate links
        seen_normalized_hrefs[resolved_href] = seen_normalized_hrefs.get(resolved_href, 0) + 1
        is_dup = seen_normalized_hrefs[resolved_href] > 1
        if is_dup:
            issue = IssueItem(
                link=resolved_href,
                anchor=anchor or "(empty)",
                problem="Duplicate link (same URL linked multiple times in article body)",
                fix="Consolidate internal linking or remove redundant duplicate link"
            )
            link_issues.append(issue)
            failed_issues.append(issue)

        # Check C3: product page link match
        is_prod = False
        if norm_product_page and resolved_href == norm_product_page:
            is_prod = True
            product_link_found = True
            # Check anchor keyword match
            if product_keywords_lower:
                anchor_lower = anchor.lower()
                matched_kw = [k for k in product_keywords_lower if k in anchor_lower]
                if matched_kw:
                    product_anchor_matched = True
                    product_matching_anchors.extend(matched_kw)
            else:
                product_anchor_matched = True

        link_detail = LinkDetail(
            href=resolved_href,
            raw_href=raw_href,
            anchor=anchor,
            is_external=is_ext,
            is_product_page=is_prod,
            new_tab=new_tab,
            has_noopener=has_noopener,
            rel_tags=rel_tags,
            nofollow=actual_nofollow,
            follow_ok=follow_ok,
            expected_follow=expected_follow,
            actual_follow="nofollow" if actual_nofollow else "dofollow",
            bad_anchor=is_bad_anchor,
            bad_anchor_reason=bad_reason,
            duplicate=is_dup,
            issues=link_issues
        )
        all_links.append(link_detail)

    # Summarize checks
    total_links = len(all_links)
    internal_links = [l for l in all_links if not l.is_external]
    external_links = [l for l in all_links if l.is_external]
    
    unique_internal_urls = len(set(l.href for l in internal_links))
    unique_external_urls = len(set(l.href for l in external_links))

    # Check A: new tab
    failed_new_tab = [l for l in all_links if not l.new_tab]
    check_a = SubCheckResult(
        name="A. Links open in new tab",
        status="PASS" if len(failed_new_tab) == 0 else "FAIL",
        summary=f"{len(failed_new_tab)} of {total_links} links missing target='_blank'",
        score_or_count=len(failed_new_tab)
    )

    # Check B: Follow / Nofollow
    failed_follow = [l for l in external_links if not l.follow_ok]
    check_b = SubCheckResult(
        name="B. Nofollow / Dofollow",
        status="PASS" if len(failed_follow) == 0 else "FAIL",
        summary=f"{len(failed_follow)} of {len(external_links)} external links violate follow rules",
        score_or_count=len(failed_follow)
    )

    # Check C1: Outgoing internal links
    c1_passed = unique_internal_urls >= 1
    check_c1 = SubCheckResult(
        name="C1. Outgoing internal links",
        status="PASS" if c1_passed else "FAIL",
        summary=f"{unique_internal_urls} unique internal link(s) found (minimum 1 required)",
        score_or_count=unique_internal_urls
    )

    # Check C2: Incoming internal links (5+ rule) via crawler
    crawler_res = await scan_incoming_internal_links(req.site_url, gate.final_url, max_crawl_pages=40)
    c2_count = crawler_res.get("count", 0)
    c2_passed = crawler_res.get("passed", False)
    check_c2 = SubCheckResult(
        name="C2. Incoming internal links (5+ rule)",
        status="PASS" if c2_passed else "FAIL",
        summary=f"{c2_count} of 5 required incoming blog links found ({crawler_res.get('source', '')})",
        score_or_count=c2_count,
        details=f"Analyzed {crawler_res.get('pages_analyzed', 0)} pages from sitemap. Found links from: {', '.join(crawler_res.get('referring_urls', [])[:3]) or 'None'}"
    )

    # Check C3: Product page link + anchor
    if norm_product_page:
        if not product_link_found:
            check_c3 = SubCheckResult(
                name="C3. Product page link",
                status="FAIL",
                summary=f"No link found to product page ({norm_product_page})"
            )
            failed_issues.append(IssueItem(
                link=norm_product_page,
                anchor="",
                problem="Missing product page link in article body",
                fix=f"Add a contextual link pointing to '{norm_product_page}'"
            ))
        elif product_keywords_lower and not product_anchor_matched:
            check_c3 = SubCheckResult(
                name="C3. Product page link",
                status="FAIL",
                summary="Product link present, but anchor text is missing required product keywords"
            )
            failed_issues.append(IssueItem(
                link=norm_product_page,
                anchor="",
                problem="Product anchor text does not contain any product keywords",
                fix=f"Update anchor text using: {', '.join(req.product_anchor_keywords)}"
            ))
        else:
            matched_msg = f" (matched anchor keyword: '{product_matching_anchors[0]}')" if product_matching_anchors else ""
            check_c3 = SubCheckResult(
                name="C3. Product page link",
                status="PASS",
                summary=f"Product link verified{matched_msg}"
            )
    else:
        check_c3 = SubCheckResult(
            name="C3. Product page link",
            status="SKIPPED",
            summary="No Product page URL provided in input"
        )

    # Check C4: Anchor quality
    failed_anchors = [l for l in all_links if l.bad_anchor]
    check_c4 = SubCheckResult(
        name="C4. Bad anchors",
        status="PASS" if len(failed_anchors) == 0 else "FAIL",
        summary=f"{len(failed_anchors)} bad/naked/empty anchor(s) detected",
        score_or_count=len(failed_anchors)
    )

    # Check C5: Duplicate links
    dup_links = [l for l in all_links if l.duplicate]
    check_c5 = SubCheckResult(
        name="C5. Duplicate links",
        status="PASS" if len(dup_links) == 0 else "FAIL",
        summary=f"{len(dup_links)} duplicate link occurrence(s) found",
        score_or_count=len(dup_links)
    )

    # Check D: KD and On-Page Keyword
    kd_res = await fetch_keyword_data(req.primary_keyword, req.country)
    onpage_res = evaluate_onpage_keyword(soup, body_container, gate.final_url, req.primary_keyword)

    # Overall pass condition
    all_mandatory = [
        check_a.status == "PASS",
        check_b.status == "PASS",
        check_c1.status == "PASS",
        check_c2.status == "PASS",
        check_c3.status in ("PASS", "SKIPPED"),
        check_c4.status == "PASS",
        check_c5.status == "PASS"
    ]
    overall_pass = all(all_mandatory)

    response = CheckResponse(
        id=check_id,
        timestamp=timestamp,
        site_url=req.site_url,
        page_url=gate.final_url,
        primary_keyword=req.primary_keyword,
        live_gate=gate,
        check_a_new_tab=check_a,
        check_b_follow=check_b,
        check_c1_internal_outgoing=check_c1,
        check_c2_incoming_links=check_c2,
        check_c3_product_link=check_c3,
        check_c4_anchor_quality=check_c4,
        check_c5_duplicates=check_c5,
        check_d_kd=kd_res,
        check_d_onpage=onpage_res,
        overall_pass=overall_pass,
        total_links=total_links,
        internal_links_count=len(internal_links),
        external_links_count=len(external_links),
        failed_issues=failed_issues,
        all_links=all_links
    )

    # Save to history
    save_check_history(
        record_id=check_id,
        site_url=req.site_url,
        page_url=gate.final_url,
        keyword=req.primary_keyword,
        overall_pass=overall_pass,
        result_dict=response.model_dump()
    )

    return response
