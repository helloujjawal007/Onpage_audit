#!/usr/bin/env python3
"""
SEO Link & Keyword Checker CLI Tool
Command line interface to audit live URLs against the SEO checklist.
"""

import sys
import asyncio
import argparse
import json
from backend.checker import run_full_check
from backend.models import CheckRequest


async def main():
    parser = argparse.ArgumentParser(description="SEO Link & Keyword Checker CLI")
    parser.add_argument("--site", required=True, help="Base Site URL (e.g. https://signeasy.com)")
    parser.add_argument("--url", required=True, help="Live Page URL to audit")
    parser.add_argument("--kw", required=True, help="Primary Keyword")
    parser.add_argument("--product-url", default=None, help="Product Page URL")
    parser.add_argument("--product-anchors", default="", help="Comma-separated product anchor keywords")
    parser.add_argument("--subdomains", default="", help="Comma-separated internal subdomains")
    parser.add_argument("--country", default="us", help="Country code for KD (default: us)")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    parser.add_argument("--csv", default=None, help="Save CSV report to filepath")

    args = parser.parse_args()

    product_anchors = [a.strip() for a in args.product_anchors.split(",") if a.strip()]
    subdomains = [s.strip() for s in args.subdomains.split(",") if s.strip()]

    req = CheckRequest(
        site_url=args.site,
        page_url=args.url,
        primary_keyword=args.kw,
        product_page_url=args.product_url,
        product_anchor_keywords=product_anchors,
        internal_subdomains=subdomains,
        country=args.country
    )

    print(f"\n🔍 Running SEO Audit for: {args.url}")
    print(f"Target Keyword: '{args.kw}' | Base Site: {args.site}\n")

    res = await run_full_check(req)

    if args.json:
        print(json.dumps(res.model_dump(), indent=2))
        return

    # Formatted terminal output
    print("=" * 65)
    print(f"Site: {res.site_url}")
    print(f"URL: {res.page_url}")
    print(f"Keyword: \"{res.primary_keyword}\"  |  KD: {res.check_d_kd.kd} ({res.check_d_kd.source})  |  Vol: {res.check_d_kd.volume:,}")
    print(f"Live Status: {'LIVE (200 OK)' if res.live_gate.is_live else 'FAILED (' + str(res.live_gate.status_code) + ')'}")
    print("=" * 65)

    checks = [
        ("A. Links open in new tab", res.check_a_new_tab),
        ("B. Nofollow / dofollow", res.check_b_follow),
        ("C1. Internal links on page", res.check_c1_internal_outgoing),
        ("C2. Incoming internal links", res.check_c2_incoming_links),
        ("C3. Product page link + anchor", res.check_c3_product_link),
        ("C4. Bad anchors", res.check_c4_anchor_quality),
        ("C5. Duplicate links", res.check_c5_duplicates),
        ("D. Keyword in URL / H1 / H2", SubCheckDisplay(res.check_d_onpage.status, f"Density: {res.check_d_onpage.keyword_density}%")),
    ]

    if res.phase2:
        p2 = res.phase2
        checks.extend([
            ("P2. Title & Meta (Length/Px)", SubCheckDisplay(p2.title_meta.status, f"{p2.title_meta.title_char_length}c (~{p2.title_meta.title_pixel_width}px) | Meta: {p2.title_meta.meta_char_length}c")),
            ("P2. Heading Hierarchy (H1/H2)", SubCheckDisplay(p2.heading_hierarchy.status, f"H1 count: {p2.heading_hierarchy.h1_count} | Total: {p2.heading_hierarchy.total_headings}")),
            ("P2. Images (Alt text & WebP)", SubCheckDisplay(p2.image_audit.status, f"Total: {p2.image_audit.total_images} | Non-WebP: {p2.image_audit.non_webp_count} | No Alt: {p2.image_audit.missing_alt_count}")),
            ("P2. Schema (Article/Dates)", SubCheckDisplay(p2.schema_validation.status, f"Type: {p2.schema_validation.article_type or 'None'}")),
            ("P2. FAQ Section & Schema", SubCheckDisplay(p2.faq_check.status, f"Section: {'Yes' if p2.faq_check.faq_section_found else 'No'} | Schema: {'Yes' if p2.faq_check.faq_schema_present else 'No'}")),
            ("P2. Key Takeaways Section", SubCheckDisplay(p2.key_takeaways.status, f"Found: {'Yes' if p2.key_takeaways.takeaways_section_found else 'No'} | KW: {'Yes' if p2.key_takeaways.has_keyword else 'No'}")),
        ])

    print(f"{'CHECK':<35} {'RESULT':<10} {'DETAILS'}")
    print("-" * 65)
    for name, c in checks:
        status_color = "\033[92mPASS\033[0m" if c.status == "PASS" else ("\033[93mWARN\033[0m" if c.status == "WARN" else "\033[91mFAIL\033[0m")
        summary = getattr(c, "summary", "")
        print(f"{name:<35} {status_color:<18} {summary}")
    print("=" * 65)

    if res.failed_issues:
        print(f"\n⚠️  {len(res.failed_issues)} ACTIONABLE ISSUES FOUND:")
        print(f"{'LINK':<30} {'ANCHOR':<15} {'PROBLEM':<30} {'FIX'}")
        print("-" * 90)
        for issue in res.failed_issues:
            short_link = issue.link if len(issue.link) <= 28 else issue.link[:25] + "..."
            short_anchor = issue.anchor if len(issue.anchor) <= 13 else issue.anchor[:12] + "..."
            print(f"{short_link:<30} {short_anchor:<15} {issue.problem:<30} {issue.fix}")
        print("-" * 90)
    else:
        print("\n🎉 ALL CHECKLIST CRITERIA PASSED! No issues found.\n")

    if args.csv:
        import csv
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["Link", "Anchor", "Problem", "Fix"])
            for i in res.failed_issues:
                writer.writerow([i.link, i.anchor, i.problem, i.fix])
        print(f"📁 CSV exported to: {args.csv}\n")


class SubCheckDisplay:
    def __init__(self, status, summary):
        self.status = status
        self.summary = summary


if __name__ == "__main__":
    asyncio.run(main())

