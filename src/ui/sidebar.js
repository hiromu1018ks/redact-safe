// ============================================================
// Sidebar Manager
// ============================================================

import { appState, isTauri, invoke, logAuditEvent, autoSaveDocument } from "./app-state.js";

// --- PII Type Labels (Japanese) ---
const PII_TYPE_LABELS = {
  name: "氏名",
  address: "住所",
  phone: "電話番号",
  email: "メールアドレス",
  birth_date: "生年月日",
  my_number: "マイナンバー",
  corporate_number: "法人番号",
  custom: "カスタム",
};

/**
 * Get a display label for a PII type.
 * Falls back to the raw type string for unknown types.
 */
export function piiTypeLabel(type) {
  return PII_TYPE_LABELS[type] || type;
}

// --- DOM Element References ---
const sidebarPlaceholder = document.getElementById("sidebar-placeholder");
const sidebarContent = document.getElementById("sidebar-content");
const regionCountSpan = document.getElementById("region-count");
const regionListEl = document.getElementById("region-list");
const filterTypeSelect = document.getElementById("filter-type");
const filterStatusSelect = document.getElementById("filter-status");
const btnSidebarAllOn = document.getElementById("btn-sidebar-all-on");
const btnSidebarAllOff = document.getElementById("btn-sidebar-all-off");
const sidebar = document.getElementById("sidebar");
const btnSidebarToggle = document.getElementById("btn-sidebar-toggle");
const btnSidebarExpand = document.getElementById("btn-sidebar-expand");

// --- Sidebar State ---
/** Currently active filter state */
let sidebarFilter = { type: "all", status: "all" };

// --- Sidebar collapse/expand ---
if (btnSidebarToggle && sidebar && btnSidebarExpand) {
  btnSidebarToggle.addEventListener("click", () => {
    sidebar.classList.add("collapsed");
    btnSidebarExpand.style.display = "block";
  });
  btnSidebarExpand.addEventListener("click", () => {
    sidebar.classList.remove("collapsed");
    btnSidebarExpand.style.display = "none";
  });
}

/**
 * Update the sidebar with all regions from backend or test data.
 */
export async function updateSidebarRegions() {
  const { pdfViewer, maskingOverlay, allRegionsByPage, testRegions } = appState;
  if (isTauri) {
    try {
      const doc = await invoke("get_document");
      if (!doc || !doc.pages) {
        for (const key of Object.keys(allRegionsByPage)) delete allRegionsByPage[key];
        renderSidebar();
        return;
      }
      for (const key of Object.keys(allRegionsByPage)) delete allRegionsByPage[key];
      for (const page of doc.pages) {
        if (page.regions && page.regions.length > 0) {
          allRegionsByPage[page.page] = page.regions;
        }
      }
    } catch (e) {
      for (const key of Object.keys(allRegionsByPage)) delete allRegionsByPage[key];
    }
  } else {
    // Browser mode: group test regions by page
    if (testRegions.length > 0) {
      for (const key of Object.keys(allRegionsByPage)) delete allRegionsByPage[key];
      allRegionsByPage[pdfViewer.currentPage] = testRegions;
    } else {
      for (const key of Object.keys(allRegionsByPage)) delete allRegionsByPage[key];
    }
  }
  renderSidebar();
}

/**
 * Render the sidebar region list based on current filter state.
 */
