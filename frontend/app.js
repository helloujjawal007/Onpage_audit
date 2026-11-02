// Frontend JavaScript for SEO Link & Keyword Checker Tool

let currentAuditData = null;
let savedProfiles = {};
let activeInventoryFilter = "all";

document.addEventListener("DOMContentLoaded", async () => {
  setupEventListeners();
  await loadProfiles();
});

function setupEventListeners() {
  const auditForm = document.getElementById("auditForm");
  const profileSelect = document.getElementById("profileSelect");
  const saveProfileBtn = document.getElementById("saveProfileBtn");
  const toggleAdvancedBtn = document.getElementById("toggleAdvancedBtn");
  const advancedFields = document.getElementById("advancedFields");
  const advIcon = document.getElementById("advIcon");
  const downloadCsvBtn = document.getElementById("downloadCsvBtn");
  const copyJsonBtn = document.getElementById("copyJsonBtn");
  const historyBtn = document.getElementById("historyBtn");
  const historyModal = document.getElementById("historyModal");
  const closeHistoryBtn = document.getElementById("closeHistoryBtn");

  // Toggle Advanced Settings
  toggleAdvancedBtn.addEventListener("click", () => {
    const isHidden = advancedFields.classList.contains("hidden");
    if (isHidden) {
      advancedFields.classList.remove("hidden");
      advIcon.classList.replace("fa-chevron-right", "fa-chevron-down");
    } else {
      advancedFields.classList.add("hidden");
      advIcon.classList.replace("fa-chevron-down", "fa-chevron-right");
    }
  });

  // Profile select change
  profileSelect.addEventListener("change", (e) => {
    const domain = e.target.value;
    if (domain && savedProfiles[domain]) {
      applyProfile(savedProfiles[domain]);
    }
  });

  // Save current form as profile
  saveProfileBtn.addEventListener("click", async () => {
    const siteUrl = document.getElementById("siteUrl").value.trim();
    if (!siteUrl) {
      alert("Please enter a Site URL first to save its preset.");
      return;
    }
    const profile = {
      site_url: siteUrl,
      product_page_url: document.getElementById("productPageUrl").value.trim() || null,
      product_anchor_keywords: parseList(document.getElementById("productAnchors").value),
      internal_subdomains: parseList(document.getElementById("internalSubdomains").value),
      country: document.getElementById("countryLocation").value || "us",
      custom_body_selector: document.getElementById("customSelector").value.trim() || null
    };

    try {
      const res = await fetch("/api/profiles", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(profile)
      });
      if (res.ok) {
        alert("Site preset saved successfully!");
        await loadProfiles();
      } else {
        const err = await res.json();
        alert("Failed to save preset: " + (err.detail || "Unknown error"));
      }
    } catch (e) {
      alert("Error saving profile: " + e.message);
    }
  });

  // Form Submit
  auditForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    await runAudit();
  });

  // Download CSV
  downloadCsvBtn.addEventListener("click", () => {
    if (currentAuditData && currentAuditData.id) {
      window.location.href = `/api/export/${currentAuditData.id}/csv`;
    }
  });

  // Copy JSON
  copyJsonBtn.addEventListener("click", () => {
    if (currentAuditData) {
      navigator.clipboard.writeText(JSON.stringify(currentAuditData, null, 2));
      const orig = copyJsonBtn.innerHTML;
      copyJsonBtn.innerHTML = `<i class="fa-solid fa-check"></i><span>Copied!</span>`;
      setTimeout(() => copyJsonBtn.innerHTML = orig, 2000);
    }
  });

  // Link inventory filter buttons
  document.querySelectorAll(".filter-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".filter-btn").forEach(b => {
        b.classList.remove("active", "bg-white", "shadow-sm", "text-slate-800");
        b.classList.add("text-slate-600");
      });
      btn.classList.add("active", "bg-white", "shadow-sm", "text-slate-800");
      btn.classList.remove("text-slate-600");

      activeInventoryFilter = btn.dataset.filter;
      renderLinkInventory();
    });
  });

  // History Modal
  historyBtn.addEventListener("click", async () => {
    historyModal.classList.remove("hidden");
    await loadAuditHistory();
  });

  closeHistoryBtn.addEventListener("click", () => {
    historyModal.classList.add("hidden");
  });

  historyModal.addEventListener("click", (e) => {
    if (e.target === historyModal) {
      historyModal.classList.add("hidden");
    }
  });
}

