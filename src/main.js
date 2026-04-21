import { PdfViewer } from "./pdf-viewer.js";
import { MaskingOverlay } from "./masking-overlay.js";
import { UndoManager } from "./undo-manager.js";

// --- Tauri API (safe access for browser fallback) ---
const isTauri = !!window.__TAURI__;

function invoke(cmd, args) {
  if (!isTauri) return Promise.reject(new Error("Not running in Tauri"));
  return window.__TAURI__.core.invoke(cmd, args);
}

// Generate a simple UUID-like ID
function generateId() {
  return "r-" + Math.random().toString(36).substring(2, 10);
}

// ============================================================
// Progress Manager
// ============================================================

const progressContainer = document.getElementById("progress-container");
const progressBarFill = document.getElementById("progress-bar-fill");
const progressMessage = document.getElementById("progress-message");
const progressPercent = document.getElementById("progress-percent");
const progressStaleWarning = document.getElementById("progress-stale-warning");
const btnCancelProgress = document.getElementById("btn-cancel-progress");

const progressManager = {
  _active: false,
  _lastUpdate: 0,
  _staleTimer: null,
  _cancelUnlisten: null,
  _cancelledUnlisten: null,

  /** Show the progress bar and start listening for events */
  show() {
    this._active = true;
    this._lastUpdate = Date.now();
    progressContainer.style.display = "block";
    progressBarFill.classList.remove("indeterminate");
    progressBarFill.style.width = "0%";
    progressMessage.textContent = "処理を開始しています...";
    progressPercent.textContent = "0%";
    progressStaleWarning.style.display = "none";
    btnCancelProgress.disabled = false;

    // Start stale detection timer (check every 2 seconds)
    this._staleTimer = setInterval(() => this._checkStale(), 2000);

    // Listen for worker progress events
    if (isTauri && !this._cancelUnlisten) {
      this._cancelUnlisten = window.__TAURI__.event.listen("worker-progress", (event) => {
        this.update(event.payload);
      });
      this._cancelledUnlisten = window.__TAURI__.event.listen("worker-cancelled", () => {
        this.hide();
      });
    }
  },

  /** Update progress from a worker-progress event */
  update(payload) {
    if (!this._active) return;

    this._lastUpdate = Date.now();
    progressStaleWarning.style.display = "none";

    const { phase, current, total, message } = payload;

    // Update message
    progressMessage.textContent = message || phase;

    // Update bar
    if (total > 0) {
      const pct = Math.min(Math.round((current / total) * 100), 100);
      progressBarFill.style.width = pct + "%";
      progressPercent.textContent = pct + "%";
    } else {
      // Unknown total - show indeterminate
      progressBarFill.classList.add("indeterminate");
      progressPercent.textContent = "";
    }
  },

  /** Hide the progress bar */
  hide() {
    this._active = false;
    progressContainer.style.display = "none";
    progressBarFill.classList.remove("indeterminate");
    if (this._staleTimer) {
      clearInterval(this._staleTimer);
      this._staleTimer = null;
    }
  },

  /** Check if progress is stale (>10 seconds without update) */
  _checkStale() {
    if (!this._active) return;
    const elapsed = Date.now() - this._lastUpdate;
    if (elapsed > 10000) {
      progressStaleWarning.style.display = "block";
    }
  },

  /** Whether progress UI is currently active */
  get isActive() {
    return this._active;
  },

  /** Clean up event listeners */
  cleanup() {
    if (this._cancelUnlisten) {
      this._cancelUnlisten.then((fn) => fn());
      this._cancelUnlisten = null;
    }
    if (this._cancelledUnlisten) {
      this._cancelledUnlisten.then((fn) => fn());
      this._cancelledUnlisten = null;
    }
  },
};

// Cancel button handler
btnCancelProgress.addEventListener("click", async () => {
  btnCancelProgress.disabled = true;
  progressMessage.textContent = "キャンセル中...";
  try {
    await invoke("cancel_worker");
  } catch (e) {
    console.warn("Cancel failed:", e);
  }
  progressManager.hide();
});

// --- PDF Viewer ---
let pdfViewer = null;
let maskingOverlay = null;
let undoManager = new UndoManager();

// ============================================================
// Interaction Engine (drag / resize / draw-new)
// ============================================================

const InteractionMode = {
  NONE: "none",
  MOVE: "move",
  RESIZE: "resize",
  DRAW_NEW: "draw_new",
};

/** @type {{ mode: string, handleId: string|null, regionId: string|null, startClientX: number, startClientY: number, startBbox: number[]|null, currentBbox: number[]|null }} */
let interaction = {
  mode: InteractionMode.NONE,
  handleId: null,
  regionId: null,
  startClientX: 0,
  startClientY: 0,
  startBbox: null,
  currentBbox: null,
};

/** Minimum size in PDF points for a drawn region */
const MIN_REGION_SIZE_PT = 5;

/**
 * Get the region object from local test regions or backend document.
 * Returns null if not found.
 */
async function getRegion(pageNum, regionId) {
  if (isTauri) {
    try {
      const doc = await invoke("get_document");
      if (!doc || !doc.pages) return null;
      const page = doc.pages.find((p) => p.page === pageNum);
      if (!page || !page.regions) return null;
      return page.regions.find((r) => r.id === regionId) || null;
    } catch {
      return null;
    }
  }
  // Browser mode: check local testRegions
  return testRegions.find((r) => r.id === regionId) || null;
}

/**
 * Persist a region update to the backend (Tauri mode).
 * In browser mode, updates local testRegions array.
 */
async function persistRegionUpdate(pageNum, regionId, updates) {
  if (isTauri) {
    try {
      if (updates.bbox) {
        await invoke("update_region_bbox", { pageNum, regionId, bbox: updates.bbox });
      }
      if (updates.enabled !== undefined) {
        await invoke("toggle_region", { pageNum, regionId });
      }
    } catch (e) {
      console.error("Failed to persist region update:", e);
    }
  } else {
    const r = testRegions.find((tr) => tr.id === regionId);
    if (r) {
      if (updates.bbox) r.bbox = updates.bbox;
      if (updates.enabled !== undefined) r.enabled = updates.enabled;
    }
  }
}

/**
 * Add a region to backend (Tauri) or local test array (browser).
 */
async function persistAddRegion(pageNum, region) {
  if (isTauri) {
    try {
      await invoke("add_region", { pageNum, region });
    } catch (e) {
      console.error("Failed to add region:", e);
    }
  } else {
    testRegions.push(region);
  }
}

/**
 * Remove a region from backend (Tauri) or local test array (browser).
 */
