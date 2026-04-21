const { invoke } = window.__TAURI__.core;

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
});