export function renderSidebar() {
  const { maskingOverlay, allRegionsByPage } = appState;

  const allRegions = Object.entries(allRegionsByPage).flatMap(([page, regions]) =>
    regions.map((r) => ({ ...r, _page: parseInt(page, 10) }))
  );

  const total = allRegions.length;
  regionCountSpan.textContent = total + "件";

  if (total === 0) {
    sidebarPlaceholder.style.display = "flex";
    sidebarContent.style.display = "none";
    return;
  }

  sidebarPlaceholder.style.display = "none";
  sidebarContent.style.display = "flex";

  // Apply filters
  const filtered = allRegions.filter((r) => {
    if (sidebarFilter.type !== "all" && r.type !== sidebarFilter.type) return false;
    if (sidebarFilter.status === "enabled" && !r.enabled) return false;
    if (sidebarFilter.status === "disabled" && r.enabled) return false;
    return true;
  });

  // Sort by page, then by position (y then x)
  filtered.sort((a, b) => {
    if (a._page !== b._page) return a._page - b._page;
    if (a.bbox[1] !== b.bbox[1]) return a.bbox[1] - b.bbox[1];
    return a.bbox[0] - b.bbox[0];
  });

  // Render list
  regionListEl.innerHTML = "";
  if (filtered.length === 0) {
    regionListEl.innerHTML = '<div class="region-list-empty">条件に一致する項目がありません</div>';
    return;
  }

  for (const region of filtered) {
    const item = document.createElement("div");
    item.className = "region-item";
    if (maskingOverlay && region.id === maskingOverlay.selectedRegionId) {
      item.classList.add("selected");
    }
    item.dataset.regionId = region.id;
    item.dataset.pageNum = region._page;

    const iconClass = region.enabled ? "icon-on" : "icon-off";
    const typeClass = "type-" + (region.type || "custom");
    const sourceTag = region.source === "manual" ? " [手動]" : "";
    const confidenceStr = region.confidence ? ` (${(region.confidence * 100).toFixed(0)}%)` : "";

    item.innerHTML = `
      <div class="region-icon ${iconClass}">${region.enabled ? "ON" : "OFF"}</div>
      <div class="region-info">
        <div class="region-type ${typeClass}">${piiTypeLabel(region.type)}${sourceTag}</div>
        <div class="region-meta">P${region._page} · ${confidenceStr}</div>
      </div>
    `;

    item.addEventListener("click", () => onSidebarRegionClick(region));
    regionListEl.appendChild(item);
  }

  // Enable/disable bulk buttons
  const hasRegions = total > 0;
  btnSidebarAllOn.disabled = !hasRegions;
  btnSidebarAllOff.disabled = !hasRegions;
}

/**
 * Handle click on a sidebar region item.
 * Navigate to the page and select/highlight the region.
 */
async function onSidebarRegionClick(region) {
  const { pdfViewer, maskingOverlay } = appState;
  const pageNum = region._page;

  // Navigate to the correct page if needed
  if (pdfViewer.isLoaded && pdfViewer.currentPage !== pageNum) {
    await pdfViewer.goToPage(pageNum);
  }

  // Wait a bit for the page to render, then select the region
  setTimeout(() => {
    if (maskingOverlay) {
      maskingOverlay.setSelectedRegion(region.id);
      renderSidebar(); // Update selection highlight in sidebar
    }
  }, 200);
}

// --- Filter change handlers ---
filterTypeSelect.addEventListener("change", () => {
  sidebarFilter.type = filterTypeSelect.value;
  renderSidebar();
});

filterStatusSelect.addEventListener("change", () => {
  sidebarFilter.status = filterStatusSelect.value;
  renderSidebar();
});

// --- Sidebar bulk ON/OFF buttons ---
btnSidebarAllOn.addEventListener("click", async () => {
  const { maskingOverlay, testRegions, undoManager } = appState;
  if (!isTauri) {
    testRegions.forEach((r) => (r.enabled = true));
    maskingOverlay.setRegions(testRegions);
    await updateSidebarRegions();
    logAuditEvent("all_regions_enabled", null, { count: testRegions.length });
    return;
  }
  try {
    undoManager.beginMacro("全てON");
    const count = await invoke("set_all_regions_enabled", { pageNum: null, enabled: true });
    undoManager.endMacro();
    await refreshOverlay();
    await updateSidebarRegions();
    logAuditEvent("all_regions_enabled", null, { count });
    await autoSaveDocument();
  } catch (e) {
    undoManager.endMacro();
    console.error("Failed to enable all regions:", e);
  }
});

btnSidebarAllOff.addEventListener("click", async () => {
  const { maskingOverlay, testRegions, undoManager } = appState;
  if (!isTauri) {
    testRegions.forEach((r) => (r.enabled = false));
    maskingOverlay.setRegions(testRegions);
    await updateSidebarRegions();
    logAuditEvent("all_regions_disabled", null, { count: testRegions.length });
    return;
  }
  try {
    undoManager.beginMacro("全てOFF");
    const count = await invoke("set_all_regions_enabled", { pageNum: null, enabled: false });
    undoManager.endMacro();
    await refreshOverlay();
    await updateSidebarRegions();
    logAuditEvent("all_regions_disabled", null, { count });
    await autoSaveDocument();
  } catch (e) {
    undoManager.endMacro();
    console.error("Failed to disable all regions:", e);
  }
});

/**
 * Refresh overlay regions from backend or local array.
 */
async function refreshOverlay() {
  const { maskingOverlay, pdfViewer, testRegions } = appState;
  if (!maskingOverlay) return;
  if (isTauri) {
    // fetchAndDisplayRegions is defined in main.js and attached to appState
    if (appState.fetchAndDisplayRegions) {
      await appState.fetchAndDisplayRegions(pdfViewer.currentPage);
    }
  } else {
    maskingOverlay.setRegions(testRegions);
  }
}
