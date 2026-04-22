// ============================================================
// App State — Shared mutable state for cross-module communication
// ============================================================

export const appState = {
  // PDF viewer and overlay
  pdfViewer: null,
  maskingOverlay: null,

  // Undo management
  undoManager: null,

  // Document status
  docStatusManager: null,
  progressManager: null,

  // Region data
  allRegionsByPage: {},
  testRegions: [],

  // PDF state
  currentPdfPassword: "",
  currentSourceFilePath: "",
};

// --- Tauri API (safe access for browser fallback) ---
export const isTauri = !!window.__TAURI__;

export function invoke(cmd, args) {
  if (!isTauri) return Promise.reject(new Error("Not running in Tauri"));
  return window.__TAURI__.core.invoke(cmd, args);
}

// Generate a simple UUID-like ID
export function generateId() {
  return "r-" + Math.random().toString(36).substring(2, 10);
}

/**
 * Log an audit event (Tauri only).
 */
export function logAuditEvent(event, documentId, data) {
  if (!isTauri) return;
  invoke("log_event", { event, user: null, documentId, data }).catch(() => {});
}

/**
 * Auto-save document (Tauri only).
 */
export async function autoSaveDocument() {
  if (!isTauri) return;
  try {
    await invoke("auto_save_document");
  } catch {
    // Auto-save is best-effort; document may not have a path yet
  }
}