async function persistRemoveRegion(pageNum, regionId) {
  if (isTauri) {
    try {
      await invoke("remove_region", { pageNum, regionId });
    } catch (e) {
      console.error("Failed to remove region:", e);
    }
  } else {
    const idx = testRegions.findIndex((r) => r.id === regionId);
    if (idx !== -1) testRegions.splice(idx, 1);
  }
}

/**
 * Toggle region ON/OFF via backend.
 * Returns the new enabled state.
 */
async function persistToggleRegion(pageNum, regionId) {
  if (isTauri) {
    try {
      return await invoke("toggle_region", { pageNum, regionId });
    } catch (e) {
      console.error("Failed to toggle region:", e);
      return null;
    }
  } else {
    const r = testRegions.find((tr) => tr.id === regionId);
    if (r) {
      r.enabled = !r.enabled;
      return r.enabled;
    }
    return null;
  }
}

/**
 * Refresh overlay regions from backend or local array.
 */
async function refreshOverlay() {
  if (!maskingOverlay) return;
  if (isTauri) {
    await fetchAndDisplayRegions(pdfViewer.currentPage);
  } else {
    maskingOverlay.setRegions(testRegions);
  }
}

/**
 * Log an audit event (Tauri only).
 */
function logAuditEvent(event, documentId, data) {
  if (!isTauri) return;
  invoke("log_event", { event, user: null, documentId, data }).catch(() => {});
}

/**
 * Auto-save document (Tauri only).
 */
async function autoSaveDocument() {
  if (!isTauri) return;
  try {
    await invoke("save_document", { path: "" });
  } catch {
    // Auto-save is best-effort; document may not have a path yet
  }
}

/**
 * Handle mousedown on the overlay canvas — start interaction.
 */
function onOverlayMouseDown(e) {
  if (!maskingOverlay || !pdfViewer.isLoaded) return;
  if (e.button !== 0) return; // left click only

  const clientX = e.clientX;
  const clientY = e.clientY;

  // 1. Check if clicking a resize handle of the selected region
  const handleId = maskingOverlay.findHandleAtPoint(clientX, clientY);
  if (handleId) {
    const region = maskingOverlay.regions.find((r) => r.id === maskingOverlay.selectedRegionId);
    if (region) {
      interaction.mode = InteractionMode.RESIZE;
      interaction.handleId = handleId;
      interaction.regionId = region.id;
      interaction.startClientX = clientX;
      interaction.startClientY = clientY;
      interaction.startBbox = [...region.bbox];
      interaction.currentBbox = [...region.bbox];
      e.preventDefault();
      return;
    }
  }

  // 2. Check if clicking on a region
  const region = maskingOverlay.findRegionAtPoint(clientX, clientY);
  if (region) {
    maskingOverlay.setSelectedRegion(region.id);
    interaction.mode = InteractionMode.MOVE;
    interaction.handleId = null;
    interaction.regionId = region.id;
    interaction.startClientX = clientX;
    interaction.startClientY = clientY;
    interaction.startBbox = [...region.bbox];
    interaction.currentBbox = [...region.bbox];
    e.preventDefault();
    return;
  }

  // 3. Clicked on empty space → deselect and start drawing new region
  maskingOverlay.setSelectedRegion(null);
  interaction.mode = InteractionMode.DRAW_NEW;
  interaction.handleId = null;
  interaction.regionId = null;
  interaction.startClientX = clientX;
  interaction.startClientY = clientY;
  interaction.startBbox = null;
  interaction.currentBbox = null;
  e.preventDefault();
}

/**
 * Handle mousemove during an active interaction.
 */
function onOverlayMouseMove(e) {
  if (!maskingOverlay || !pdfViewer.isLoaded) return;

  const clientX = e.clientX;
  const clientY = e.clientY;

  if (interaction.mode === InteractionMode.NONE) {
    // Update cursor based on what's under the mouse
    const handleId = maskingOverlay.findHandleAtPoint(clientX, clientY);
    if (handleId) {
      overlayCanvas.style.cursor = MaskingOverlay.cursorForHandle(handleId);
    } else {
      const region = maskingOverlay.findRegionAtPoint(clientX, clientY);
      overlayCanvas.style.cursor = region ? "move" : "crosshair";
    }
    return;
  }

  e.preventDefault();

  if (interaction.mode === InteractionMode.MOVE) {
    // Calculate delta in PDF points
    const startPt = pdfViewer.screenToPdfPoint(interaction.startClientX, interaction.startClientY);
    const currentPt = pdfViewer.screenToPdfPoint(clientX, clientY);
    const dx = currentPt.x - startPt.x;
    const dy = currentPt.y - startPt.y;

    const newBbox = [
      interaction.startBbox[0] + dx,
      interaction.startBbox[1] + dy,
      interaction.startBbox[2],
      interaction.startBbox[3],
    ];
    interaction.currentBbox = newBbox;

    // Update region in overlay
    const region = maskingOverlay.regions.find((r) => r.id === interaction.regionId);
    if (region) {
      region.bbox = newBbox;
      maskingOverlay.render();
    }
  } else if (interaction.mode === InteractionMode.RESIZE) {
    const startPt = pdfViewer.screenToPdfPoint(interaction.startClientX, interaction.startClientY);
    const currentPt = pdfViewer.screenToPdfPoint(clientX, clientY);
    const dx = currentPt.x - startPt.x;
    const dy = currentPt.y - startPt.y;

    const sb = interaction.startBbox;
    let newX = sb[0], newY = sb[1], newW = sb[2], newH = sb[3];
    const hid = interaction.handleId;

    // Adjust x, y, w, h based on which handle is being dragged
    if (hid === "nw" || hid === "w" || hid === "sw") { newX += dx; newW -= dx; }
    if (hid === "ne" || hid === "e" || hid === "se") { newW += dx; }
    if (hid === "nw" || hid === "n" || hid === "ne") { newY += dy; newH -= dy; }
    if (hid === "sw" || hid === "s" || hid === "se") { newH += dy; }

    // Enforce minimum size
    if (newW < MIN_REGION_SIZE_PT) {
      if (hid === "nw" || hid === "w" || hid === "sw") {
        newX = sb[0] + sb[2] - MIN_REGION_SIZE_PT;
      }
      newW = MIN_REGION_SIZE_PT;
    }
    if (newH < MIN_REGION_SIZE_PT) {
      if (hid === "nw" || hid === "n" || hid === "ne") {
        newY = sb[1] + sb[3] - MIN_REGION_SIZE_PT;
      }
      newH = MIN_REGION_SIZE_PT;
    }

    const newBbox = [newX, newY, newW, newH];
    interaction.currentBbox = newBbox;

    const region = maskingOverlay.regions.find((r) => r.id === interaction.regionId);
    if (region) {
      region.bbox = newBbox;
      maskingOverlay.render();
    }
  } else if (interaction.mode === InteractionMode.DRAW_NEW) {
    // Draw a preview rectangle on the overlay
    const startPt = pdfViewer.screenToPdfPoint(interaction.startClientX, interaction.startClientY);
    const currentPt = pdfViewer.screenToPdfPoint(clientX, clientY);

    const x = Math.min(startPt.x, currentPt.x);
    const y = Math.min(startPt.y, currentPt.y);
    const w = Math.abs(currentPt.x - startPt.x);
    const h = Math.abs(currentPt.y - startPt.y);

    interaction.currentBbox = [x, y, w, h];

    // Render a preview by temporarily adding a "drawing" region
    _drawNewRegionPreview(x, y, w, h);
  }
}