function parseList(str) {
  if (!str) return [];
  return str.split(",").map(s => s.trim()).filter(Boolean);
}

async function loadProfiles() {
  try {
    const res = await fetch("/api/profiles");
    if (!res.ok) return;
    savedProfiles = await res.json();

    const select = document.getElementById("profileSelect");
    select.innerHTML = `<option value="">Custom Site</option>`;

    Object.keys(savedProfiles).forEach(domain => {
      const opt = document.createElement("option");
      opt.value = domain;
      opt.textContent = domain;
      select.appendChild(opt);
    });

    // Default to signeasy.com if available and inputs empty
    if (savedProfiles["signeasy.com"] && !document.getElementById("siteUrl").value) {
      select.value = "signeasy.com";
      applyProfile(savedProfiles["signeasy.com"]);
    }
  } catch (e) {
    console.error("Failed to load site profiles", e);
  }
}

function applyProfile(p) {
  if (!p) return;
  document.getElementById("siteUrl").value = p.site_url || "";
  document.getElementById("productPageUrl").value = p.product_page_url || "";
  document.getElementById("productAnchors").value = (p.product_anchor_keywords || []).join(", ");
  document.getElementById("internalSubdomains").value = (p.internal_subdomains || []).join(", ");
  document.getElementById("countryLocation").value = p.country || "us";
  document.getElementById("customSelector").value = p.custom_body_selector || "";
}

async function runAudit() {
  const siteUrl = document.getElementById("siteUrl").value.trim();
  const pageUrl = document.getElementById("pageUrl").value.trim();
  const keyword = document.getElementById("primaryKeyword").value.trim();
  const productUrl = document.getElementById("productPageUrl").value.trim();
  const productAnchors = parseList(document.getElementById("productAnchors").value);
  const internalSubdomains = parseList(document.getElementById("internalSubdomains").value);
  const country = document.getElementById("countryLocation").value || "us";
  const customSelector = document.getElementById("customSelector").value.trim() || null;

  const loadingState = document.getElementById("loadingState");
  const resultsSection = document.getElementById("resultsSection");
  const submitBtn = document.getElementById("submitBtn");

  submitBtn.disabled = true;
  loadingState.classList.remove("hidden");
  resultsSection.classList.add("hidden");

  const payload = {
    site_url: siteUrl,
    page_url: pageUrl,
    primary_keyword: keyword,
    product_page_url: productUrl || null,
    product_anchor_keywords: productAnchors,
    internal_subdomains: internalSubdomains,
    country: country,
    custom_body_selector: customSelector
  };

  try {
    const res = await fetch("/api/check", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });

    const data = await res.json();
    if (!res.ok) {
      alert("Error: " + (data.detail || "Server error while performing audit"));
      return;
    }

    currentAuditData = data;
    renderAuditResults(data);
    resultsSection.classList.remove("hidden");
    resultsSection.scrollIntoView({ behavior: "smooth" });
  } catch (err) {
    alert("Connection error: " + err.message);
  } finally {
    submitBtn.disabled = false;
    loadingState.classList.add("hidden");
  }
}

