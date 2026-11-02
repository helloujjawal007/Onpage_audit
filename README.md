# SEO Link & Keyword Checker Tool

Automated SEO checklist validator that audits live blog URLs against link rules, keyword presence, and Keyword Difficulty (KD).

---

## 🚀 Quick Start

### 1. Start the Web UI & API Server
```bash
./run.sh
```
Or manually:
```bash
source venv/bin/activate
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```
Open **[http://localhost:8000](http://localhost:8000)** in your browser.

---

### 2. Run Audits via CLI
```bash
source venv/bin/activate
python3 cli.py \
  --site "https://signeasy.com" \
  --url "https://signeasy.com/blog/business/is-docusign-free" \
  --kw "is docusign free" \
  --product-url "https://signeasy.com/electronic-signature-software" \
  --product-anchors "eSignature software, eSign tool" \
  --csv report.csv
```

---

## 📋 Checks Covered (Phase 1 MVP)

### **Rule #0: Live Gate**
- HTTP GET with browser User-Agent (`Mozilla/5.0...`) & 15s timeout.
- Validates **HTTP 200 OK**. If redirected (301/302), tracks hops and final destination URL.
- Flags `<meta name="robots" content="noindex">` or `X-Robots-Tag: noindex`.
- Verifies canonical tag (`is_self_canonical`).
- Validates `Content-Type: text/html`.

### **Check A: New Tab (`target="_blank"`)**
- Scopes links strictly to the article body container (`article`, `main`, `.post-content`, excluding navigation, headers, footers, and sidebars).
- Confirms every link contains `target="_blank"` and `rel="noopener noreferrer"`.

### **Check B: Follow / Nofollow**
- External links to standard commercial sites must have `rel="nofollow"`.
- External links to reputable authority sites (`.org`, `.gov`, `.gov.in`, `.edu`, Wikipedia, etc.) are expected to be **dofollow**.
- Whitelist configurable in `config/reputable_domains.json`.

### **Check C: Internal Linking**
- **C1. Outgoing internal links**: Verifies at least 1 unique outgoing link to the parent site domain or configured internal subdomains.
- **C2. Incoming internal links (5+ Rule)**: Discovers blog URLs via site sitemap (`/sitemap.xml`, `/sitemap_index.xml`), checks that >= 5 unique published blogs link to this target URL, and caches crawl results in SQLite (24-hour TTL per site).
- **C3. Product page link**: Verifies link to the specified product page URL and checks that anchor text contains designated product keywords.
- **C4. Anchor quality**: Prohibits generic anchors (`here`, `click here`, `read more`, `this`) and naked URLs (`http://...`).
- **C5. Duplicate links**: Normalizes URLs (stripping query tracking params and hash fragments) to flag redundant duplicate links.

### **Check D: Keyword & KD**
- **Keyword Difficulty & Search Volume**: Pluggable provider architecture. Supports **DataForSEO**, **Semrush**, or built-in **Offline Estimator** when API keys are not provided.
- **On-Page Keyword Signals**: Checks presence in URL slug, exactly 1 H1 heading, at least 1 H2 heading, first paragraph, and keyword density (~0.5%).

---

## ⚙️ Configuration & Customization

| Configuration File | Purpose |
|---|---|
| `config/reputable_domains.json` | Allowed TLDs (`.org`, `.gov`, `.edu`) and reputable authority domains (`wikipedia.org`, `w3.org`, etc.). |
| `config/bad_anchors.json` | Prohibited generic anchor words (`here`, `click here`, `link`, etc.). |
| `config/site_profiles.json` | Default site profiles (e.g. Signeasy product URL, anchor keywords, internal subdomains). |

### Optional Third-Party API Keys (for Live KD):
To use live Semrush or DataForSEO data instead of the offline estimator:
```bash
# In your terminal or .env file:
export SEMRUSH_API_KEY="your_semrush_key"

# OR DataForSEO:
export DATAFORSEO_LOGIN="your_login"
export DATAFORSEO_PASSWORD="your_password"
```

---

## 🧪 Running Automated Tests
```bash
source venv/bin/activate
PYTHONPATH=. pytest -v
```
All 11 unit & integration tests verify domain validation, URL normalization, anchor checks, live gate, full audits, and API endpoints.

---

## 📊 CSV Export & Reporting
- Every audit can be downloaded as a **CSV report** (`/api/export/{check_id}/csv`) containing:
  - Header & KD metadata
  - Checklist Pass/Fail summary
  - Actionable issues table (`Link`, `Anchor`, `Problem`, `Suggested Fix`)
  - Complete link inventory (Destination, Anchor, Type, Target Blank, Follow status)
