import re
import json
from urllib.parse import urlparse
from typing import List, Dict, Any, Optional
import httpx
from bs4 import BeautifulSoup

from backend.utils import normalize_url, clean_domain
from backend.models import (
    TitleMetaCheckResult,
    HeadingHierarchyResult,
    ImageAuditItem,
    ImageAuditResult,
    SchemaValidationResult,
    FAQSectionResult,
    KeyTakeawaysResult,
    Phase2Checks,
    IssueItem
)

# Approximate pixel widths based on Arial rendering in Google SERP
WIDE_CHARS = set("WMwm@%&#")
NARROW_CHARS = set("ilIjtfr .,:;!'|")


def calculate_pixel_width(text: str, is_title: bool = True) -> int:
    """
    Estimates Google SERP pixel width for desktop.
    Title uses ~20px Arial (~9.5px average).
    Snippet uses ~14px Arial (~6.5px average).
    """
    if not text:
        return 0
        
    width = 0.0
    for ch in text:
        if ch in WIDE_CHARS:
            width += 14.0 if is_title else 10.0
        elif ch in NARROW_CHARS:
            width += 4.5 if is_title else 3.5
        elif ch.isupper():
            width += 11.5 if is_title else 8.5
        else:
            width += 9.5 if is_title else 6.5
            
    return int(round(width))


def evaluate_title_and_meta(
    soup: BeautifulSoup,
    primary_keyword: str
) -> tuple[TitleMetaCheckResult, List[IssueItem]]:
    issues: List[str] = []
    action_items: List[IssueItem] = []
    kw_lower = primary_keyword.lower().strip()

    # 1. Title Tag
    title_el = soup.find("title")
    title_text = title_el.get_text().strip() if title_el else ""
    title_len = len(title_text)
    title_px = calculate_pixel_width(title_text, is_title=True)
    title_has_kw = kw_lower in title_text.lower() if title_text else False

    if not title_text:
        issues.append("Missing <title> tag on page")
        action_items.append(IssueItem(
            link="<title>", anchor="title", problem="Missing <title> tag",
            fix=f"Add a descriptive title (50-60 chars) including '{primary_keyword}'"
        ))
    else:
        if title_len < 30:
            issues.append(f"Title is too short ({title_len} chars, recommended 50-60 chars)")
        elif title_len > 60 or title_px > 580:
            issues.append(f"Title may truncate in Google SERP ({title_len} chars, ~{title_px}px; max recommended ~580px / 60 chars)")
            action_items.append(IssueItem(
                link="<title>", anchor=title_text[:30] + "...",
                problem=f"Title exceeds recommended length ({title_len} chars, ~{title_px}px)",
                fix="Shorten title to <= 60 chars / 580px to prevent SERP truncation"
            ))
        if not title_has_kw:
            issues.append(f"Primary keyword '{primary_keyword}' not found in <title>")
            action_items.append(IssueItem(
                link="<title>", anchor=title_text[:30] + "...",
                problem="Primary keyword missing from <title>",
                fix=f"Include '{primary_keyword}' near the start of the title tag"
            ))

    # 2. Meta Description
    meta_desc_el = soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)})
    meta_desc = meta_desc_el.get("content", "").strip() if meta_desc_el else ""
    meta_len = len(meta_desc)
    meta_px = calculate_pixel_width(meta_desc, is_title=False)
    meta_has_kw = kw_lower in meta_desc.lower() if meta_desc else False

    if not meta_desc:
        issues.append("Missing meta description tag")
        action_items.append(IssueItem(
            link="<meta name='description'>", anchor="meta-description",
            problem="Missing meta description tag",
            fix=f"Add a compelling meta description (120-160 chars) including '{primary_keyword}'"
        ))
    else:
        if meta_len < 70:
            issues.append(f"Meta description is too short ({meta_len} chars, recommended 120-160 chars)")
        elif meta_len > 160 or meta_px > 960:
            issues.append(f"Meta description may truncate in SERP ({meta_len} chars, ~{meta_px}px; max ~960px / 160 chars)")
            action_items.append(IssueItem(
                link="<meta name='description'>", anchor=meta_desc[:30] + "...",
                problem=f"Meta description too long ({meta_len} chars, ~{meta_px}px)",
                fix="Shorten meta description to 120-160 characters"
            ))
        if not meta_has_kw:
            issues.append(f"Primary keyword '{primary_keyword}' not found in meta description")
            action_items.append(IssueItem(
                link="<meta name='description'>", anchor=meta_desc[:30] + "...",
                problem="Primary keyword missing from meta description",
                fix=f"Incorporate '{primary_keyword}' naturally in the meta description"
            ))

    status = "PASS" if len(issues) == 0 else ("WARN" if len(issues) <= 2 else "FAIL")
    result = TitleMetaCheckResult(
        status=status,
        title=title_text or None,
        title_char_length=title_len,
        title_pixel_width=title_px,
        title_has_keyword=title_has_kw,
        meta_description=meta_desc or None,
        meta_char_length=meta_len,
        meta_pixel_width=meta_px,
        meta_has_keyword=meta_has_kw,
        issues=issues
    )
    return result, action_items