function renderAuditResults(d) {
  // 1. Overview Header
  document.getElementById("resSiteHost").textContent = d.site_url.replace(/^https?:\/\//, '').replace(/\/$/, '');
  document.getElementById("resTimestamp").textContent = new Date(d.timestamp).toLocaleString();
  document.getElementById("resPageTitle").textContent = d.page_url;
  document.getElementById("resKeyword").textContent = `KW: "${d.primary_keyword}"`;
  
  const kd = d.check_d_kd || {};
  document.getElementById("resKD").textContent = `KD: ${kd.kd ?? 'N/A'} (${kd.source || 'Estimator'})`;
  document.getElementById("resVolume").textContent = `Volume: ${(kd.volume ?? 0).toLocaleString()}/mo`;

  // Overall badge
  const overallBadge = document.getElementById("overallBadge");
  if (d.overall_pass) {
    overallBadge.textContent = "AUDIT PASSED";
    overallBadge.className = "px-5 py-2 rounded-xl text-sm font-extrabold tracking-wider uppercase shadow-sm bg-emerald-500 text-white";
  } else {
    overallBadge.textContent = "AUDIT FAILED (ISSUES FOUND)";
    overallBadge.className = "px-5 py-2 rounded-xl text-sm font-extrabold tracking-wider uppercase shadow-sm bg-rose-500 text-white";
  }

  // KPI cards
  const lg = d.live_gate || {};
  document.getElementById("kpiLiveStatus").textContent = lg.is_live ? `${lg.status_code} OK` : `FAIL (${lg.status_code || 0})`;
  
  const redirectTag = document.getElementById("kpiRedirectTag");
  if (lg.is_redirected) {
    redirectTag.classList.remove("hidden");
    redirectTag.textContent = `${lg.redirect_chain.length} Redirect(s)`;
  } else {
    redirectTag.classList.add("hidden");
  }

  const kpiCanonical = document.getElementById("kpiCanonical");
  if (lg.canonical_url) {
    kpiCanonical.textContent = lg.is_self_canonical ? "Self-canonical: Yes" : "Non-self canonical!";
    kpiCanonical.className = `text-[11px] mt-1 truncate ${lg.is_self_canonical ? 'text-slate-500' : 'text-amber-600 font-bold'}`;
  } else {
    kpiCanonical.textContent = "Canonical tag missing";
    kpiCanonical.className = "text-[11px] text-slate-400 mt-1";
  }

  document.getElementById("kpiTotalLinks").textContent = d.total_links;
  document.getElementById("kpiInternalLinks").textContent = d.internal_links_count;
  document.getElementById("kpiExternalLinks").textContent = d.external_links_count;

  const issuesCount = (d.failed_issues || []).length;
  const issuesEl = document.getElementById("kpiIssuesCount");
  issuesEl.textContent = `${issuesCount} Issue${issuesCount === 1 ? '' : 's'}`;
  issuesEl.className = `font-extrabold text-lg ${issuesCount === 0 ? 'text-emerald-600' : 'text-rose-600'}`;
  document.getElementById("issuesBadgeCount").textContent = issuesCount;

  // 2. Checklist Matrix
  renderChecklistMatrix(d);

  // 3. Actionable Issues Table
  renderActionableIssues(d.failed_issues || []);

  // 4. On-Page Keyword Signals
  renderOnPageSignals(d.check_d_onpage || {});

  // 5. Link Inventory
  updateInventoryCounts(d);
  renderLinkInventory();
}

function getBadgeHtml(status) {
  if (status === "PASS") return `<span class="px-2.5 py-1 text-xs font-bold rounded-lg badge-pass"><i class="fa-solid fa-check mr-1"></i>PASS</span>`;
  if (status === "FAIL") return `<span class="px-2.5 py-1 text-xs font-bold rounded-lg badge-fail"><i class="fa-solid fa-xmark mr-1"></i>FAIL</span>`;
  if (status === "WARN") return `<span class="px-2.5 py-1 text-xs font-bold rounded-lg badge-warn"><i class="fa-solid fa-triangle-exclamation mr-1"></i>WARN</span>`;
  return `<span class="px-2.5 py-1 text-xs font-bold rounded-lg badge-skip">SKIPPED</span>`;
}

function renderChecklistMatrix(d) {
  const matrix = document.getElementById("checklistMatrix");
  matrix.innerHTML = "";

  const items = [
    { id: "A", data: d.check_a_new_tab, desc: "All links in body open in new tab (target='_blank' + rel='noopener')" },
    { id: "B", data: d.check_b_follow, desc: "External links have nofollow; reputable domains (.org, .gov, .edu) are dofollow" },
    { id: "C1", data: d.check_c1_internal_outgoing, desc: "At least 1 outgoing link to an internal site page" },
    { id: "C2", data: d.check_c2_incoming_links, desc: "At least 5 existing published blogs link to this target page (sitemap crawl)" },
    { id: "C3", data: d.check_c3_product_link, desc: "Links to product page with natural keyword-rich anchor text" },
    { id: "C4", data: d.check_c4_anchor_quality, desc: "Prohibits generic anchors ('here', 'click here') and naked URL anchors" },
    { id: "C5", data: d.check_c5_duplicates, desc: "No duplicate links to identical URLs in the article body" }
  ];

  items.forEach(item => {
    const check = item.data || { name: item.id, status: "SKIPPED", summary: "No data" };
    const row = document.createElement("div");
    row.className = "px-6 py-4 flex flex-col sm:flex-row sm:items-center justify-between gap-4 hover:bg-slate-50/50 transition";
    row.innerHTML = `
      <div class="space-y-0.5">
        <div class="flex items-center space-x-2">
          <span class="font-bold text-slate-900 text-sm">${check.name || item.id}</span>
        </div>
        <p class="text-xs text-slate-500">${item.desc}</p>
        ${check.details ? `<p class="text-[11px] text-slate-400 font-mono mt-1">${escapeHtml(check.details)}</p>` : ''}
      </div>
      <div class="flex items-center space-x-4 self-start sm:self-center shrink-0">
        <span class="text-xs text-slate-600 font-medium">${escapeHtml(check.summary || '')}</span>
        ${getBadgeHtml(check.status)}
      </div>
    `;
    matrix.appendChild(row);
  });
}

function renderActionableIssues(issues) {
  const tbody = document.getElementById("issuesTableBody");
  tbody.innerHTML = "";

  if (issues.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="4" class="py-8 text-center text-slate-400">
          <i class="fa-regular fa-circle-check text-3xl text-emerald-500 mb-2 block"></i>
          <span class="font-medium">No SEO link issues detected! All checklist points passed.</span>
        </td>
      </tr>
    `;
    return;
  }

  issues.forEach(issue => {
    const tr = document.createElement("tr");
    tr.className = "hover:bg-slate-50 transition";
    tr.innerHTML = `
      <td class="py-3.5 px-6 font-mono text-xs text-slate-700 max-w-xs truncate" title="${escapeHtml(issue.link)}">
        <a href="${escapeHtml(issue.link)}" target="_blank" class="text-indigo-600 hover:underline">
          ${escapeHtml(issue.link)}
        </a>
      </td>
      <td class="py-3.5 px-6 font-semibold text-slate-900 text-xs">
        ${escapeHtml(issue.anchor || '(empty)')}
      </td>
      <td class="py-3.5 px-6 text-rose-600 font-semibold text-xs">
        <i class="fa-solid fa-circle-xmark mr-1"></i>${escapeHtml(issue.problem)}
      </td>
      <td class="py-3.5 px-6 text-emerald-700 font-semibold text-xs bg-emerald-50/40">
        <i class="fa-solid fa-wrench mr-1"></i>${escapeHtml(issue.fix)}
      </td>
    `;
    tbody.appendChild(tr);
  });
}

function renderOnPageSignals(op) {
  const badge = document.getElementById("onpageStatusBadge");
  badge.textContent = op.status || "SKIPPED";
  badge.className = `text-xs font-extrabold px-2.5 py-0.5 rounded-full ${
    op.status === "PASS" ? 'badge-pass' : (op.status === "WARN" ? 'badge-warn' : 'badge-fail')
  }`;

  document.getElementById("slugVal").innerHTML = op.in_slug ? 
    `<span class="text-emerald-600"><i class="fa-solid fa-check mr-1"></i>Found in slug</span>` : 
    `<span class="text-rose-500"><i class="fa-solid fa-xmark mr-1"></i>Missing from slug</span>`;

  document.getElementById("h1Val").innerHTML = (op.h1_count === 1 && op.h1_has_keyword) ?
    `<span class="text-emerald-600"><i class="fa-solid fa-check mr-1"></i>1 H1 with keyword</span>` :
    `<span class="text-rose-500"><i class="fa-solid fa-xmark mr-1"></i>${op.h1_count} H1 (${op.h1_has_keyword ? 'Has KW' : 'No KW'})</span>`;

  document.getElementById("h2Val").innerHTML = op.h2_has_keyword ?
    `<span class="text-emerald-600"><i class="fa-solid fa-check mr-1"></i>Found in H2</span>` :
    `<span class="text-rose-500"><i class="fa-solid fa-xmark mr-1"></i>Missing in H2</span>`;

  document.getElementById("firstPVal").innerHTML = op.first_p_has_keyword ?
    `<span class="text-emerald-600"><i class="fa-solid fa-check mr-1"></i>Found in 1st P</span>` :
    `<span class="text-rose-500"><i class="fa-solid fa-xmark mr-1"></i>Missing in 1st P</span>`;

  document.getElementById("densityVal").innerHTML = `
    <span class="${op.keyword_density >= 0.5 ? 'text-emerald-600' : 'text-amber-600'} font-bold">
      ${op.keyword_density}%
    </span>
    <span class="text-slate-400 font-normal">(${op.keyword_count || 0} in ${op.total_words || 0}w)</span>
  `;

  const issuesList = document.getElementById("onpageIssuesList");
  if (op.issues && op.issues.length > 0) {
    issuesList.classList.remove("hidden");
    issuesList.innerHTML = op.issues.map(i => `<div>• ${escapeHtml(i)}</div>`).join("");
  } else {
    issuesList.classList.add("hidden");
  }
}

function updateInventoryCounts(d) {
  const links = d.all_links || [];
  document.getElementById("countAll").textContent = links.length;
  document.getElementById("countFilterIssues").textContent = links.filter(l => l.issues && l.issues.length > 0).length;
  document.getElementById("countInternal").textContent = links.filter(l => !l.is_external).length;
  document.getElementById("countExternal").textContent = links.filter(l => l.is_external).length;
  document.getElementById("countProduct").textContent = links.filter(l => l.is_product_page).length;
}

function renderLinkInventory() {
  if (!currentAuditData) return;
  const tbody = document.getElementById("linkInventoryBody");
  tbody.innerHTML = "";

  let links = currentAuditData.all_links || [];
  if (activeInventoryFilter === "issues") {
    links = links.filter(l => l.issues && l.issues.length > 0);
  } else if (activeInventoryFilter === "internal") {
    links = links.filter(l => !l.is_external);
  } else if (activeInventoryFilter === "external") {
    links = links.filter(l => l.is_external);
  } else if (activeInventoryFilter === "product") {
    links = links.filter(l => l.is_product_page);
  }

  if (links.length === 0) {
    tbody.innerHTML = `<tr><td colspan="6" class="py-6 text-center text-slate-400">No links in this filter view.</td></tr>`;
    return;
  }

  links.forEach(l => {
    const tr = document.createElement("tr");
    tr.className = l.issues.length > 0 ? "bg-rose-50/20 hover:bg-rose-50/40" : "hover:bg-slate-50";

    const typeBadge = l.is_product_page ? 
      `<span class="px-2 py-0.5 rounded bg-purple-100 text-purple-700 font-bold">Product</span>` :
      (l.is_external ? `<span class="px-2 py-0.5 rounded bg-amber-100 text-amber-800 font-bold">External</span>` : `<span class="px-2 py-0.5 rounded bg-indigo-100 text-indigo-700 font-bold">Internal</span>`);

    const newTabBadge = l.new_tab ?
      `<span class="text-emerald-600 font-bold"><i class="fa-solid fa-check"></i> _blank</span>` :
      `<span class="text-rose-600 font-bold"><i class="fa-solid fa-xmark"></i> Same tab</span>`;

    const followBadge = l.follow_ok ?
      `<span class="text-emerald-600 font-bold">${l.actual_follow}</span>` :
      `<span class="text-rose-600 font-bold">${l.actual_follow} (Expected: ${l.expected_follow})</span>`;

    const issuesBadge = l.issues.length > 0 ?
      `<span class="px-2 py-0.5 rounded-full bg-rose-100 text-rose-700 font-bold" title="${escapeHtml(l.issues.map(i=>i.problem).join('; '))}">
        ${l.issues.length} violation(s)
       </span>` :
      `<span class="text-emerald-600"><i class="fa-solid fa-circle-check"></i> Clean</span>`;

    tr.innerHTML = `
      <td class="py-3 px-6">${typeBadge}</td>
      <td class="py-3 px-6 font-mono max-w-sm truncate" title="${escapeHtml(l.href)}">
        <a href="${escapeHtml(l.href)}" target="_blank" class="text-indigo-600 hover:underline">
          ${escapeHtml(l.href)}
        </a>
      </td>
      <td class="py-3 px-6 font-semibold text-slate-800">${escapeHtml(l.anchor || '(empty)')}</td>
      <td class="py-3 px-6 text-center">${newTabBadge}</td>
      <td class="py-3 px-6">${followBadge}</td>
      <td class="py-3 px-6 text-center">${issuesBadge}</td>
    `;
    tbody.appendChild(tr);
  });
}

async function loadAuditHistory() {
  const container = document.getElementById("historyList");
  try {
    const res = await fetch("/api/history?limit=20");
    const items = await res.json();
    if (!items || items.length === 0) {
      container.innerHTML = `<p class="p-6 text-sm text-slate-400 text-center">No past audits recorded yet.</p>`;
      return;
    }

    container.innerHTML = "";
    items.forEach(item => {
      const row = document.createElement("div");
      row.className = "p-4 hover:bg-slate-50 cursor-pointer flex items-center justify-between transition";
      row.innerHTML = `
        <div class="space-y-1">
          <div class="text-xs font-bold text-slate-900 truncate max-w-md">${escapeHtml(item.page_url)}</div>
          <div class="text-xs text-slate-400 flex items-center space-x-2">
            <span>KW: "${escapeHtml(item.keyword)}"</span>
            <span>•</span>
            <span>${new Date(item.created_at).toLocaleDateString()}</span>
          </div>
        </div>
        <div>
          ${item.overall_pass ? 
            `<span class="px-2 py-0.5 text-xs font-bold rounded badge-pass">PASS</span>` :
            `<span class="px-2 py-0.5 text-xs font-bold rounded badge-fail">FAIL</span>`
          }
        </div>
      `;
      row.addEventListener("click", async () => {
        document.getElementById("historyModal").classList.add("hidden");
        const detailRes = await fetch(`/api/check/${item.id}`);
        if (detailRes.ok) {
          currentAuditData = await detailRes.json();
          renderAuditResults(currentAuditData);
          document.getElementById("resultsSection").classList.remove("hidden");
          document.getElementById("resultsSection").scrollIntoView({ behavior: "smooth" });
        }
      });
      container.appendChild(row);
    });
  } catch (e) {
    container.innerHTML = `<p class="p-6 text-sm text-rose-500 text-center">Failed to load history.</p>`;
  }
}

function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}
