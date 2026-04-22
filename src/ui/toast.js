// ============================================================
// Toast Notifications
// ============================================================

const TOAST_TYPES = { error: "error", warning: "warning", info: "info" };

/**
 * Show a toast notification.
 * @param {string} message - Notification message
 * @param {"error"|"warning"|"info"} type - Notification type
 */
export function showToast(message, type = "error") {
  const container = document.getElementById("toast-container");
  if (!container) return;

  const toast = document.createElement("div");
  toast.className = `toast toast-${type}`;
  toast.textContent = message;
  toast.setAttribute("role", "alert");
  toast.setAttribute("aria-live", "assertive");

  container.appendChild(toast);

  // Trigger slide-in animation
  requestAnimationFrame(() => toast.classList.add("toast-visible"));

  // Auto-dismiss after 3 seconds
  setTimeout(() => {
    toast.classList.remove("toast-visible");
    toast.addEventListener("transitionend", () => toast.remove(), { once: true });
  }, 3000);
}

export { TOAST_TYPES };
