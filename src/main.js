import { PdfViewer } from "./pdf-viewer.js";
import { MaskingOverlay } from "./masking-overlay.js";
import { UndoManager } from "./undo-manager.js";
import { appState, isTauri, invoke, generateId, logAuditEvent, autoSaveDocument } from "./ui/app-state.js";
import { showToast } from "./ui/toast.js";
import { renderSidebar, updateSidebarRegions } from "./ui/sidebar.js";
import { closeAllMenus, isMenuOpen } from "./ui/menu.js";
import {
  trapFocus,
  showPasswordDialog, showPasswordError, showSignatureDialog,
  showOperatorDialog, showFinalizerWarningDialog,
  showSettingsDialog, hideSettingsDialog, isSettingsDialogOpen,
  showHelpDialog, hideHelpDialog, isHelpDialogOpen,
} from "./ui/dialogs.js";

// ============================================================
// Wire cross-module function references into appState
// ============================================================

appState.openPdfFile = openPdfFile; // forward reference, set below
appState.showSettingsDialog = showSettingsDialog;
appState.showHelpDialog = showHelpDialog;

// ============================================================
// Watermark Manager
// ============================================================

const watermarkEl = document.getElementById("watermark");

async function updateWatermark() {
  if (!isTauri) {
    watermarkEl.style.display = "flex";
    return;
  }

  try {
    const status = await invoke("get_document_status");
    if (status === "draft" || status === "confirmed") {
      watermarkEl.style.display = "flex";
    } else {
      watermarkEl.style.display = "none";
    }
  } catch {
    watermarkEl.style.display = "none";
  }
}

// ============================================================
// Document Status Manager
// ============================================================

const STATUS_LABELS = {
  draft: "下書き",
  confirmed: "確認済み",
  finalized: "確定済み",
};

let currentDocStatus = null;

const docStatusManager = {
  async refresh() {
    if (!isTauri) {
      currentDocStatus = "draft";
    } else {
      try {
        currentDocStatus = await invoke("get_document_status");
      } catch {
        currentDocStatus = null;
      }
    }
    this.updateUI();
  },

  getStatus() {
    return currentDocStatus;
  },

  isEditable() {
    return currentDocStatus === "draft";
  },

  canConfirm() {
    return currentDocStatus === "draft";
  },

  canRollback() {
    return currentDocStatus === "confirmed";
  },

  canFinalize() {
    return currentDocStatus === "confirmed";
  },

  updateUI() {
    const status = currentDocStatus;
    const hasDoc = !!status;
    const { maskingOverlay, pdfViewer } = appState;

    // --- Status display badge ---
    if (status) {
      const badgeClass = `badge-${status}`;
      statusDisplay.innerHTML = `${pdfViewer.fileName ? `${pdfViewer.fileName} — ${pdfViewer.currentPage || 1} / ${pdfViewer.totalPages || "?"}ページ` : ""} <span class="status-badge ${badgeClass}">${STATUS_LABELS[status] || status}</span>`;
    } else {
      statusDisplay.textContent = "未読込";
    }

    // --- Confirm button ---
    const btnConfirm = document.getElementById("btn-confirm");
    if (btnConfirm) {
      btnConfirm.style.display = hasDoc ? "" : "none";
      btnConfirm.disabled = !this.canConfirm();
    }

    // --- Rollback button ---
    const btnRollback = document.getElementById("btn-rollback");
    if (btnRollback) {
      btnRollback.style.display = this.canRollback() ? "" : "none";
      btnRollback.disabled = !this.canRollback();
    }

    // --- Finalize button ---
    const btnFinalize = document.getElementById("btn-finalize");
    if (btnFinalize) {
      btnFinalize.disabled = !this.canFinalize();
    }

    // --- Editing controls ---
    const editable = this.isEditable();

    const btnSidebarAllOn = document.getElementById("btn-sidebar-all-on");
    const btnSidebarAllOff = document.getElementById("btn-sidebar-all-off");
    if (btnSidebarAllOn) btnSidebarAllOn.disabled = !editable || !hasDoc;
    if (btnSidebarAllOff) btnSidebarAllOff.disabled = !editable || !hasDoc;

    const btnToolbarAllOn = document.getElementById("btn-toolbar-all-on");
    const btnToolbarAllOff = document.getElementById("btn-toolbar-all-off");
    if (btnToolbarAllOn) btnToolbarAllOn.disabled = !editable || !hasDoc;
    if (btnToolbarAllOff) btnToolbarAllOff.disabled = !editable || !hasDoc;

    if (maskingOverlay) {
      if (editable) {
        overlayCanvas.classList.remove("interaction-disabled");
      } else {
        overlayCanvas.classList.add("interaction-disabled");
      }
    }

    const warningBanner = document.getElementById("warning-banner");
    if (warningBanner) {
      if (status === "draft" || status === "confirmed") {
        warningBanner.style.display = "flex";
      } else {
        warningBanner.style.display = "none";
      }
    }

    if (modeDisplay) {
      if (!status) {
        modeDisplay.textContent = "";
        modeDisplay.className = "mode-display";
      } else if (status === "draft") {
        modeDisplay.textContent = "編集モード";
        modeDisplay.className = "mode-display mode-edit";
      } else if (status === "confirmed") {
        modeDisplay.textContent = "確認モード";
        modeDisplay.className = "mode-display mode-review";
      } else if (status === "finalized") {
        modeDisplay.textContent = "確定済み";
        modeDisplay.className = "mode-display mode-finalized";
      }
    }

    if (statusBarText) {
      if (status) {
        statusBarText.textContent = pdfViewer.fileName
          ? `${pdfViewer.fileName} — ${pdfViewer.currentPage || 1} / ${pdfViewer.totalPages || "?"}ページ`
          : STATUS_LABELS[status] || status;
      } else {
        statusBarText.textContent = "未読込";
      }
    }
    if (statusBarBadge) {
      if (status) {
        statusBarBadge.style.display = "inline-block";
        statusBarBadge.textContent = STATUS_LABELS[status] || status;
        statusBarBadge.className = "status-bar-badge sb-" + status;
      } else {
        statusBarBadge.style.display = "none";
      }
    }
  },
};

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

    this._staleTimer = setInterval(() => this._checkStale(), 2000);

    if (isTauri && !this._cancelUnlisten) {
      this._cancelUnlisten = window.__TAURI__.event.listen("worker-progress", (event) => {
        this.update(event.payload);
      });
      this._cancelledUnlisten = window.__TAURI__.event.listen("worker-cancelled", () => {
        this.hide();
      });
    }
  },

  update(payload) {
    if (!this._active) return;
    this._lastUpdate = Date.now();
    progressStaleWarning.style.display = "none";

    const { phase, current, total, message } = payload;
    progressMessage.textContent = message || phase;

    if (total > 0) {
      const pct = Math.min(Math.round((current / total) * 100), 100);
      progressBarFill.style.width = pct + "%";
      progressPercent.textContent = pct + "%";
    } else {
      progressBarFill.classList.add("indeterminate");
      progressPercent.textContent = "";
    }
  },

  hide() {
    this._active = false;
    progressContainer.style.display = "none";
    progressBarFill.classList.remove("indeterminate");
    if (this._staleTimer) {
      clearInterval(this._staleTimer);
      this._staleTimer = null;
    }
  },

  _checkStale() {
    if (!this._active) return;
    const elapsed = Date.now() - this._lastUpdate;
    if (elapsed > 10000) {
      progressStaleWarning.style.display = "block";
    }
  },

  get isActive() {
    return this._active;
  },

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

