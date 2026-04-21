const { invoke } = window.__TAURI__.core;

// Generate a simple UUID-like ID
function generateId() {
  return "r-" + Math.random().toString(36).substring(2, 10);
}

document.addEventListener("DOMContentLoaded", () => {
  console.log("RedactSafe initialized");

  const btnInitWorker = document.getElementById("btn-init-worker");
  const btnPing = document.getElementById("btn-ping");
  const pingMessage = document.getElementById("ping-message");
  const workerStatus = document.getElementById("worker-status");
  const pingResult = document.getElementById("ping-result");

  let workerConnected = false;

  // Initialize Python Worker
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

  // Send Ping
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

  // Audit Log Test
  const btnLogEvent = document.getElementById("btn-log-event");
  const btnVerifyChain = document.getElementById("btn-verify-chain");
  const auditLogResult = document.getElementById("audit-log-result");
  const logDirSpan = document.getElementById("log-dir");

  // Show log directory on load
  (async () => {
    try {
      const dir = await invoke("get_log_dir");
      logDirSpan.textContent = dir;
    } catch (e) {
      logDirSpan.textContent = "Error: " + e;
    }
  })();

  btnLogEvent.addEventListener("click", async () => {
    try {
      btnLogEvent.disabled = true;
      auditLogResult.textContent = "Logging...";
      const today = new Date().toISOString().split("T")[0];
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

  // Document State Test
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
      // Get doc to find a region id
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