def evaluate_heading_hierarchy(soup: BeautifulSoup) -> tuple[HeadingHierarchyResult, List[IssueItem]]:
    headings = soup.find_all(re.compile(r"^h[1-6]$"))
    h1_elements = soup.find_all("h1")
    h1_count = len(h1_elements)
    h1_text = h1_elements[0].get_text().strip() if h1_elements else None

    issues: List[str] = []
    action_items: List[IssueItem] = []
    hierarchy_valid = True

    if h1_count == 0:
        issues.append("Missing H1 heading on page")
        hierarchy_valid = False
        action_items.append(IssueItem(
            link="H1", anchor="none", problem="Missing H1 heading tag",
            fix="Add exactly one primary H1 heading to the article"
        ))
    elif h1_count > 1:
        issues.append(f"Multiple H1 headings found ({h1_count}). Only exactly 1 H1 is recommended.")
        hierarchy_valid = False
        action_items.append(IssueItem(
            link="H1", anchor=h1_text or "H1", problem=f"{h1_count} H1 tags detected",
            fix="Consolidate so there is only 1 primary H1 heading; use H2 for subsections"
        ))

    # Check hierarchy steps (no skipping e.g. H1 -> H3 or H2 -> H4)
    prev_level = 0
    for h in headings:
        level = int(h.name[1])
        if prev_level > 0 and level > prev_level + 1:
            err = f"Skipped heading level: H{prev_level} directly to H{level} ('{h.get_text().strip()[:40]}')"
            issues.append(err)
            hierarchy_valid = False
            action_items.append(IssueItem(
                link=h.name.upper(), anchor=h.get_text().strip()[:30],
                problem=f"Improper heading hierarchy: skipped from H{prev_level} to H{level}",
                fix=f"Use H{prev_level + 1} before H{level} to maintain logical structure"
            ))
        prev_level = level

    status = "PASS" if hierarchy_valid and h1_count == 1 else "FAIL"
    return HeadingHierarchyResult(
        status=status,
        h1_count=h1_count,
        h1_text=h1_text,
        total_headings=len(headings),
        hierarchy_valid=hierarchy_valid,
        issues=issues
    ), action_items