let interaction = {
  mode: InteractionMode.NONE,
  handleId: null,
  regionId: null,
  startClientX: 0,
  startClientY: 0,
  startBbox: null,
  currentBbox: null,
};

const MIN_REGION_SIZE_PT = 5;

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
  return appState.testRegions.find((r) => r.id === regionId) || null;
}

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
    const r = appState.testRegions.find((tr) => tr.id === regionId);
    if (r) {
      if (updates.bbox) r.bbox = updates.bbox;
      if (updates.enabled !== undefined) r.enabled = updates.enabled;
    }
  }
}

async function persistAddRegion(pageNum, region) {
  if (isTauri) {
    try {
      await invoke("add_region", { pageNum, region });
    } catch (e) {
      console.error("Failed to add region:", e);
    }
  } else {
    appState.testRegions.push(region);
  }
}

async function persistRemoveRegion(pageNum, regionId) {
  if (isTauri) {
    try {
      await invoke("remove_region", { pageNum, regionId });
    } catch (e) {
      console.error("Failed to remove region:", e);
    }
  } else {
    const idx = appState.testRegions.findIndex((r) => r.id === regionId);
    if (idx !== -1) appState.testRegions.splice(idx, 1);
  }
}

async function persistToggleRegion(pageNum, regionId) {
  if (isTauri) {
    try {
      return await invoke("toggle_region", { pageNum, regionId });
    } catch (e) {
      console.error("Failed to toggle region:", e);
      return null;
    }
  } else {
    const r = appState.testRegions.find((tr) => tr.id === regionId);
    if (r) {
      r.enabled = !r.enabled;
      return r.enabled;
    }
    return null;
  }
}

async function refreshOverlay() {
  const { maskingOverlay, pdfViewer, testRegions } = appState;
  if (!maskingOverlay) return;
  if (isTauri) {
    await fetchAndDisplayRegions(pdfViewer.currentPage);
  } else {
    maskingOverlay.setRegions(testRegions);
  }
}

let autoSaveTimer = null;

function startAutoSaveTimer() {
  stopAutoSaveTimer();
  autoSaveTimer = setInterval(() => {
    autoSaveDocument();
  }, 30000);
}

function stopAutoSaveTimer() {
  if (autoSaveTimer) {
    clearInterval(autoSaveTimer);
    autoSaveTimer = null;
  }
}

