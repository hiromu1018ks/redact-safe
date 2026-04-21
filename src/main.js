import { PdfViewer } from "./pdf-viewer.js";

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

// --- PDF Viewer ---
let pdfViewer = null;

// --- DOM Elements ---
const pdfCanvas = document.getElementById("pdf-canvas");
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

  pdfViewer.onLoad = ({ numPages, fileName }) => {
    // Show canvas, hide placeholder
    pdfCanvas.classList.add("visible");
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
  };

  pdfViewer.onZoomChange = (scale) => {
    zoomLevel.textContent = Math.round(scale * 100) + "%";
  };
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

  try {
    await pdfViewer.loadPdf(result.data, result.fileName);
  } catch (e) {
    console.error("Failed to load PDF:", e);
    alert("PDFの読み込みに失敗しました: " + e.message);
  }
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

  // Coordinate display on mouse move
  pdfCanvas.addEventListener("mousemove", (e) => {
    if (!pdfViewer.isLoaded) return;
    const pt = pdfViewer.screenToPdfPoint(e.clientX, e.clientY);
    coordDisplay.textContent = `${pt.x.toFixed(1)}, ${pt.y.toFixed(1)} pt`;
  });

  pdfCanvas.addEventListener("mouseleave", () => {
    coordDisplay.textContent = "";
  });

  // --- Drag & Drop Support ---
  pdfContainer.addEventListener("dragover", (e) => {
    e.preventDefault();
    e.stopPropagation();
    pdfContainer.style.outline = "3px dashed #4a90d9";
  });

  pdfContainer.addEventListener("dragleave", (e) => {
    e.preventDefault();
    e.stopPropagation();
    pdfContainer.style.outline = "";
  });

  pdfContainer.addEventListener("drop", async (e) => {
    e.preventDefault();
    e.stopPropagation();
    pdfContainer.style.outline = "";

    const file = e.dataTransfer.files[0];
    if (!file) return;

    if (file.type !== "application/pdf" && !file.name.toLowerCase().endsWith(".pdf")) {
      alert("PDFファイルのみ読み込み可能です");
      return;
    }

    try {
      const arrayBuffer = await file.arrayBuffer();
      await pdfViewer.loadPdf(arrayBuffer, file.name);
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

    // Ctrl+Shift+D: Toggle debug panel
    if (e.ctrlKey && e.shiftKey && e.key === "D") {
      e.preventDefault();
      toggleDebugPanel();
      return;
    }

    if (!pdfViewer.isLoaded) return;

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
    } catch (e) {
      docResult.textContent = "Error: " + e;
    }
  });

  btnAllOff.addEventListener("click", async () => {
    try {
      const count = await invoke("set_all_regions_enabled", { pageNum: null, enabled: false });
      docResult.textContent = `${count} regions disabled`;
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
});

function toggleDebugPanel() {
  debugPanel.style.display =
    debugPanel.style.display === "none" ? "flex" : "none";
}
