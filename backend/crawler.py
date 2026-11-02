import asyncio
import re
import xml.etree.ElementTree as ET
from urllib.parse import urlparse, urljoin
from typing import List, Dict, Set, Any
import httpx
from bs4 import BeautifulSoup

from backend.utils import normalize_url, clean_domain
from backend.database import get_cached_pages_for_site, save_page_crawl

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
}


async def discover_sitemap_urls(site_url: str, client: httpx.AsyncClient) -> List[str]:
    """Finds sitemaps from robots.txt or common default locations."""
    parsed = urlparse(site_url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    found_sitemaps = []

    # Check robots.txt first
    try:
        r = await client.get(f"{base}/robots.txt", timeout=6.0, follow_redirects=True)
        if r.status_code == 200:
            for line in r.text.splitlines():
                if line.lower().startswith("sitemap:"):
                    s_url = line.split(":", 1)[1].strip()
                    if s_url and s_url not in found_sitemaps:
                        found_sitemaps.append(s_url)
    except Exception:
        pass

    # Common candidates
    candidates = [
        f"{base}/sitemap.xml",
        f"{base}/sitemap_index.xml",
        f"{base}/blog-sitemap.xml",
        f"{base}/post-sitemap.xml"
    ]
    for c in candidates:
        if c not in found_sitemaps:
            found_sitemaps.append(c)

    return found_sitemaps


def parse_xml_locs(xml_content: str) -> tuple[List[str], List[str]]:
    """
    Returns (page_locs, sub_sitemap_locs)
    """
    page_locs = []
    sub_sitemaps = []
    
    # Strip namespaces for easier parsing
    clean_xml = re.sub(r'\sxmlns(?::\w+)?="[^"]*"', '', xml_content, count=1)
    try:
        root = ET.fromstring(clean_xml)
        # Check if sitemapindex
        for sitemap in root.findall(".//sitemap"):
            loc = sitemap.find("loc")
            if loc is not None and loc.text:
                sub_sitemaps.append(loc.text.strip())
                
        # Check if urlset
        for url_tag in root.findall(".//url"):
            loc = url_tag.find("loc")
            if loc is not None and loc.text:
                page_locs.append(loc.text.strip())
    except Exception:
        # Fallback to regex if XML parse error
        locs = re.findall(r'<loc>(https?://[^<]+)</loc>', xml_content)
        for l in locs:
            if "sitemap" in l.lower() and l.endswith(".xml"):
                sub_sitemaps.append(l)
            else:
                page_locs.append(l)
                
    return page_locs, sub_sitemaps


async def fetch_urls_from_sitemaps(site_url: str, max_urls: int = 60) -> List[str]:
    """Retrieves blog/article URLs from site sitemaps."""
    discovered_urls: Set[str] = set()
    async with httpx.AsyncClient(headers=HEADERS, timeout=8.0, follow_redirects=True) as client:
        candidate_sitemaps = await discover_sitemap_urls(site_url, client)
        
        for sitemap_url in candidate_sitemaps:
            if len(discovered_urls) >= max_urls:
                break
            try:
                r = await client.get(sitemap_url)
                if r.status_code == 200:
                    pages, sub_sitemaps = parse_xml_locs(r.text)
                    
                    # If sub_sitemaps found, process blog/post ones first
                    blog_sub = [s for s in sub_sitemaps if "blog" in s.lower() or "post" in s.lower()]
                    target_subs = blog_sub if blog_sub else sub_sitemaps[:3]
                    
                    for sub in target_subs:
                        if len(discovered_urls) >= max_urls:
                            break
                        try:
                            sub_r = await client.get(sub)
                            if sub_r.status_code == 200:
                                sub_pages, _ = parse_xml_locs(sub_r.text)
                                for p in sub_pages:
                                    discovered_urls.add(p)
                                    if len(discovered_urls) >= max_urls:
                                        break
                        except Exception:
                            continue

                    for p in pages:
                        discovered_urls.add(p)
                        if len(discovered_urls) >= max_urls:
                            break
            except Exception:
                continue

    # Filter prioritized for blogs if available
    url_list = list(discovered_urls)
    blog_urls = [u for u in url_list if "/blog" in u.lower() or "/post" in u.lower() or "/article" in u.lower()]
    return blog_urls if blog_urls else url_list[:max_urls]


async def extract_links_from_page(url: str, client: httpx.AsyncClient) -> List[str]:
    """Fetches a page and returns all normalized outgoing hrefs found in its content."""
    try:
        r = await client.get(url, timeout=7.0)
        if r.status_code != 200 or "text/html" not in r.headers.get("content-type", ""):
            return []
        
        soup = BeautifulSoup(r.text, "lxml")
        container = soup.select_one("article, main, [role='main'], .post-content, .entry-content, #content") or soup.body
        if not container:
            return []
            
        out_links = []
        for a in container.select("a[href]"):
            raw_href = a.get("href", "")
            if raw_href and not raw_href.startswith(("#", "mailto:", "tel:", "javascript:")):
                normalized = normalize_url(raw_href, base_url=url)
                if normalized:
                    out_links.append(normalized)
        return list(set(out_links))
    except Exception:
        return []


async def scan_incoming_internal_links(
    site_url: str,
    target_page_url: str,
    max_crawl_pages: int = 50,
    force_refresh: bool = False
) -> Dict[str, Any]:
    """
    Checks how many blog pages from site_url link to target_page_url.
    Uses SQLite 24-hour cache per site to minimize network calls.
    """
    site_domain = clean_domain(urlparse(site_url).netloc)
    normalized_target = normalize_url(target_page_url)
    
    # 1. Check local cache first
    cached_pages = get_cached_pages_for_site(site_domain, max_age_hours=24)
    
    # If cache has sufficient scanned pages and not force_refresh, compute from cache
    if cached_pages and len(cached_pages) >= 5 and not force_refresh:
        referring_urls = []
        for p in cached_pages:
            source_page = normalize_url(p["page_url"])
            if source_page != normalized_target:
                # Check if target is in outgoing links
                if normalized_target in p["out_links"]:
                    referring_urls.append(p["page_url"])
                    
        return {
            "count": len(referring_urls),
            "referring_urls": referring_urls,
            "required": 5,
            "passed": len(referring_urls) >= 5,
            "pages_analyzed": len(cached_pages),
            "source": "cache (24h TTL)"
        }

    # 2. Need to crawl or refresh
    blog_urls = await fetch_urls_from_sitemaps(site_url, max_urls=max_crawl_pages)
    
    # Don't crawl the target page itself as a source
    pages_to_crawl = [u for u in blog_urls if normalize_url(u) != normalized_target][:max_crawl_pages]
    
    referring_urls = []
    analyzed_count = 0

    if pages_to_crawl:
        async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True) as client:
            # Crawl with concurrency limit of 5
            semaphore = asyncio.Semaphore(5)

            async def crawl_worker(url: str):
                nonlocal analyzed_count
                async with semaphore:
                    links = await extract_links_from_page(url, client)
                    if links:
                        save_page_crawl(site_domain, url, links)
                        analyzed_count += 1
                        if normalized_target in links:
                            referring_urls.append(url)

            tasks = [crawl_worker(u) for u in pages_to_crawl]
            await asyncio.gather(*tasks, return_exceptions=True)

    return {
        "count": len(referring_urls),
        "referring_urls": referring_urls,
        "required": 5,
        "passed": len(referring_urls) >= 5,
        "pages_analyzed": analyzed_count or len(pages_to_crawl),
        "source": "live sitemap crawl"
    }