function onOverlayMouseDown(e) {
  if (!maskingOverlay || !pdfViewer.isLoaded) return;
  if (e.button !== 0) return;
  if (!docStatusManager.isEditable()) return;

  const clientX = e.clientX;
  const clientY = e.clientY;

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

  const region = maskingOverlay.findRegionAtPoint(clientX, clientY);
  if (region) {
    maskingOverlay.setSelectedRegion(region.id);
    renderSidebar();
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

  maskingOverlay.setSelectedRegion(null);
  renderSidebar();
  interaction.mode = InteractionMode.DRAW_NEW;
  interaction.handleId = null;
  interaction.regionId = null;
  interaction.startClientX = clientX;
  interaction.startClientY = clientY;
  interaction.startBbox = null;
  interaction.currentBbox = null;
  e.preventDefault();
}

function onOverlayMouseMove(e) {
  if (!maskingOverlay || !pdfViewer.isLoaded) return;

  const clientX = e.clientX;
  const clientY = e.clientY;

  if (interaction.mode === InteractionMode.NONE) {
    if (docStatusManager.isEditable()) {
      const handleId = maskingOverlay.findHandleAtPoint(clientX, clientY);
      if (handleId) {
        overlayCanvas.style.cursor = MaskingOverlay.cursorForHandle(handleId);
      } else {
        const region = maskingOverlay.findRegionAtPoint(clientX, clientY);
        overlayCanvas.style.cursor = region ? "move" : "crosshair";
      }
    } else {
      overlayCanvas.style.cursor = "default";
    }
    return;
  }

  e.preventDefault();

  if (interaction.mode === InteractionMode.MOVE) {
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

    if (hid === "nw" || hid === "w" || hid === "sw") { newX += dx; newW -= dx; }
    if (hid === "ne" || hid === "e" || hid === "se") { newW += dx; }
    if (hid === "nw" || hid === "n" || hid === "ne") { newY += dy; newH -= dy; }
    if (hid === "sw" || hid === "s" || hid === "se") { newH += dy; }

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
    const startPt = pdfViewer.screenToPdfPoint(interaction.startClientX, interaction.startClientY);
    const currentPt = pdfViewer.screenToPdfPoint(clientX, clientY);

    const x = Math.min(startPt.x, currentPt.x);
    const y = Math.min(startPt.y, currentPt.y);
    const w = Math.abs(currentPt.x - startPt.x);
    const h = Math.abs(currentPt.y - startPt.y);

    interaction.currentBbox = [x, y, w, h];
    _drawNewRegionPreview(x, y, w, h);
  }
}

function _drawNewRegionPreview(x, y, w, h) {
  if (!maskingOverlay) return;
  const ctx = maskingOverlay.ctx;
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

async function onOverlayMouseUp(e) {
  if (interaction.mode === InteractionMode.NONE) return;

  const pageNum = pdfViewer.currentPage;

  if (interaction.mode === InteractionMode.MOVE) {
    if (interaction.currentBbox && interaction.startBbox) {
      const changed =
        interaction.currentBbox[0] !== interaction.startBbox[0] ||
        interaction.currentBbox[1] !== interaction.startBbox[1];
      if (changed) {
        undoManager.push({
          type: "move",
          pageNum,
          regionId: interaction.regionId,
          prevBbox: interaction.startBbox,
        });
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
        await updateSidebarRegions();
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
        await updateSidebarRegions();
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
        await updateSidebarRegions();
      }
    }
    await refreshOverlay();
  }

  interaction.mode = InteractionMode.NONE;
  interaction.handleId = null;
  interaction.regionId = null;
  interaction.startBbox = null;
  interaction.currentBbox = null;
}

async function performUndo() {
  if (!docStatusManager.isEditable()) return;
  const op = undoManager.pop();
  if (!op) return;

  if (op.type === "macro") {
    for (const macroOp of op.ops) {
      await undoSingleOp(macroOp);
    }
    logAuditEvent("undo_macro", null, { label: op.label, count: op.ops.length });
  } else {
    await undoSingleOp(op);
  }

  await refreshOverlay();
  await autoSaveDocument();
  await updateSidebarRegions();
}

async function undoSingleOp(op) {
  const pageNum = op.pageNum;

  if (pdfViewer.isLoaded && pdfViewer.currentPage !== pageNum) {
    await pdfViewer.goToPage(pageNum);
  }

  if (op.type === "move" || op.type === "resize") {
    await persistRegionUpdate(pageNum, op.regionId, { bbox: op.prevBbox });
    maskingOverlay.setSelectedRegion(op.regionId);
    logAuditEvent("undo_" + op.type, null, {
      region_id: op.regionId,
      page: pageNum,
      restored_bbox: op.prevBbox,
    });
  } else if (op.type === "add") {
    await persistRemoveRegion(pageNum, op.regionId);
    logAuditEvent("undo_add", null, {
      region_id: op.regionId,
      page: pageNum,
    });
  } else if (op.type === "remove") {
    await persistAddRegion(pageNum, op.snapshot);
    maskingOverlay.setSelectedRegion(op.regionId);
    logAuditEvent("undo_remove", null, {
      region_id: op.regionId,
      page: pageNum,
    });
  } else if (op.type === "toggle") {
    await persistToggleRegion(pageNum, op.regionId);
    maskingOverlay.setSelectedRegion(op.regionId);
    logAuditEvent("undo_toggle", null, {
      region_id: op.regionId,
      page: pageNum,
    });
  }
}

async function deleteSelectedRegion() {
  if (!maskingOverlay || !maskingOverlay.selectedRegionId) return;
  if (!docStatusManager.isEditable()) return;

  const regionId = maskingOverlay.selectedRegionId;
  const pageNum = pdfViewer.currentPage;

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
  await updateSidebarRegions();
}

async function toggleSelectedRegion() {
  if (!maskingOverlay || !maskingOverlay.selectedRegionId) return;
  if (!docStatusManager.isEditable()) return;

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
  await updateSidebarRegions();
}

// ============================================================
// DOM Elements
// ============================================================

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
const statusBarText = document.getElementById("status-bar-text");
const statusBarBadge = document.getElementById("status-bar-badge");
const modeDisplay = document.getElementById("mode-display");

const btnOpenPdf = document.getElementById("btn-open-pdf");
const btnZoomIn = document.getElementById("btn-zoom-in");
const btnZoomOut = document.getElementById("btn-zoom-out");
const btnFitWidth = document.getElementById("btn-fit-width");
const btnPrevPage = document.getElementById("btn-prev-page");
const btnNextPage = document.getElementById("btn-next-page");

const debugPanel = document.getElementById("debug-panel");
const btnCloseDebug = document.getElementById("btn-close-debug");

// ============================================================
// PDF Viewer Setup
// ============================================================

function initPdfViewer() {
  pdfViewer = new PdfViewer(pdfCanvas);
  maskingOverlay = new MaskingOverlay(overlayCanvas, pdfViewer);

  // Store references in shared state
  appState.pdfViewer = pdfViewer;
  appState.maskingOverlay = maskingOverlay;
  appState.undoManager = undoManager;
  appState.docStatusManager = docStatusManager;
  appState.progressManager = progressManager;
  appState.fetchAndDisplayRegions = fetchAndDisplayRegions;

  pdfViewer.onLoad = ({ numPages, fileName }) => {
    canvasWrapper.classList.add("visible");
    pdfPlaceholder.classList.add("hidden");
    pdfContainer.classList.add("has-pdf");

    pdfFilename.textContent = fileName;
    pdfFilename.title = fileName;

    totalPagesSpan.textContent = numPages;
    pageInput.max = numPages;
    pageInput.value = 1;
    pageInput.disabled = false;

    btnPrevPage.disabled = false;
    btnNextPage.disabled = numPages <= 1;
    btnZoomIn.disabled = false;
    btnZoomOut.disabled = false;
    btnFitWidth.disabled = false;

    updateStatus(fileName, 1, numPages);

    if (isTauri) {
      invoke("log_event", {
        event: "file_opened",
        user: null,
        documentId: null,
        data: { file_name: fileName, num_pages: numPages },
      }).catch(() => {});

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

    updateSidebarRegions();
    updateWatermark();
    docStatusManager.refresh();

    startAutoSaveTimer();

    requestAnimationFrame(() => {
      const containerWidth = pdfContainer.clientWidth - 32;
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

    if (maskingOverlay) {
      maskingOverlay.resize(pdfCanvas.width, pdfCanvas.height);
    }

    fetchAndDisplayRegions(pageNum);
  };

  pdfViewer.onZoomChange = (scale) => {
    zoomLevel.textContent = Math.round(scale * 100) + "%";
  };
}

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
    const { allRegionsByPage } = appState;
    for (const key of Object.keys(allRegionsByPage)) delete allRegionsByPage[key];
    for (const p of doc.pages) {
      if (p.regions && p.regions.length > 0) {
        allRegionsByPage[p.page] = p.regions;
      }
    }
    renderSidebar();
  } catch (e) {
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

// ============================================================
// Utility Functions
// ============================================================

function arrayBufferToBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (let i = 0; i < bytes.byteLength; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary);
}

function generateOutputPath(sourceFilePath) {
  if (!sourceFilePath) return "document_redacted.pdf";
  const lastSlash = Math.max(sourceFilePath.lastIndexOf("/"), sourceFilePath.lastIndexOf("\\"));
  const dir = sourceFilePath.substring(0, lastSlash + 1);
  const full = sourceFilePath.substring(lastSlash + 1);
  const dotIdx = full.lastIndexOf(".");
  const baseName = dotIdx > 0 ? full.substring(0, dotIdx) : full;
  const now = new Date();
  const pad = (n) => String(n).padStart(2, "0");
  const timestamp = `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}_${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
  return `${dir}${baseName}_redacted_${timestamp}.pdf`;
}

// ============================================================
// PDF Analysis Flow
// ============================================================

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
    return null;
  }
  try {
    try {
      const workerResult = await invoke("init_worker");
      console.log("Python worker initialized:", workerResult);
    } catch (e) {
      console.error("Python worker initialization failed:", e);
      return null;
    }

    progressManager.show();
    progressManager.update({ phase: "analyzing", current: 0, total: 1, message: "PDFを解析中..." });

    let invokeParams;
    if (appState.currentSourceFilePath) {
      invokeParams = { filePath: appState.currentSourceFilePath, password: null };
    } else {
      invokeParams = { pdfDataBase64: arrayBufferToBase64(pdfData), password: null };
    }
    const result = await invoke("analyze_pdf", invokeParams);
    return result;
  } catch (e) {
    console.error("PDF analysis via Python worker failed:", e);
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

async function loadPdfWithAnalysis(arrayBuffer, fileName) {
  undoManager.clear();

  const analysis = await analyzePdfWithWorker(arrayBuffer);

  if (analysis) {
    if (analysis.needs_pass) {
      while (true) {
        const password = await showPasswordDialog();
        if (password === null) {
          return;
        }

        appState.currentPdfPassword = password || "";
        const decryptResult = await decryptPdfWithWorker(arrayBuffer, password);
        if (decryptResult && decryptResult.success) {
          break;
        } else {
          showPasswordError();
        }
      }
    }

    if (analysis.has_signatures) {
      const proceed = await showSignatureDialog();
      if (!proceed) {
        return;
      }
    }

    if (analysis.sha256) {
      try {
        const osUsername = await invoke("get_os_username");
        const docId = await invoke("create_document", {
          sourceFile: fileName,
          sourceHash: `sha256:${analysis.sha256}`,
          osUsername: osUsername,
          displayName: osUsername,
        });
        console.log("Document created:", docId);

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

  try {
    await pdfViewer.loadPdf(arrayBuffer, fileName);
  } catch (e) {
    console.error("Failed to load PDF:", e);
    showToast("PDFの読み込みに失敗しました: " + e.message);
    return;
  }

  if (isTauri && analysis && analysis.page_count > 0) {
    await runPiiDetection(arrayBuffer, analysis.page_count, appState.currentPdfPassword);
  }
}

async function runPiiDetection(arrayBuffer, pageCount, password) {
  let totalDetections = 0;

  try {
    progressManager.show();
    progressManager.update({
      phase: "pii_detection",
      current: 0,
      total: pageCount,
      message: "個人情報を検出中... (0/" + pageCount + "ページ)",
    });

    for (let pageIdx = 0; pageIdx < pageCount; pageIdx++) {
      try {
        progressManager.update({
          phase: "pii_detection",
          current: pageIdx + 1,
          total: pageCount,
          message: "個人情報を検出中... (" + (pageIdx + 1) + "/" + pageCount + "ページ)",
        });

        let invokeParams;
        if (appState.currentSourceFilePath) {
          invokeParams = {
            filePath: appState.currentSourceFilePath,
            pageNum: pageIdx,
            enableNameDetection: true,
            password: password || null,
          };
        } else {
          invokeParams = {
            pdfDataBase64: arrayBufferToBase64(arrayBuffer),
            pageNum: pageIdx,
            enableNameDetection: true,
            password: password || null,
          };
        }
        const result = await invoke("detect_pii_pdf", invokeParams);

        const detections = result.detections || [];
        totalDetections += detections.length;

        for (const det of detections) {
          try {
            await invoke("add_region", {
              pageNum: pageIdx + 1,
              region: {
                id: det.id || generateId(),
                bbox: det.bbox_pt || [0, 0, 0, 0],
                type: det.type || "custom",
                confidence: det.confidence || 0.5,
                enabled: true,
                source: "auto",
                note: det.rule_name || "",
              },
            });
          } catch (regionErr) {
            console.warn("Failed to add region:", det, regionErr);
          }
        }
      } catch (pageErr) {
        console.warn("PII detection failed for page", pageIdx + 1, ":", pageErr);
      }
    }

    updateSidebarRegions();
    if (pdfViewer.isLoaded) {
      fetchAndDisplayRegions(pdfViewer.currentPage);
    }

    if (isTauri) {
      invoke("get_document").then((doc) => {
        if (doc) {
          logAuditEvent("pii_detection_completed", doc.document_id, {
            total_pages: pageCount,
            total_detections: totalDetections,
          });
        }
      }).catch(() => {});
    }

    console.log("PII detection complete:", totalDetections, "regions detected across", pageCount, "pages");
  } catch (e) {
    console.warn("PII detection pipeline failed:", e);
  } finally {
    progressManager.hide();
  }
}

async function openPdfFile() {
  console.log("openPdfFile called, isTauri:", isTauri, "status:", docStatusManager.getStatus());
  if (docStatusManager.getStatus()) {
    console.log("Blocked: document already loaded");
    return;
  }

  let result = null;

  if (isTauri) {
    try {
      const { open } = await import("@tauri-apps/plugin-dialog");
      const filePath = await open({
        multiple: false,
        filters: [{ name: "PDF Files", extensions: ["pdf"] }],
      });
      console.log("Tauri file dialog result:", filePath);
      if (!filePath) return;

      appState.currentSourceFilePath = filePath;
      appState.currentPdfPassword = "";
      console.log("Reading file via Tauri invoke...");
      const base64Data = await window.__TAURI__.core.invoke("read_file_as_base64", { path: filePath });
      const binaryStr = atob(base64Data);
      const arrayBuffer = new Uint8Array(binaryStr.length);
      for (let i = 0; i < binaryStr.length; i++) {
        arrayBuffer[i] = binaryStr.charCodeAt(i);
      }
      const fileName = filePath.split(/[/\\]/).pop() || "document.pdf";
      result = { data: arrayBuffer.buffer, fileName };
      console.log("File loaded, size:", arrayBuffer.byteLength);
    } catch (e) {
      console.error("Failed to open file via Tauri dialog:", e);
      return;
    }
  } else {
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

  btnOpenPdf.addEventListener("click", openPdfFile);

  const btnToolbarAllOn = document.getElementById("btn-toolbar-all-on");
  const btnToolbarAllOff = document.getElementById("btn-toolbar-all-off");

  const btnConfirm = document.getElementById("btn-confirm");
  const btnRollback = document.getElementById("btn-rollback");
  const btnFinalize = document.getElementById("btn-finalize");

  btnConfirm.addEventListener("click", async () => {
    if (!docStatusManager.canConfirm()) return;

    const operator = await showOperatorDialog(
      "確認承認",
      "マスキング内容を確認し承認します。操作者の氏名を入力してください。"
    );
    if (!operator) return;

    try {
      await invoke("confirm_document", {
        osUsername: operator.osUsername,
        displayName: operator.displayName,
      });
      await docStatusManager.refresh();
      await updateWatermark();
      await updateSidebarRegions();
    } catch (e) {
      console.error("Failed to confirm document:", e);
      showToast("確認に失敗しました: " + e);
    }
  });

  btnRollback.addEventListener("click", async () => {
    if (!docStatusManager.canRollback()) return;

    const operator = await showOperatorDialog(
      "差し戻し",
      "確認を取り消して編集可能な状態に戻します。操作者の氏名を入力してください。"
    );
    if (!operator) return;

    try {
      await invoke("rollback_document", {
        osUsername: operator.osUsername,
        displayName: operator.displayName,
      });
      await docStatusManager.refresh();
      await updateWatermark();
      await updateSidebarRegions();
    } catch (e) {
      console.error("Failed to rollback document:", e);
      showToast("差し戻しに失敗しました: " + e);
    }
  });

  btnFinalize.addEventListener("click", async () => {
    if (!docStatusManager.canFinalize()) return;

    const operator = await showOperatorDialog(
      "確定マスキングの実行",
      "黒塗りをPDFに焼き込み、安全なPDFを生成します。操作者の氏名を入力してください。"
    );
    if (!operator) return;

    if (isTauri) {
      try {
        const isMatch = await invoke("check_finalizer_creator_match", {
          osUsername: operator.osUsername,
        });
        if (isMatch) {
          const proceed = await showFinalizerWarningDialog();
          if (!proceed) return;
        }
      } catch (e) {
        console.warn("Failed to check finalizer/creator match:", e);
      }
    }

    let summary;
    try {
      summary = await invoke("get_document_summary");
    } catch (e) {
      console.error("Failed to get document summary:", e);
      showToast("ドキュメント情報の取得に失敗しました: " + e);
      return;
    }

    const enabledRegions = summary?.enabled_regions ?? 0;
    const pageCount = summary?.page_count ?? 0;

    const confirmed = confirm(
      "確定マスキング処理を実行しますか？\n\n" +
      "・マスキング件数: " + enabledRegions + "件\n" +
      "・対象ページ数: " + pageCount + "ページ\n\n" +
      "この操作は元に戻せません。\n" +
      "黒塗りがPDFに焼き込まれ、安全なPDFが生成されます。"
    );
    if (!confirmed) return;

    try {
      progressManager.show();
      progressMessage.textContent = "安全PDFを生成中...";

      const sourceFile = appState.currentSourceFilePath || summary?.source_file;
      if (!sourceFile) {
        throw new Error("ソースPDFファイルのパスが見つかりません");
      }

      const outputPath = await window.__TAURI__.dialog.save({
        title: "安全PDFの保存",
        defaultPath: generateOutputPath(sourceFile),
        filters: [{ name: "PDFファイル", extensions: ["pdf"] }],
      });

      if (!outputPath) {
        progressManager.hide();
        return;
      }

      const result = await invoke("finalize_masking_pdf", {
        pdfPath: sourceFile,
        dpi: 300,
        marginPt: 3.0,
        password: appState.currentPdfPassword || null,
      });

      const tempOutputPath = result?.output_path;
      if (!tempOutputPath) {
        throw new Error("PDF生成に失敗しました");
      }

      await window.__TAURI__.core.invoke("copy_file", {
        from: tempOutputPath,
        to: outputPath,
      });

      try {
        await window.__TAURI__.core.invoke("remove_file", { path: tempOutputPath });
      } catch (e) {
        console.warn("Failed to clean up temp file:", e);
      }

      await invoke("finalize_document", {
        osUsername: operator.osUsername,
        displayName: operator.displayName,
      });

      await invoke("set_output_file", { path: outputPath });

      progressManager.hide();
      await docStatusManager.refresh();
      await updateWatermark();
      await updateSidebarRegions();

      logAuditEvent("document_finalized_saved", null, {
        output_path: outputPath,
        pages_processed: result?.pages_processed,
        regions_masked: result?.regions_masked,
      });
    } catch (e) {
      console.error("Failed to finalize document:", e);
      progressManager.hide();
      showToast("確定処理に失敗しました: " + e);
    }
  });

  // Block print via beforeprint event
  window.addEventListener("beforeprint", (e) => {
    if (docStatusManager.getStatus() !== "finalized") {
      e.preventDefault();
      showToast("確定済みのドキュメントのみ印刷可能です。");
    }
  });

  btnToolbarAllOn.addEventListener("click", async () => {
    const { testRegions } = appState;
    if (!isTauri) {
      testRegions.forEach((r) => (r.enabled = true));
      if (maskingOverlay) maskingOverlay.setRegions(testRegions);
      updateSidebarRegions();
      return;
    }
    try {
      undoManager.beginMacro("全てON");
      await invoke("set_all_regions_enabled", { pageNum: null, enabled: true });
      undoManager.endMacro();
      await refreshOverlay();
      await updateSidebarRegions();
      logAuditEvent("all_regions_enabled", null, {});
      await autoSaveDocument();
    } catch (e) {
      undoManager.endMacro();
      console.error("Failed to enable all regions:", e);
    }
  });

  btnToolbarAllOff.addEventListener("click", async () => {
    const { testRegions } = appState;
    if (!isTauri) {
      testRegions.forEach((r) => (r.enabled = false));
      if (maskingOverlay) maskingOverlay.setRegions(testRegions);
      updateSidebarRegions();
      return;
    }
    try {
      undoManager.beginMacro("全てOFF");
      await invoke("set_all_regions_enabled", { pageNum: null, enabled: false });
      undoManager.endMacro();
      await refreshOverlay();
      await updateSidebarRegions();
      logAuditEvent("all_regions_disabled", null, {});
      await autoSaveDocument();
    } catch (e) {
      undoManager.endMacro();
      console.error("Failed to disable all regions:", e);
    }
  });

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

  // Coordinate display on mouse move
  overlayCanvas.addEventListener("mousemove", (e) => {
    if (!pdfViewer.isLoaded) return;
    const pt = pdfViewer.screenToPdfPoint(e.clientX, e.clientY);
    coordDisplay.textContent = `${pt.x.toFixed(1)}, ${pt.y.toFixed(1)} pt`;

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

  // Interaction Engine
  overlayCanvas.addEventListener("mousedown", onOverlayMouseDown);
  window.addEventListener("mousemove", onOverlayMouseMove);
  window.addEventListener("mouseup", onOverlayMouseUp);

  // Double-click to toggle ON/OFF
  overlayCanvas.addEventListener("dblclick", (e) => {
    if (!maskingOverlay) return;
    if (!docStatusManager.isEditable()) return;
    const region = maskingOverlay.findRegionAtPoint(e.clientX, e.clientY);
    if (region) {
      maskingOverlay.setSelectedRegion(region.id);
      renderSidebar();
      toggleSelectedRegion();
    }
  });

  // Drag & Drop Support
  pdfContainer.addEventListener("dragover", (e) => {
    e.preventDefault();
    e.stopPropagation();
    if (docStatusManager.getStatus()) return;
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

    if (docStatusManager.getStatus()) {
      return;
    }

    const file = e.dataTransfer.files[0];
    if (!file) return;

    if (file.type !== "application/pdf" && !file.name.toLowerCase().endsWith(".pdf")) {
      showToast("PDFファイルのみ読み込み可能です");
      return;
    }

    try {
      const arrayBuffer = await file.arrayBuffer();
      await loadPdfWithAnalysis(arrayBuffer, file.name);
    } catch (err) {
      console.error("Failed to load dropped PDF:", err);
      showToast("PDFの読み込みに失敗しました: " + err.message);
    }
  });

  // Debug Panel
  btnCloseDebug.addEventListener("click", () => {
    debugPanel.style.display = "none";
  });

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
      const osUsername = await invoke("get_os_username");
      const docId = await invoke("create_document", {
        sourceFile: "test_sample.pdf",
        sourceHash: "sha256:testhash123",
        osUsername: osUsername,
        displayName: osUsername,
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
      await invoke("confirm_document", { osUsername: "test_user", displayName: "テストユーザー" });
      docResult.textContent = "Document confirmed";
      await refreshDocStatus();
      await updateWatermark();
      await docStatusManager.refresh();
      await updateSidebarRegions();
    } catch (e) {
      docResult.textContent = "Error: " + e;
    }
  });

  btnRollbackDoc.addEventListener("click", async () => {
    try {
      await invoke("rollback_document", { osUsername: "test_user", displayName: "テストユーザー" });
      docResult.textContent = "Document rolled back to draft";
      await refreshDocStatus();
      await updateWatermark();
      await docStatusManager.refresh();
      await updateSidebarRegions();
    } catch (e) {
      docResult.textContent = "Error: " + e;
    }
  });

  btnFinalizeDoc.addEventListener("click", async () => {
    try {
      await invoke("finalize_document", { osUsername: "test_user", displayName: "テストユーザー" });
      docResult.textContent = "Document finalized";
      await refreshDocStatus();
      await updateWatermark();
      await docStatusManager.refresh();
      await updateSidebarRegions();
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

  btnAddTestRegions.addEventListener("click", () => {
    if (!maskingOverlay || !pdfViewer.isLoaded) {
      overlayResult.textContent = "Load a PDF first";
      return;
    }
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
    appState.testRegions = [...appState.testRegions, ...newRegions];
    maskingOverlay.setRegions(appState.testRegions);
    updateSidebarRegions();
    overlayResult.textContent = `Added ${newRegions.length} regions (total: ${appState.testRegions.length})`;
  });

  btnAddManualRegion.addEventListener("click", () => {
    if (!maskingOverlay || !pdfViewer.isLoaded) {
      overlayResult.textContent = "Load a PDF first";
      return;
    }
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
    appState.testRegions.push(newRegion);
    maskingOverlay.setRegions(appState.testRegions);
    maskingOverlay.setSelectedRegion(newRegion.id);
    updateSidebarRegions();
    overlayResult.textContent = `Manual region added: ${newRegion.id}`;
  });

  btnClearOverlay.addEventListener("click", () => {
    if (!maskingOverlay) return;
    appState.testRegions = [];
    maskingOverlay.clear();
    updateSidebarRegions();
    overlayResult.textContent = "Overlay cleared";
  });

  btnToggleTestOn.addEventListener("click", async () => {
    if (!maskingOverlay) return;
    appState.testRegions.forEach((r) => (r.enabled = true));
    maskingOverlay.setRegions(appState.testRegions);
    updateSidebarRegions();
    overlayResult.textContent = "All regions ON";
    logAuditEvent("all_regions_enabled", null, { count: appState.testRegions.length });
  });

  btnToggleTestOff.addEventListener("click", async () => {
    if (!maskingOverlay) return;
    appState.testRegions.forEach((r) => (r.enabled = false));
    maskingOverlay.setRegions(appState.testRegions);
    updateSidebarRegions();
    overlayResult.textContent = "All regions OFF";
    logAuditEvent("all_regions_disabled", null, { count: appState.testRegions.length });
  });

  btnSelectNext.addEventListener("click", () => {
    if (!maskingOverlay || !pdfViewer.isLoaded) return;
    const regions = maskingOverlay.regions;
    if (regions.length === 0) return;
    const currentId = maskingOverlay.selectedRegionId;
    const currentIdx = regions.findIndex((r) => r.id === currentId);
    const nextIdx = (currentIdx + 1) % regions.length;
    maskingOverlay.setSelectedRegion(regions[nextIdx].id);
    renderSidebar();
    overlayResult.textContent = `Selected: ${regions[nextIdx].id}`;
  });

  btnDeselect.addEventListener("click", () => {
    if (!maskingOverlay) return;
    maskingOverlay.setSelectedRegion(null);
    renderSidebar();
    overlayResult.textContent = "Deselected";
  });
});

function toggleDebugPanel() {
  debugPanel.style.display =
    debugPanel.style.display === "none" ? "flex" : "none";
}

// ============================================================
// Window Resize Handler
// ============================================================

window.addEventListener("resize", () => {
  if (!pdfViewer || !pdfViewer.isLoaded) return;

  if (maskingOverlay) {
    maskingOverlay.resize(pdfCanvas.width, pdfCanvas.height);
  }

  if (maskingOverlay && maskingOverlay.regions.length > 0) {
    maskingOverlay.render();
  }
});

// ============================================================
// Unified Keyboard Shortcuts
// (Merges the two separate keydown listeners into one)
// ============================================================

document.addEventListener("keydown", (e) => {
  // Don't capture when typing in inputs
  if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA" || e.target.tagName === "SELECT") {
    return;
  }

  // Ctrl+P: Block print (capture phase handled separately below)
  if (e.ctrlKey && e.key === "p") {
    e.preventDefault();
    return;
  }

  // Ctrl+S: Block save
  if (e.ctrlKey && e.key === "s") {
    e.preventDefault();
    return;
  }

  // Ctrl+,: Open settings
  if (e.ctrlKey && e.key === ",") {
    e.preventDefault();
    showSettingsDialog();
    return;
  }

  // Ctrl+O: Open file
  if (e.ctrlKey && e.key === "o") {
    e.preventDefault();
    if (!docStatusManager.getStatus()) {
      openPdfFile();
    }
    return;
  }

  // Ctrl+W: Fit to width
  if (e.ctrlKey && e.key === "w") {
    e.preventDefault();
    if (pdfViewer && pdfViewer.isLoaded) {
      const containerWidth = pdfContainer.clientWidth - 32;
      if (containerWidth > 0) {
        pdfViewer.fitToWidth(containerWidth);
      }
    }
    return;
  }

  // Ctrl+Z: Undo
  if (e.ctrlKey && !e.shiftKey && e.key === "z") {
    e.preventDefault();
    if (docStatusManager.isEditable()) {
      performUndo();
    }
    return;
  }

  // Ctrl+Shift+D: Toggle debug panel
  if (e.ctrlKey && e.shiftKey && e.key === "D") {
    e.preventDefault();
    toggleDebugPanel();
    return;
  }

  // Escape: Close menus → close modals → deselect region
  if (e.key === "Escape" && !e.ctrlKey && !e.shiftKey) {
    // Menu close is handled by menu.js with stopPropagation
    // Settings dialog
    if (isSettingsDialogOpen()) {
      hideSettingsDialog();
      return;
    }
    // Help dialog
    if (isHelpDialogOpen()) {
      hideHelpDialog();
      return;
    }
    // Deselect region on overlay
    if (maskingOverlay && maskingOverlay.selectedRegionId) {
      maskingOverlay.setSelectedRegion(null);
      renderSidebar();
      return;
    }
    return;
  }

  // Tab: Navigate between regions
  if (e.key === "Tab" && !e.ctrlKey) {
    e.preventDefault();
    if (!maskingOverlay || !pdfViewer || !pdfViewer.isLoaded) return;

    const regions = maskingOverlay.regions;
    if (regions.length === 0) return;

    const currentId = maskingOverlay.selectedRegionId;
    const currentIdx = regions.findIndex((r) => r.id === currentId);

    let nextIdx;
    if (e.shiftKey) {
      nextIdx = currentIdx <= 0 ? regions.length - 1 : currentIdx - 1;
    } else {
      nextIdx = (currentIdx + 1) % regions.length;
    }

    maskingOverlay.setSelectedRegion(regions[nextIdx].id);
    renderSidebar();
    return;
  }

  if (!pdfViewer || !pdfViewer.isLoaded) return;

  // Delete / Backspace: Delete selected region
  if (e.key === "Delete" || e.key === "Backspace") {
    e.preventDefault();
    if (docStatusManager.isEditable()) {
      deleteSelectedRegion();
    }
    return;
  }

  // Space: Toggle selected region ON/OFF
  if (e.key === " " && !e.ctrlKey && !e.shiftKey) {
    e.preventDefault();
    if (docStatusManager.isEditable()) {
      toggleSelectedRegion();
    }
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

  // Ctrl+/Ctrl-/Ctrl+0: Zoom
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

// Ctrl+P block on capture phase (must be on window to take priority)
window.addEventListener("keydown", (e) => {
  if (e.ctrlKey && e.key === "p") {
    e.preventDefault();
    e.stopPropagation();
  }
}, true);