async def evaluate_images(
    body_container,
    base_url: str,
    client: Optional[httpx.AsyncClient] = None
) -> tuple[ImageAuditResult, List[IssueItem]]:
    img_tags = body_container.find_all("img") if body_container else []
    items: List[ImageAuditItem] = []
    action_items: List[IssueItem] = []
    overall_issues: List[str] = []

    missing_alt = 0
    non_webp = 0
    large_count = 0

    GENERIC_ALTS = {"image", "photo", "screenshot", "untitled", "img", "picture", "graphic"}

    for img in img_tags:
        src = img.get("src", "").strip()
        if not src or src.startswith("data:"):
            continue

        normalized_src = normalize_url(src, base_url=base_url)
        alt = (img.get("alt") or "").strip()
        
        # Determine format
        parsed_path = urlparse(normalized_src).path.lower()
        if parsed_path.endswith(".webp"):
            fmt = "webp"
        elif parsed_path.endswith(".avif"):
            fmt = "avif"
        elif parsed_path.endswith(".svg"):
            fmt = "svg"
        elif parsed_path.endswith((".png", ".png/")):
            fmt = "png"
        elif parsed_path.endswith((".jpg", ".jpeg")):
            fmt = "jpg"
        elif parsed_path.endswith(".gif"):
            fmt = "gif"
        else:
            fmt = "unknown"

        is_modern = fmt in ("webp", "avif", "svg")
        img_issues: List[str] = []

        # Alt tag check
        if not alt:
            missing_alt += 1
            img_issues.append("Missing alt attribute")
            action_items.append(IssueItem(
                link=normalized_src, anchor="img",
                problem="Image is missing alt text",
                fix="Add descriptive, keyword-relevant alt text to the <img> tag"
            ))
        elif alt.lower() in GENERIC_ALTS:
            missing_alt += 1
            img_issues.append(f"Generic alt text: '{alt}'")
            action_items.append(IssueItem(
                link=normalized_src, anchor=alt,
                problem="Generic alt text detected",
                fix="Replace generic alt text with specific description of image content"
            ))

        # Modern format check
        if not is_modern:
            non_webp += 1
            img_issues.append(f"Format is {fmt.upper()}, recommended WebP or AVIF")

        # Size check via HTTP HEAD if client provided
        size_kb = None
        if client:
            try:
                head_resp = await client.head(normalized_src, timeout=3.0)
                if head_resp.status_code == 200:
                    cl = head_resp.headers.get("content-length")
                    if cl and cl.isdigit():
                        size_kb = round(int(cl) / 1024, 1)
                        if size_kb > 100.0:
                            large_count += 1
                            img_issues.append(f"Image size is {size_kb} KB (> 100 KB target)")
                            action_items.append(IssueItem(
                                link=normalized_src, anchor=alt or "img",
                                problem=f"Image size ({size_kb} KB) exceeds recommended 100 KB limit",
                                fix="Compress and convert image to WebP format under 100 KB"
                            ))
            except Exception:
                pass

        items.append(ImageAuditItem(
            src=normalized_src,
            alt=alt,
            format=fmt,
            is_webp_or_modern=is_modern,
            size_kb=size_kb,
            issues=img_issues
        ))

    if missing_alt > 0:
        overall_issues.append(f"{missing_alt} image(s) missing proper descriptive alt text")
    if non_webp > 0:
        overall_issues.append(f"{non_webp} image(s) not using modern WebP/AVIF compression")
    if large_count > 0:
        overall_issues.append(f"{large_count} image(s) exceed 100 KB file size")

    status = "PASS" if len(overall_issues) == 0 else ("WARN" if missing_alt == 0 else "FAIL")
    return ImageAuditResult(
        status=status,
        total_images=len(items),
        missing_alt_count=missing_alt,
        non_webp_count=non_webp,
        large_image_count=large_count,
        images=items,
        issues=overall_issues
    ), action_items


def evaluate_schema_structured_data(soup: BeautifulSoup) -> tuple[SchemaValidationResult, List[IssueItem]]:
    scripts = soup.find_all("script", attrs={"type": "application/ld+json"})
    schema_types: List[str] = []
    has_article = False
    has_faq = False
    article_type = None
    dates: Dict[str, Optional[str]] = {}
    has_author = False
    issues: List[str] = []
    action_items: List[IssueItem] = []

    for s in scripts:
        raw_text = s.string or s.get_text() or ""
        if not raw_text.strip():
            continue
        try:
            data = json.loads(raw_text)
            items_to_inspect = data.get("@graph", []) if isinstance(data, dict) and "@graph" in data else ([data] if isinstance(data, dict) else (data if isinstance(data, list) else []))
            
            for item in items_to_inspect:
                if not isinstance(item, dict):
                    continue
                stype = item.get("@type")
                if isinstance(stype, list):
                    schema_types.extend(stype)
                elif stype:
                    schema_types.append(stype)

                if stype in ("Article", "BlogPosting", "NewsArticle", "TechArticle"):
                    has_article = True
                    article_type = stype
                    if "datePublished" in item:
                        dates["datePublished"] = str(item["datePublished"])
                    if "dateModified" in item:
                        dates["dateModified"] = str(item["dateModified"])
                    if "author" in item:
                        has_author = True

                if stype == "FAQPage":
                    has_faq = True
        except Exception:
            continue

    if not has_article:
        issues.append("Missing Article or BlogPosting Schema structured data")
        action_items.append(IssueItem(
            link="schema.org/BlogPosting", anchor="ld+json",
            problem="Missing Article/BlogPosting Schema structured data",
            fix="Add JSON-LD BlogPosting or Article Schema with headline, author, and dates"
        ))
    else:
        if not dates.get("datePublished"):
            issues.append("Article schema missing datePublished")
        if not dates.get("dateModified"):
            issues.append("Article schema missing dateModified")
        if not has_author:
            issues.append("Article schema missing author specification")

    status = "PASS" if has_article and len(issues) == 0 else ("WARN" if has_article else "FAIL")
    return SchemaValidationResult(
        status=status,
        schema_types_found=list(set(schema_types)),
        has_article_schema=has_article,
        article_type=article_type,
        has_faq_schema=has_faq,
        dates_present=dates,
        has_author=has_author,
        issues=issues
    ), action_items