/**
 * Render a preview rectangle for the region being drawn.
 */
function _drawNewRegionPreview(x, y, w, h) {
  if (!maskingOverlay) return;
  const ctx = maskingOverlay.ctx;
  // Re-render existing regions first
  maskingOverlay.render();
  if (w < 1 || h < 1) return;

  const bbox = pdfViewer.getBBoxInCanvas([x, y, w, h]);
  ctx.save();
  ctx.setLineDash([4, 4]);
  ctx.strokeStyle = "#44AA44";
  ctx.lineWidth = 1.5;
  ctx.strokeRect(bbox.x, bbox.y, bbox.width, bbox.height);
  ctx.fillStyle = "rgba(0, 0, 0, 0.3)";
  ctx.fillRect(bbox.x, bbox.y, bbox.width, bbox.height);
  ctx.restore();
}

/**
 * Handle mouseup — finalize the interaction.
 */
async function onOverlayMouseUp(e) {
  if (interaction.mode === InteractionMode.NONE) return;

  const pageNum = pdfViewer.currentPage;

  if (interaction.mode === InteractionMode.MOVE) {
    if (interaction.currentBbox && interaction.startBbox) {
      const changed =
        interaction.currentBbox[0] !== interaction.startBbox[0] ||
        interaction.currentBbox[1] !== interaction.startBbox[1];
      if (changed) {
        // Push undo
        undoManager.push({
          type: "move",
          pageNum,
          regionId: interaction.regionId,
          prevBbox: interaction.startBbox,
        });
        // Persist
        await persistRegionUpdate(pageNum, interaction.regionId, {
          bbox: interaction.currentBbox,
        });
        logAuditEvent("region_moved", null, {
          region_id: interaction.regionId,
          page: pageNum,
          prev_bbox: interaction.startBbox,
          new_bbox: interaction.currentBbox,
        });
        await autoSaveDocument();
      }
    }
  } else if (interaction.mode === InteractionMode.RESIZE) {
    if (interaction.currentBbox && interaction.startBbox) {
      const changed =
        interaction.currentBbox[0] !== interaction.startBbox[0] ||
        interaction.currentBbox[1] !== interaction.startBbox[1] ||
        interaction.currentBbox[2] !== interaction.startBbox[2] ||
        interaction.currentBbox[3] !== interaction.startBbox[3];
      if (changed) {
        undoManager.push({
          type: "resize",
          pageNum,
          regionId: interaction.regionId,
          prevBbox: interaction.startBbox,
        });
        await persistRegionUpdate(pageNum, interaction.regionId, {
          bbox: interaction.currentBbox,
        });
        logAuditEvent("region_resized", null, {
          region_id: interaction.regionId,
          page: pageNum,
          prev_bbox: interaction.startBbox,
          new_bbox: interaction.currentBbox,
        });
        await autoSaveDocument();
      }
    }
  } else if (interaction.mode === InteractionMode.DRAW_NEW) {
    if (interaction.currentBbox) {
      const [x, y, w, h] = interaction.currentBbox;
      if (w >= MIN_REGION_SIZE_PT && h >= MIN_REGION_SIZE_PT) {
        const newRegion = {
          id: generateId(),
          bbox: [x, y, w, h],
          type: "custom",
          confidence: 1.0,
          enabled: true,
          source: "manual",
          note: "",
        };
        undoManager.push({
          type: "add",
          pageNum,
          regionId: newRegion.id,
          snapshot: { ...newRegion },
        });
        await persistAddRegion(pageNum, newRegion);
        maskingOverlay.setSelectedRegion(newRegion.id);
        logAuditEvent("region_added", null, {
          region_id: newRegion.id,
          page: pageNum,
          bbox: newRegion.bbox,
          source: "manual",
        });
        await autoSaveDocument();
      }
    }
    // Clear preview and refresh
    await refreshOverlay();
  }

  // Reset interaction
  interaction.mode = InteractionMode.NONE;
  interaction.handleId = null;
  interaction.regionId = null;
  interaction.startBbox = null;
  interaction.currentBbox = null;
}

/**
 * Perform undo of the last operation.
 */
async function performUndo() {
  const op = undoManager.pop();
  if (!op) return;

  const pageNum = op.pageNum;

  if (op.type === "move" || op.type === "resize") {
    // Restore previous bbox
    await persistRegionUpdate(pageNum, op.regionId, { bbox: op.prevBbox });
    maskingOverlay.setSelectedRegion(op.regionId);
    logAuditEvent("undo_" + op.type, null, {
      region_id: op.regionId,
      page: pageNum,
      restored_bbox: op.prevBbox,
    });
  } else if (op.type === "add") {
    // Remove the added region
    await persistRemoveRegion(pageNum, op.regionId);
    logAuditEvent("undo_add", null, {
      region_id: op.regionId,
      page: pageNum,
    });
  } else if (op.type === "remove") {
    // Re-add the removed region
    await persistAddRegion(pageNum, op.snapshot);
    maskingOverlay.setSelectedRegion(op.regionId);
    logAuditEvent("undo_remove", null, {
      region_id: op.regionId,
      page: pageNum,
    });
  } else if (op.type === "toggle") {
    // Toggle back
    await persistToggleRegion(pageNum, op.regionId);
    maskingOverlay.setSelectedRegion(op.regionId);
    logAuditEvent("undo_toggle", null, {
      region_id: op.regionId,
      page: pageNum,
    });
  }

  await refreshOverlay();
  await autoSaveDocument();
}

/**
 * Delete the currently selected region.
 */
async function deleteSelectedRegion() {
  if (!maskingOverlay || !maskingOverlay.selectedRegionId) return;

  const regionId = maskingOverlay.selectedRegionId;
  const pageNum = pdfViewer.currentPage;

  // Get region snapshot for undo
  const region = await getRegion(pageNum, regionId);
  if (!region) return;

  undoManager.push({
    type: "remove",
    pageNum,
    regionId,
    snapshot: { ...region },
  });

  await persistRemoveRegion(pageNum, regionId);
  maskingOverlay.setSelectedRegion(null);
  logAuditEvent("region_deleted", null, {
    region_id: regionId,
    page: pageNum,
  });
  await refreshOverlay();
  await autoSaveDocument();
}

