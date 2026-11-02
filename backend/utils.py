import re
from urllib.parse import urlparse, urlunparse, urljoin, parse_qsl, urlencode
from typing import List, Dict, Any, Optional

TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "utm_id", "gclid", "fbclid", "mc_cid", "mc_eid", "yclid", "_hsenc", "_hsmi"
}

IGNORED_SCHEMES = {"mailto", "tel", "javascript", "data", "whatsapp", "sms"}


def clean_domain(netloc: str) -> str:
    """Normalize netloc: lowercased, port removed, leading 'www.' removed."""
    if not netloc:
        return ""
    host = netloc.lower().split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    return host


def normalize_url(url: str, base_url: Optional[str] = None) -> str:
    """
    Normalizes a URL:
    - Resolves relative URLs if base_url is provided
    - Converts scheme and host to lowercase
    - Strips 'www.' for consistency
    - Removes `#fragments`
    - Removes tracking query params (utm_*, etc.)
    - Removes trailing slashes (except root path '/')
    """
    if not url:
        return ""
    
    url = url.strip()
    if base_url:
        url = urljoin(base_url, url)
    
    parsed = urlparse(url)
    if parsed.scheme in IGNORED_SCHEMES:
        return url

    scheme = parsed.scheme.lower() or "https"
    netloc = clean_domain(parsed.netloc)
    
    path = parsed.path
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    if not path:
        path = "/"
        
    # Filter out tracking query params, sort the rest
    query_params = parse_qsl(parsed.query, keep_blank_values=False)
    filtered_params = sorted([(k, v) for k, v in query_params if k.lower() not in TRACKING_PARAMS])
    query = urlencode(filtered_params)

    # Reconstruct without fragment
    return urlunparse((scheme, netloc, path, parsed.params, query, ""))


def is_valid_http_url(url: str) -> bool:
    if not url:
        return False
    parsed = urlparse(url)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def is_internal_url(url: str, site_url: str, internal_subdomains: Optional[List[str]] = None) -> bool:
    """
    Determines if URL belongs to the site or listed internal subdomains.
    """
    if not url:
        return False
    
    parsed_target = urlparse(url)
    if parsed_target.scheme in IGNORED_SCHEMES:
        return False
    
    target_host = clean_domain(parsed_target.netloc)
    site_host = clean_domain(urlparse(site_url).netloc)
    
    if not target_host or not site_host:
        return False
    
    if target_host == site_host:
        return True
    
    subdomain_list = [clean_domain(s) for s in (internal_subdomains or []) if s.strip()]
    if target_host in subdomain_list:
        return True
        
    return False


def is_reputable_external(domain: str, reputable_config: Dict[str, List[str]]) -> bool:
    """
    Checks if external domain should be DOFOLLOW:
    - TLD check (.org, .gov, .gov.in, .edu, etc.)
    - Domain whitelist check
    """
    if not domain:
        return False
    
    domain_clean = domain.lower().split(":")[0]
    
    # Check TLDs
    tlds = reputable_config.get("tlds", [])
    for tld in tlds:
        tld_clean = tld.lower()
        if domain_clean.endswith(tld_clean):
            return True
            
    # Check specific domains
    domains = reputable_config.get("domains", [])
    for d in domains:
        d_clean = clean_domain(d)
        if domain_clean == d_clean or domain_clean.endswith("." + d_clean):
            return True
            
    return False


def clean_anchor_text(text: Optional[str]) -> str:
    if not text:
        return ""
    # Collapse multiple whitespaces/newlines into a single space
    return re.sub(r"\s+", " ", text).strip()


def is_naked_url(text: str, href: str) -> bool:
    if not text:
        return False
    t = text.lower().strip()
    if t.startswith("http://") or t.startswith("https://") or t.startswith("www."):
        return True
    h = href.lower().strip()
    if t == h or t == clean_domain(urlparse(h).netloc):
        return True
    return False


def check_anchor_quality(text: str, href: str, bad_anchors: List[str]) -> tuple[bool, Optional[str]]:
    """
    Returns (is_bad, reason)
    """
    cleaned = clean_anchor_text(text)
    if not cleaned:
        return True, "Empty anchor text"
    
    if is_naked_url(cleaned, href):
        return True, "Naked link (anchor is a raw URL)"
        
    cleaned_lower = cleaned.lower()
    for bad in bad_anchors:
        bad_clean = bad.lower().strip()
        if cleaned_lower == bad_clean:
            return True, f"Generic anchor text: '{cleaned}'"
            
    return False, None