def evaluate_faq_section(
    soup: BeautifulSoup,
    has_faq_schema: bool
) -> tuple[FAQSectionResult, List[IssueItem]]:
    headings = soup.find_all(re.compile(r"^h[2-4]$"))
    faq_heading = None
    for h in headings:
        text = h.get_text().strip()
        if re.search(r"\bfaqs?\b", text, re.I) or "frequently asked" in text.lower():
            faq_heading = text
            break

    issues: List[str] = []
    action_items: List[IssueItem] = []

    if faq_heading:
        if not has_faq_schema:
            issues.append("FAQ section found in content, but missing FAQPage Schema markup")
            action_items.append(IssueItem(
                link="schema.org/FAQPage", anchor=faq_heading[:30],
                problem="FAQ section exists on page but has no FAQPage JSON-LD schema",
                fix="Implement FAQPage Schema structured data to earn Google SERP FAQ rich snippets"
            ))
            status = "WARN"
        else:
            status = "PASS"
    else:
        status = "PASS" if has_faq_schema else "PASS"

    return FAQSectionResult(
        status=status,
        faq_section_found=bool(faq_heading),
        faq_schema_present=has_faq_schema,
        heading_text=faq_heading,
        issues=issues
    ), action_items


def evaluate_key_takeaways(
    body_container,
    primary_keyword: str
) -> tuple[KeyTakeawaysResult, List[IssueItem]]:
    kw_lower = primary_keyword.lower().strip()
    headings = body_container.find_all(re.compile(r"^h[2-4]$")) if body_container else []
    
    takeaways_heading = None
    section_container = None

    for h in headings:
        t = h.get_text().strip().lower()
        if any(term in t for term in ("key takeaways", "takeaways", "summary", "tl;dr", "quick overview", "main points")):
            takeaways_heading = h.get_text().strip()
            # Look at immediate siblings or parent block
            section_container = h.find_next_sibling()
            break

    issues: List[str] = []
    action_items: List[IssueItem] = []
    has_kw = False

    if takeaways_heading:
        section_text = section_container.get_text().lower() if section_container else ""
        has_kw = kw_lower in section_text
        if not has_kw:
            issues.append(f"Key Takeaways section found, but does not mention primary keyword '{primary_keyword}'")
            action_items.append(IssueItem(
                link="Takeaways", anchor=takeaways_heading[:30],
                problem="Key Takeaways section missing primary keyword",
                fix=f"Include primary keyword '{primary_keyword}' in key takeaways bullet points"
            ))
            status = "WARN"
        else:
            status = "PASS"
    else:
        issues.append("No 'Key Takeaways' or 'Summary' section detected")
        action_items.append(IssueItem(
            link="Takeaways", anchor="None",
            problem="No Key Takeaways section found",
            fix="Add a 'Key Takeaways' bullet section near the top with primary keyword for AI Overviews & user retention"
        ))
        status = "WARN"

    return KeyTakeawaysResult(
        status=status,
        takeaways_section_found=bool(takeaways_heading),
        has_keyword=has_kw,
        heading_text=takeaways_heading,
        issues=issues
    ), action_items


async def run_phase2_audit(
    soup: BeautifulSoup,
    body_container,
    page_url: str,
    primary_keyword: str,
    client: Optional[httpx.AsyncClient] = None
) -> tuple[Phase2Checks, List[IssueItem]]:
    all_action_items: List[IssueItem] = []

    # 1. Title & Meta
    title_meta, tm_items = evaluate_title_and_meta(soup, primary_keyword)
    all_action_items.extend(tm_items)

    # 2. Heading hierarchy
    heading_res, hh_items = evaluate_heading_hierarchy(soup)
    all_action_items.extend(hh_items)

    # 3. Images
    image_res, img_items = await evaluate_images(body_container, page_url, client)
    all_action_items.extend(img_items)

    # 4. Schema validation
    schema_res, schema_items = evaluate_schema_structured_data(soup)
    all_action_items.extend(schema_items)

    # 5. FAQ section + Schema match
    faq_res, faq_items = evaluate_faq_section(soup, schema_res.has_faq_schema)
    all_action_items.extend(faq_items)

    # 6. Key Takeaways
    takeaways_res, tk_items = evaluate_key_takeaways(body_container, primary_keyword)
    all_action_items.extend(tk_items)

    phase2_checks = Phase2Checks(
        title_meta=title_meta,
        heading_hierarchy=heading_res,
        image_audit=image_res,
        schema_validation=schema_res,
        faq_check=faq_res,
        key_takeaways=takeaways_res
    )

    return phase2_checks, all_action_items