/**
 * Toggle the currently selected region ON/OFF.
 */
async function toggleSelectedRegion() {
  if (!maskingOverlay || !maskingOverlay.selectedRegionId) return;

  const regionId = maskingOverlay.selectedRegionId;
  const pageNum = pdfViewer.currentPage;

  undoManager.push({
    type: "toggle",
    pageNum,
    regionId,
  });

  const newEnabled = await persistToggleRegion(pageNum, regionId);
  logAuditEvent("region_toggled", null, {
    region_id: regionId,
    page: pageNum,
    enabled: newEnabled,
  });
  await refreshOverlay();
  await autoSaveDocument();
}

// --- DOM Elements ---
const pdfCanvas = document.getElementById("pdf-canvas");
const overlayCanvas = document.getElementById("overlay-canvas");
const canvasWrapper = document.getElementById("canvas-wrapper");
const pdfPlaceholder = document.getElementById("pdf-placeholder");
const pdfContainer = document.getElementById("pdf-container");
const pdfFilename = document.getElementById("pdf-filename");
const zoomLevel = document.getElementById("zoom-level");
const pageInput = document.getElementById("page-input");
const totalPagesSpan = document.getElementById("total-pages");
const coordDisplay = document.getElementById("coord-display");
const statusDisplay = document.getElementById("status-display");

const btnOpenPdf = document.getElementById("btn-open-pdf");
const btnZoomIn = document.getElementById("btn-zoom-in");
const btnZoomOut = document.getElementById("btn-zoom-out");
const btnFitWidth = document.getElementById("btn-fit-width");
const btnPrevPage = document.getElementById("btn-prev-page");
const btnNextPage = document.getElementById("btn-next-page");

// --- Debug Panel ---
const debugPanel = document.getElementById("debug-panel");
const btnCloseDebug = document.getElementById("btn-close-debug");

// ============================================================
// PDF Viewer Setup
// ============================================================

function initPdfViewer() {
  pdfViewer = new PdfViewer(pdfCanvas);
  maskingOverlay = new MaskingOverlay(overlayCanvas, pdfViewer);

  pdfViewer.onLoad = ({ numPages, fileName }) => {
    // Show canvas wrapper, hide placeholder
    canvasWrapper.classList.add("visible");
    pdfPlaceholder.classList.add("hidden");
    pdfContainer.classList.add("has-pdf");

    // Update filename
    pdfFilename.textContent = fileName;
    pdfFilename.title = fileName;

    // Update total pages
    totalPagesSpan.textContent = numPages;
    pageInput.max = numPages;
    pageInput.value = 1;
    pageInput.disabled = false;

    // Enable navigation buttons
    btnPrevPage.disabled = false;
    btnNextPage.disabled = numPages <= 1;
    btnZoomIn.disabled = false;
    btnZoomOut.disabled = false;
    btnFitWidth.disabled = false;

    // Update status
    updateStatus(fileName, 1, numPages);

    // Log file_opened event (Tauri only)
    if (isTauri) {
      invoke("log_event", {
        event: "file_opened",
        user: null,
        documentId: null,
        data: { file_name: fileName, num_pages: numPages },
      }).catch(() => {});

      // Also try to get the document_id for logging
      invoke("get_document_status").then((status) => {
        if (status) {
          invoke("get_document").then((doc) => {
            if (doc) {
              invoke("log_event", {
                event: "document_created",
                user: null,
                documentId: doc.document_id,
                data: {
                  file_name: fileName,
                  num_pages: numPages,
                  source_hash: doc.source_hash,
                },
              }).catch(() => {});
            }
          }).catch(() => {});
        }
      }).catch(() => {});
    }

    // Auto fit to width
    requestAnimationFrame(() => {
      const containerWidth = pdfContainer.clientWidth - 32; // padding
      if (containerWidth > 0) {
        pdfViewer.fitToWidth(containerWidth);
      }
    });
  };

  pdfViewer.onPageChange = (pageNum, totalPages) => {
    pageInput.value = pageNum;
    btnPrevPage.disabled = pageNum <= 1;
    btnNextPage.disabled = pageNum >= totalPages;
    updateStatus(pdfViewer.fileName, pageNum, totalPages);

    // Sync overlay canvas size with PDF canvas
    if (maskingOverlay) {
      maskingOverlay.resize(pdfCanvas.width, pdfCanvas.height);
    }

    // Fetch regions for the new page from backend
    fetchAndDisplayRegions(pageNum);
  };

  pdfViewer.onZoomChange = (scale) => {
    zoomLevel.textContent = Math.round(scale * 100) + "%";
  };
}

/**
 * Fetch regions for a page from the backend and display them on the overlay.
 */
async function fetchAndDisplayRegions(pageNum) {
  if (!isTauri || !maskingOverlay) return;
  try {
    const doc = await invoke("get_document");
    if (!doc || !doc.pages) {
      maskingOverlay.clear();
      return;
    }
    const page = doc.pages.find((p) => p.page === pageNum);
    if (page && page.regions && page.regions.length > 0) {
      maskingOverlay.setRegions(page.regions);
    } else {
      maskingOverlay.clear();
    }
  } catch (e) {
    // No document or error - clear overlay
    maskingOverlay?.clear();
  }
}

function updateStatus(fileName, pageNum, totalPages) {
  if (!fileName) {
    statusDisplay.textContent = "未読込";
    return;
  }
  statusDisplay.textContent = `${fileName} — ${pageNum} / ${totalPages}ページ`;
}

function enablePdfControls(enabled) {
  btnZoomIn.disabled = !enabled;
  btnZoomOut.disabled = !enabled;
  btnFitWidth.disabled = !enabled;
  btnPrevPage.disabled = !enabled;
  btnNextPage.disabled = !enabled;
  pageInput.disabled = !enabled;
}

// ============================================================
// File Opening
// ============================================================

// --- Modal Dialog Helpers ---
const passwordDialog = document.getElementById("password-dialog");
const passwordInput = document.getElementById("pdf-password-input");
const passwordError = document.getElementById("password-error");
const btnPasswordOk = document.getElementById("btn-password-ok");
const btnPasswordCancel = document.getElementById("btn-password-cancel");

const signatureDialog = document.getElementById("signature-dialog");
const btnSignatureContinue = document.getElementById("btn-signature-continue");
const btnSignatureCancel = document.getElementById("btn-signature-cancel");

