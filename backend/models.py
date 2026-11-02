from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field


class CheckRequest(BaseModel):
    site_url: str = Field(..., description="Base site URL, e.g. https://signeasy.com")
    page_url: str = Field(..., description="Page URL to audit, e.g. https://signeasy.com/blog/business/is-docusign-free")
    primary_keyword: str = Field(..., description="Primary keyword, e.g. 'is docusign free'")
    product_page_url: Optional[str] = Field(None, description="Optional product page URL, e.g. https://signeasy.com/electronic-signature-software")
    product_anchor_keywords: Optional[List[str]] = Field(default_factory=list, description="Keywords for product anchor check")
    internal_subdomains: Optional[List[str]] = Field(default_factory=list, description="Internal subdomains like app.signeasy.com")
    country: str = Field("us", description="Country/location code for KD (default: us)")
    custom_body_selector: Optional[str] = Field(None, description="Optional CSS selector for main blog article body")


class IssueItem(BaseModel):
    link: str
    anchor: str
    problem: str
    fix: str


class LinkDetail(BaseModel):
    href: str
    raw_href: str
    anchor: str
    is_external: bool
    is_product_page: bool
    new_tab: bool
    has_noopener: bool
    rel_tags: List[str]
    nofollow: bool
    follow_ok: bool
    expected_follow: Optional[str] = None  # "dofollow", "nofollow", or None for internal
    actual_follow: str  # "dofollow" or "nofollow"
    bad_anchor: bool
    bad_anchor_reason: Optional[str] = None
    duplicate: bool
    issues: List[IssueItem] = Field(default_factory=list)


class LiveGateResult(BaseModel):
    is_live: bool
    status_code: int
    content_type: str
    redirect_chain: List[str] = Field(default_factory=list)
    final_url: str
    is_redirected: bool = False
    noindex: bool = False
    canonical_url: Optional[str] = None
    is_self_canonical: Optional[bool] = None
    message: str


class SubCheckResult(BaseModel):
    name: str
    status: str  # "PASS", "FAIL", "WARN", "SKIPPED"
    summary: str
    details: Optional[str] = None
    score_or_count: Optional[Any] = None


class KDResult(BaseModel):
    keyword: str
    kd: Optional[int] = None
    volume: Optional[int] = None
    cpc: Optional[float] = None
    source: str = "Estimator"
    country: str = "us"


class OnPageKeywordResult(BaseModel):
    status: str  # "PASS", "FAIL", "WARN"
    in_slug: bool
    h1_count: int
    h1_has_keyword: bool
    h2_has_keyword: bool
    first_p_has_keyword: bool
    keyword_count: int
    total_words: int
    keyword_density: float
    issues: List[str] = Field(default_factory=list)


# Phase 2 Models
class TitleMetaCheckResult(BaseModel):
    status: str  # "PASS", "WARN", "FAIL"
    title: Optional[str] = None
    title_char_length: int = 0
    title_pixel_width: int = 0
    title_has_keyword: bool = False
    meta_description: Optional[str] = None
    meta_char_length: int = 0
    meta_pixel_width: int = 0
    meta_has_keyword: bool = False
    issues: List[str] = Field(default_factory=list)


class HeadingHierarchyResult(BaseModel):
    status: str  # "PASS", "WARN", "FAIL"
    h1_count: int = 0
    h1_text: Optional[str] = None
    total_headings: int = 0
    hierarchy_valid: bool = True
    issues: List[str] = Field(default_factory=list)


class ImageAuditItem(BaseModel):
    src: str
    alt: str
    format: str
    is_webp_or_modern: bool
    size_kb: Optional[float] = None
    issues: List[str] = Field(default_factory=list)


class ImageAuditResult(BaseModel):
    status: str  # "PASS", "WARN", "FAIL"
    total_images: int = 0
    missing_alt_count: int = 0
    non_webp_count: int = 0
    large_image_count: int = 0
    images: List[ImageAuditItem] = Field(default_factory=list)
    issues: List[str] = Field(default_factory=list)


class SchemaValidationResult(BaseModel):
    status: str  # "PASS", "WARN", "FAIL"
    schema_types_found: List[str] = Field(default_factory=list)
    has_article_schema: bool = False
    article_type: Optional[str] = None
    has_faq_schema: bool = False
    dates_present: Dict[str, Optional[str]] = Field(default_factory=dict)
    has_author: bool = False
    issues: List[str] = Field(default_factory=list)


class FAQSectionResult(BaseModel):
    status: str  # "PASS", "WARN", "FAIL"
    faq_section_found: bool = False
    faq_schema_present: bool = False
    heading_text: Optional[str] = None
    issues: List[str] = Field(default_factory=list)


class KeyTakeawaysResult(BaseModel):
    status: str  # "PASS", "WARN", "FAIL"
    takeaways_section_found: bool = False
    has_keyword: bool = False
    heading_text: Optional[str] = None
    issues: List[str] = Field(default_factory=list)


class Phase2Checks(BaseModel):
    title_meta: TitleMetaCheckResult
    heading_hierarchy: HeadingHierarchyResult
    image_audit: ImageAuditResult
    schema_validation: SchemaValidationResult
    faq_check: FAQSectionResult
    key_takeaways: KeyTakeawaysResult


class CheckResponse(BaseModel):
    id: str
    timestamp: str
    site_url: str
    page_url: str
    primary_keyword: str
    live_gate: LiveGateResult
    check_a_new_tab: SubCheckResult
    check_b_follow: SubCheckResult
    check_c1_internal_outgoing: SubCheckResult
    check_c2_incoming_links: SubCheckResult
    check_c3_product_link: SubCheckResult
    check_c4_anchor_quality: SubCheckResult
    check_c5_duplicates: SubCheckResult
    check_d_kd: KDResult
    check_d_onpage: OnPageKeywordResult
    phase2: Optional[Phase2Checks] = None
    overall_pass: bool
    total_links: int
    internal_links_count: int
    external_links_count: int
    failed_issues: List[IssueItem] = Field(default_factory=list)
    all_links: List[LinkDetail] = Field(default_factory=list)


class SiteProfile(BaseModel):
    site_url: str
    product_page_url: Optional[str] = None
    product_anchor_keywords: List[str] = Field(default_factory=list)
    internal_subdomains: List[str] = Field(default_factory=list)
    country: str = "us"
    custom_body_selector: Optional[str] = None