function showPasswordDialog() {
  return new Promise((resolve) => {
    passwordInput.value = "";
    passwordError.style.display = "none";
    passwordDialog.style.display = "flex";
    passwordInput.focus();

    function cleanup() {
      passwordDialog.style.display = "none";
      btnPasswordOk.removeEventListener("click", onOk);
      btnPasswordCancel.removeEventListener("click", onCancel);
      passwordInput.removeEventListener("keydown", onKeydown);
    }

    function onOk() {
      const pw = passwordInput.value;
      cleanup();
      resolve(pw);
    }

    function onCancel() {
      cleanup();
      resolve(null);
    }

    function onKeydown(e) {
      if (e.key === "Enter") {
        e.preventDefault();
        onOk();
      } else if (e.key === "Escape") {
        e.preventDefault();
        onCancel();
      }
    }

    btnPasswordOk.addEventListener("click", onOk);
    btnPasswordCancel.addEventListener("click", onCancel);
    passwordInput.addEventListener("keydown", onKeydown);
  });
}

function showPasswordError() {
  passwordError.style.display = "block";
  passwordInput.value = "";
  passwordInput.focus();
}

function showSignatureDialog() {
  return new Promise((resolve) => {
    signatureDialog.style.display = "flex";

    function cleanup() {
      signatureDialog.style.display = "none";
      btnSignatureContinue.removeEventListener("click", onContinue);
      btnSignatureCancel.removeEventListener("click", onCancel);
    }

    function onContinue() {
      cleanup();
      resolve(true);
    }

    function onCancel() {
      cleanup();
      resolve(false);
    }

    btnSignatureContinue.addEventListener("click", onContinue);
    btnSignatureCancel.addEventListener("click", onCancel);
  });
}

// --- Array buffer to base64 ---
function arrayBufferToBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (let i = 0; i < bytes.byteLength; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary);
}

// --- PDF Analysis Flow ---

/**
 * Invoke a worker command with progress tracking.
 * Shows progress bar, handles stale detection, and supports cancellation.
 * @param {string} cmd - Tauri command name
 * @param {object} args - Command arguments
 * @param {string} [startMessage] - Initial progress message
 * @returns {Promise<any>} - Command result
 */
async function invokeWithProgress(cmd, args, startMessage) {
  progressManager.show();
  if (startMessage) {
    progressManager.update({ phase: cmd, current: 0, total: 0, message: startMessage });
  }
  try {
    const result = await invoke(cmd, args);
    return result;
  } finally {
    progressManager.hide();
  }
}

async function analyzePdfWithWorker(pdfData) {
  if (!isTauri) {
    // Browser mode: no Python worker, skip analysis
    return null;
  }
  try {
    progressManager.show();
    progressManager.update({ phase: "analyzing", current: 0, total: 1, message: "PDFを解析中..." });
    const base64 = arrayBufferToBase64(pdfData);
    const result = await invoke("analyze_pdf", {
      pdfDataBase64: base64,
      password: null,
    });
    return result;
  } catch (e) {
    console.warn("PDF analysis via Python worker failed:", e);
    return null;
  } finally {
    progressManager.hide();
  }
}

async function decryptPdfWithWorker(pdfData, password) {
  if (!isTauri) {
    return null;
  }
  try {
    const base64 = arrayBufferToBase64(pdfData);
    const result = await invoke("decrypt_pdf", {
      pdfDataBase64: base64,
      password: password,
    });
    return result;
  } catch (e) {
    console.warn("PDF decrypt via Python worker failed:", e);
    return null;
  }
}

// --- Main PDF Load Flow ---
async function loadPdfWithAnalysis(arrayBuffer, fileName) {
  // Step 1: Analyze PDF via Python worker (if available)
  const analysis = await analyzePdfWithWorker(arrayBuffer);

  if (analysis) {
    // Step 2: Check encryption
    if (analysis.needs_pass) {
      // Show password dialog (loop until correct or cancel)
      while (true) {
        const password = await showPasswordDialog();
        if (password === null) {
          // User cancelled
          return;
        }

        const decryptResult = await decryptPdfWithWorker(arrayBuffer, password);
        if (decryptResult && decryptResult.success) {
          break;
        } else {
          showPasswordError();
        }
      }
    }

    // Step 3: Check for digital signatures
    if (analysis.has_signatures) {
      const proceed = await showSignatureDialog();
      if (!proceed) {
        return;
      }
    }

    // Step 4: Create document state with hash
    if (analysis.sha256) {
      try {
        const docId = await invoke("create_document", {
          sourceFile: fileName,
          sourceHash: `sha256:${analysis.sha256}`,
        });
        console.log("Document created:", docId);

        // Add pages from analysis
        if (analysis.pages && Array.isArray(analysis.pages)) {
          for (const pageInfo of analysis.pages) {
            try {
              await invoke("add_page", {
                page: pageInfo.page,
                widthPt: pageInfo.width_pt,
                heightPt: pageInfo.height_pt,
                rotationDeg: pageInfo.rotation_deg,
                extractionPath: "unknown",
              });
            } catch (pageErr) {
              console.warn(`Failed to add page ${pageInfo.page}:`, pageErr);
            }
          }
        }
      } catch (e) {
        console.warn("Failed to create document state:", e);
      }
    }
  }

  // Step 5: Load PDF into viewer
  try {
    await pdfViewer.loadPdf(arrayBuffer, fileName);
  } catch (e) {
    console.error("Failed to load PDF:", e);
    alert("PDFの読み込みに失敗しました: " + e.message);
  }
}

async function openPdfFile() {
  let result = null;

  if (isTauri) {
    try {
      // Dynamic import to avoid build errors in browser-only mode
      const { open } = await import("@tauri-apps/plugin-dialog");
      const filePath = await open({
        multiple: false,
        filters: [{ name: "PDF Files", extensions: ["pdf"] }],
      });
      if (!filePath) return;

      const url = window.__TAURI__.core.convertFileSrc(filePath);
      const response = await fetch(url);
      const arrayBuffer = await response.arrayBuffer();
      const fileName = filePath.split(/[/\\]/).pop() || "document.pdf";
      result = { data: arrayBuffer, fileName };
    } catch (e) {
      console.error("Failed to open file via Tauri dialog:", e);
      return;
    }
  } else {
    // Browser fallback: HTML file input
    result = await new Promise((resolve) => {
      const input = document.createElement("input");
      input.type = "file";
      input.accept = ".pdf";
      input.onchange = async (e) => {
        const file = e.target.files[0];
        if (!file) {
          resolve(null);
          return;
        }
        const arrayBuffer = await file.arrayBuffer();
        resolve({ data: arrayBuffer, fileName: file.name });
      };
      input.click();
    });
  }

  if (!result) return;

  await loadPdfWithAnalysis(result.data, result.fileName);
}

// ============================================================
// Event Listeners
// ============================================================

document.addEventListener("DOMContentLoaded", () => {
  console.log("RedactSafe initialized");
  initPdfViewer();

  // --- PDF Viewer Events ---

  btnOpenPdf.addEventListener("click", openPdfFile);

  btnZoomIn.addEventListener("click", () => {
    pdfViewer.zoomIn();
  });

  btnZoomOut.addEventListener("click", () => {
    pdfViewer.zoomOut();
  });

  btnFitWidth.addEventListener("click", () => {
    const containerWidth = pdfContainer.clientWidth - 32;
    if (containerWidth > 0) {
      pdfViewer.fitToWidth(containerWidth);
    }
  });

  btnPrevPage.addEventListener("click", () => {
    pdfViewer.prevPage();
  });

  btnNextPage.addEventListener("click", () => {
    pdfViewer.nextPage();
  });

  pageInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      const page = parseInt(pageInput.value, 10);
      if (page) {
        pdfViewer.goToPage(page);
        pageInput.blur();
      }
    }
  });

  pageInput.addEventListener("change", () => {
    const page = parseInt(pageInput.value, 10);
    if (page) {
      pdfViewer.goToPage(page);
    }
  });

  // Coordinate display on mouse move (on overlay canvas, which sits on top)
  overlayCanvas.addEventListener("mousemove", (e) => {
    if (!pdfViewer.isLoaded) return;
    const pt = pdfViewer.screenToPdfPoint(e.clientX, e.clientY);
    coordDisplay.textContent = `${pt.x.toFixed(1)}, ${pt.y.toFixed(1)} pt`;

    // Hover highlight (only when not in an interaction)
    if (maskingOverlay && interaction.mode === InteractionMode.NONE) {
      const region = maskingOverlay.findRegionAtPoint(e.clientX, e.clientY);
      const regionId = region ? region.id : null;
      maskingOverlay.setHoveredRegion(regionId);
    }
  });

  overlayCanvas.addEventListener("mouseleave", () => {
    coordDisplay.textContent = "";
    if (maskingOverlay) {
      maskingOverlay.setHoveredRegion(null);
      if (interaction.mode === InteractionMode.NONE) {
        overlayCanvas.style.cursor = "crosshair";
      }
    }
  });

  // --- Interaction Engine: mousedown / mousemove / mouseup ---
  overlayCanvas.addEventListener("mousedown", onOverlayMouseDown);
  window.addEventListener("mousemove", onOverlayMouseMove);
  window.addEventListener("mouseup", onOverlayMouseUp);

  // Double-click to toggle ON/OFF
  overlayCanvas.addEventListener("dblclick", (e) => {
    if (!maskingOverlay) return;
    const region = maskingOverlay.findRegionAtPoint(e.clientX, e.clientY);
    if (region) {
      maskingOverlay.setSelectedRegion(region.id);
      toggleSelectedRegion();
    }
  });

  // --- Drag & Drop Support ---
  pdfContainer.addEventListener("dragover", (e) => {
    e.preventDefault();
    e.stopPropagation();
    pdfContainer.classList.add("drag-over");
  });

  pdfContainer.addEventListener("dragleave", (e) => {
    e.preventDefault();
    e.stopPropagation();
    pdfContainer.classList.remove("drag-over");
  });

  pdfContainer.addEventListener("drop", async (e) => {
    e.preventDefault();
    e.stopPropagation();
    pdfContainer.classList.remove("drag-over");

    const file = e.dataTransfer.files[0];
    if (!file) return;

    if (file.type !== "application/pdf" && !file.name.toLowerCase().endsWith(".pdf")) {
      alert("PDFファイルのみ読み込み可能です");
      return;
    }

    try {
      const arrayBuffer = await file.arrayBuffer();
      await loadPdfWithAnalysis(arrayBuffer, file.name);
    } catch (err) {
      console.error("Failed to load dropped PDF:", err);
      alert("PDFの読み込みに失敗しました: " + err.message);
    }
  });

  // --- Keyboard Shortcuts ---
  document.addEventListener("keydown", (e) => {
    // Don't capture when typing in inputs
    if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") {
      return;
    }

    // Ctrl+O: Open file
    if (e.ctrlKey && e.key === "o") {
      e.preventDefault();
      openPdfFile();
      return;
    }

    // Ctrl+Z: Undo
    if (e.ctrlKey && !e.shiftKey && e.key === "z") {
      e.preventDefault();
      performUndo();
      return;
    }

    // Ctrl+Shift+D: Toggle debug panel
    if (e.ctrlKey && e.shiftKey && e.key === "D") {
      e.preventDefault();
      toggleDebugPanel();
      return;
    }

    if (!pdfViewer.isLoaded) return;

    // Delete / Backspace: Delete selected region
    if (e.key === "Delete" || e.key === "Backspace") {
      e.preventDefault();
      deleteSelectedRegion();
      return;
    }

    // Space: Toggle selected region ON/OFF
    if (e.key === " " && !e.ctrlKey && !e.shiftKey) {
      e.preventDefault();
      toggleSelectedRegion();
      return;
    }

    // Left/Right arrows: Page navigation
    if (e.key === "ArrowLeft") {
      e.preventDefault();
      pdfViewer.prevPage();
    } else if (e.key === "ArrowRight") {
      e.preventDefault();
      pdfViewer.nextPage();
    }

    // Ctrl+/Ctrl-: Zoom
    if (e.ctrlKey && (e.key === "=" || e.key === "+")) {
      e.preventDefault();
      pdfViewer.zoomIn();
    } else if (e.ctrlKey && e.key === "-") {
      e.preventDefault();
      pdfViewer.zoomOut();
    } else if (e.ctrlKey && e.key === "0") {
      e.preventDefault();
      pdfViewer.setZoom(1.0);
    }
  });

  // --- Debug Panel ---
  btnCloseDebug.addEventListener("click", () => {
    debugPanel.style.display = "none";
  });

  // Click backdrop to close
  debugPanel.addEventListener("click", (e) => {
    if (e.target === debugPanel) {
      debugPanel.style.display = "none";
    }
  });

  // ============================================================
  // Debug Panel: Python Worker Test
  // ============================================================

  const btnInitWorker = document.getElementById("btn-init-worker");
  const btnPing = document.getElementById("btn-ping");
  const pingMessage = document.getElementById("ping-message");
  const workerStatus = document.getElementById("worker-status");
  const pingResult = document.getElementById("ping-result");
  let workerConnected = false;

  btnInitWorker.addEventListener("click", async () => {
    try {
      btnInitWorker.disabled = true;
      btnInitWorker.textContent = "Connecting...";
      const status = await invoke("init_worker");
      workerConnected = status.connected;
      updateWorkerStatus(status);
      btnPing.disabled = !workerConnected;
      btnInitWorker.textContent = workerConnected ? "Reinitialize" : "Initialize Worker";
      btnInitWorker.disabled = false;
    } catch (e) {
      workerConnected = false;
      workerStatus.textContent = "Error: " + e;
      workerStatus.className = "disconnected";
      btnPing.disabled = true;
      btnInitWorker.textContent = "Initialize Worker";
      btnInitWorker.disabled = false;
    }
  });

  btnPing.addEventListener("click", async () => {
    try {
      btnPing.disabled = true;
      pingResult.textContent = "Sending...";
      const response = await invoke("worker_ping", {
        message: pingMessage.value || null,
      });
      pingResult.textContent = `Pong: "${response.message}"`;
    } catch (e) {
      pingResult.textContent = "Error: " + e;
    } finally {
      btnPing.disabled = false;
    }
  });

  function updateWorkerStatus(status) {
    if (status.connected) {
      workerStatus.textContent = `Connected (v${status.version || "?"})`;
      workerStatus.className = "connected";
    } else {
      workerStatus.textContent = status.error || "Disconnected";
      workerStatus.className = "disconnected";
    }
  }

  // ============================================================
  // Debug Panel: Audit Log Test
  // ============================================================

  const btnLogEvent = document.getElementById("btn-log-event");
  const btnVerifyChain = document.getElementById("btn-verify-chain");
  const auditLogResult = document.getElementById("audit-log-result");
  const logDirSpan = document.getElementById("log-dir");

  (async () => {
    try {
      const dir = await invoke("get_log_dir");
      logDirSpan.textContent = dir;
    } catch (e) {
      logDirSpan.textContent = "N/A (browser mode)";
    }
  })();

  btnLogEvent.addEventListener("click", async () => {
    try {
      btnLogEvent.disabled = true;
      auditLogResult.textContent = "Logging...";
      const record = await invoke("log_event", {
        event: "test_event",
        user: null,
        documentId: null,
        data: { test: true, timestamp: Date.now() },
      });
      auditLogResult.textContent = `OK - hash: ${record.hash.substring(0, 20)}...`;
    } catch (e) {
      auditLogResult.textContent = "Error: " + e;
    } finally {
      btnLogEvent.disabled = false;
    }
  });

  btnVerifyChain.addEventListener("click", async () => {
    try {
      btnVerifyChain.disabled = true;
      auditLogResult.textContent = "Verifying...";
      const today = new Date().toISOString().split("T")[0];
      const result = await invoke("verify_log_chain", { date: today });
      auditLogResult.textContent = result.valid
        ? `Valid (${result.total_records} records)`
        : `INVALID at record ${result.firstInvalidIndex} (${result.totalRecords} total)`;
    } catch (e) {
      auditLogResult.textContent = "Error: " + e;
    } finally {
      btnVerifyChain.disabled = false;
    }
  });

  // ============================================================
  // Debug Panel: Document State Test
  // ============================================================

  const docResult = document.getElementById("doc-result");
  const docStatusLabel = document.getElementById("doc-status-label");
  const btnCreateDoc = document.getElementById("btn-create-doc");
  const btnGetDoc = document.getElementById("btn-get-doc");
  const btnGetSummary = document.getElementById("btn-get-summary");
  const btnAddPage = document.getElementById("btn-add-page");
  const btnAddRegion = document.getElementById("btn-add-region");
  const btnToggleRegion = document.getElementById("btn-toggle-region");
  const btnRemoveRegion = document.getElementById("btn-remove-region");
  const btnAllOn = document.getElementById("btn-all-on");
  const btnAllOff = document.getElementById("btn-all-off");
  const btnConfirmDoc = document.getElementById("btn-confirm-doc");
  const btnRollbackDoc = document.getElementById("btn-rollback-doc");
  const btnFinalizeDoc = document.getElementById("btn-finalize-doc");

  async function refreshDocStatus() {
    try {
      const status = await invoke("get_document_status");
      docStatusLabel.textContent = status ? `Status: ${status}` : "No doc";
    } catch (e) {
      docStatusLabel.textContent = "Error";
    }
  }

  btnCreateDoc.addEventListener("click", async () => {
    try {
      const docId = await invoke("create_document", {
        sourceFile: "test_sample.pdf",
        sourceHash: "sha256:testhash123",
      });
      docResult.textContent = `Created: ${docId.substring(0, 8)}...`;
      await refreshDocStatus();
    } catch (e) {
      docResult.textContent = "Error: " + e;
    }
  });

  btnGetDoc.addEventListener("click", async () => {
    try {
      const doc = await invoke("get_document");
      docResult.textContent = doc
        ? `Doc: ${doc.document_id.substring(0, 8)}... (${doc.pages?.length || 0} pages)`
        : "No document loaded";
    } catch (e) {
      docResult.textContent = "Error: " + e;
    }
  });

  btnGetSummary.addEventListener("click", async () => {
    try {
      const summary = await invoke("get_document_summary");
      docResult.textContent = summary
        ? `${summary.source_file} | ${summary.status} | r${summary.revision} | ${summary.total_regions} regions (${summary.enabled_regions} enabled)`
        : "No document";
    } catch (e) {
      docResult.textContent = "Error: " + e;
    }
  });

  btnAddPage.addEventListener("click", async () => {
    try {
      await invoke("add_page", {
        page: 1,
        widthPt: 595.28,
        heightPt: 841.89,
        rotationDeg: 0,
        extractionPath: "ocr",
      });
      docResult.textContent = "Page 1 added";
    } catch (e) {
      docResult.textContent = "Error: " + e;
    }
  });

  btnAddRegion.addEventListener("click", async () => {
    try {
      const region = {
        id: generateId(),
        bbox: [100, 200, 50, 20],
        type: "name",
        confidence: 0.92,
        enabled: true,
        source: "auto",
        note: "",
      };
      await invoke("add_region", { pageNum: 1, region });
      docResult.textContent = `Region added: ${region.id}`;
    } catch (e) {
      docResult.textContent = "Error: " + e;
    }
  });

  btnToggleRegion.addEventListener("click", async () => {
    try {
      const doc = await invoke("get_document");
      if (!doc || !doc.pages?.length || !doc.pages[0].regions?.length) {
        docResult.textContent = "No regions to toggle";
        return;
      }
      const regionId = doc.pages[0].regions[0].id;
      const enabled = await invoke("toggle_region", { pageNum: 1, regionId });
      docResult.textContent = `Region ${regionId}: ${enabled ? "ON" : "OFF"}`;
    } catch (e) {
      docResult.textContent = "Error: " + e;
    }
  });

  btnRemoveRegion.addEventListener("click", async () => {
    try {
      const doc = await invoke("get_document");
      if (!doc || !doc.pages?.length || !doc.pages[0].regions?.length) {
        docResult.textContent = "No regions to remove";
        return;
      }
      const regionId = doc.pages[0].regions[0].id;
      await invoke("remove_region", { pageNum: 1, regionId });
      docResult.textContent = `Region ${regionId} removed`;
    } catch (e) {
      docResult.textContent = "Error: " + e;
    }
  });

  btnAllOn.addEventListener("click", async () => {
    try {
      const count = await invoke("set_all_regions_enabled", { pageNum: null, enabled: true });
      docResult.textContent = `${count} regions enabled`;
      await refreshOverlay();
      logAuditEvent("all_regions_enabled", null, { count });
      await autoSaveDocument();
    } catch (e) {
      docResult.textContent = "Error: " + e;
    }
  });

  btnAllOff.addEventListener("click", async () => {
    try {
      const count = await invoke("set_all_regions_enabled", { pageNum: null, enabled: false });
      docResult.textContent = `${count} regions disabled`;
      await refreshOverlay();
      logAuditEvent("all_regions_disabled", null, { count });
      await autoSaveDocument();
    } catch (e) {
      docResult.textContent = "Error: " + e;
    }
  });

  btnConfirmDoc.addEventListener("click", async () => {
    try {
      await invoke("confirm_document", { user: "test_user" });
      docResult.textContent = "Document confirmed";
      await refreshDocStatus();
    } catch (e) {
      docResult.textContent = "Error: " + e;
    }
  });

  btnRollbackDoc.addEventListener("click", async () => {
    try {
      await invoke("rollback_document", { user: "test_user" });
      docResult.textContent = "Document rolled back to draft";
      await refreshDocStatus();
    } catch (e) {
      docResult.textContent = "Error: " + e;
    }
  });

  btnFinalizeDoc.addEventListener("click", async () => {
    try {
      await invoke("finalize_document", { user: "test_user" });
      docResult.textContent = "Document finalized";
      await refreshDocStatus();
    } catch (e) {
      docResult.textContent = "Error: " + e;
    }
  });

  // ============================================================
  // Debug Panel: Masking Overlay Test
  // ============================================================

  const btnAddTestRegions = document.getElementById("btn-add-test-regions");
  const btnAddManualRegion = document.getElementById("btn-add-manual-region");
  const btnClearOverlay = document.getElementById("btn-clear-overlay");
  const overlayResult = document.getElementById("overlay-result");
  const btnToggleTestOn = document.getElementById("btn-toggle-test-on");
  const btnToggleTestOff = document.getElementById("btn-toggle-test-off");
  const btnSelectNext = document.getElementById("btn-select-next");
  const btnDeselect = document.getElementById("btn-deselect");

  // Track test regions locally for browser testing
  let testRegions = [];

  btnAddTestRegions.addEventListener("click", () => {
    if (!maskingOverlay || !pdfViewer.isLoaded) {
      overlayResult.textContent = "Load a PDF first";
      return;
    }
    // Add several test regions at various positions on the page
    const pageW = pdfViewer.pageWidthPt;
    const pageH = pdfViewer.pageHeightPt;
    const newRegions = [
      {
        id: generateId(),
        bbox: [72, 72, 120, 20],
        type: "name",
        confidence: 0.95,
        enabled: true,
        source: "auto",
        note: "",
      },
      {
        id: generateId(),
        bbox: [72, 120, 200, 16],
        type: "address",
        confidence: 0.88,
        enabled: true,
        source: "auto",
        note: "",
      },
      {
        id: generateId(),
        bbox: [pageW - 192, 72, 120, 20],
        type: "phone",
        confidence: 0.91,
        enabled: true,
        source: "auto",
        note: "",
      },
      {
        id: generateId(),
        bbox: [72, 200, 100, 16],
        type: "email",
        confidence: 0.85,
        enabled: false,
        source: "auto",
        note: "",
      },
      {
        id: generateId(),
        bbox: [72, 260, 80, 20],
        type: "name",
        confidence: 1.0,
        enabled: true,
        source: "manual",
        note: "手動追加テスト",
      },
    ];
    testRegions = [...testRegions, ...newRegions];
    maskingOverlay.setRegions(testRegions);
    overlayResult.textContent = `Added ${newRegions.length} regions (total: ${testRegions.length})`;
  });

  btnAddManualRegion.addEventListener("click", () => {
    if (!maskingOverlay || !pdfViewer.isLoaded) {
      overlayResult.textContent = "Load a PDF first";
      return;
    }
    // Add a manual region at a random position
    const pageW = pdfViewer.pageWidthPt;
    const pageH = pdfViewer.pageHeightPt;
    const x = 72 + Math.random() * (pageW - 200);
    const y = 72 + Math.random() * (pageH - 100);
    const newRegion = {
      id: generateId(),
      bbox: [x, y, 100 + Math.random() * 100, 16 + Math.random() * 10],
      type: "custom",
      confidence: 1.0,
      enabled: true,
      source: "manual",
      note: "手動追加",
    };
    testRegions.push(newRegion);
    maskingOverlay.setRegions(testRegions);
    maskingOverlay.setSelectedRegion(newRegion.id);
    overlayResult.textContent = `Manual region added: ${newRegion.id}`;
  });

  btnClearOverlay.addEventListener("click", () => {
    if (!maskingOverlay) return;
    testRegions = [];
    maskingOverlay.clear();
    overlayResult.textContent = "Overlay cleared";
  });

  btnToggleTestOn.addEventListener("click", async () => {
    if (!maskingOverlay) return;
    testRegions.forEach((r) => (r.enabled = true));
    maskingOverlay.setRegions(testRegions);
    overlayResult.textContent = "All regions ON";
    logAuditEvent("all_regions_enabled", null, { count: testRegions.length });
  });

  btnToggleTestOff.addEventListener("click", async () => {
    if (!maskingOverlay) return;
    testRegions.forEach((r) => (r.enabled = false));
    maskingOverlay.setRegions(testRegions);
    overlayResult.textContent = "All regions OFF";
    logAuditEvent("all_regions_disabled", null, { count: testRegions.length });
  });

  btnSelectNext.addEventListener("click", () => {
    if (!maskingOverlay || testRegions.length === 0) {
      overlayResult.textContent = "No regions";
      return;
    }
    const current = maskingOverlay.selectedRegionId;
    const currentIdx = testRegions.findIndex((r) => r.id === current);
    const nextIdx = (currentIdx + 1) % testRegions.length;
    maskingOverlay.setSelectedRegion(testRegions[nextIdx].id);
    overlayResult.textContent = `Selected: ${testRegions[nextIdx].id} (${testRegions[nextIdx].type})`;
  });

  btnDeselect.addEventListener("click", () => {
    if (!maskingOverlay) return;
    maskingOverlay.setSelectedRegion(null);
    overlayResult.textContent = "Deselected";
  });
});

function toggleDebugPanel() {
  debugPanel.style.display =
    debugPanel.style.display === "none" ? "flex" : "none";
}
