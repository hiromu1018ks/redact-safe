// ============================================================
// Modal Dialogs — Focus trap, ARIA, dialog show/hide
// ============================================================

import { isTauri, invoke } from "./app-state.js";
import { showToast } from "./toast.js";

// ============================================================
// Focus Trap Utility
// ============================================================

/**
 * Trap keyboard focus within a container element.
 * Returns a cleanup function that removes the trap.
 */
export function trapFocus(container) {
  const focusableSelector = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
  const focusableElements = () => container.querySelectorAll(focusableSelector);

  function handleTabKey(e) {
    if (e.key !== "Tab") return;

    const elements = focusableElements();
    if (elements.length === 0) return;

    const first = elements[0];
    const last = elements[elements.length - 1];

    if (e.shiftKey) {
      if (document.activeElement === first) {
        e.preventDefault();
        last.focus();
      }
    } else {
      if (document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }
  }

  container.addEventListener("keydown", handleTabKey);
  return () => container.removeEventListener("keydown", handleTabKey);
}

// ============================================================
// Password Dialog
// ============================================================

const passwordDialog = document.getElementById("password-dialog");
const passwordInput = document.getElementById("pdf-password-input");
const passwordError = document.getElementById("password-error");
const btnPasswordOk = document.getElementById("btn-password-ok");
const btnPasswordCancel = document.getElementById("btn-password-cancel");

export function showPasswordDialog() {
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

export function showPasswordError() {
  passwordError.style.display = "block";
  passwordInput.value = "";
  passwordInput.focus();
}

// ============================================================
// Signature Dialog
// ============================================================

const signatureDialog = document.getElementById("signature-dialog");
const btnSignatureContinue = document.getElementById("btn-signature-continue");
const btnSignatureCancel = document.getElementById("btn-signature-cancel");

export function showSignatureDialog() {
  return new Promise((resolve) => {
    signatureDialog.style.display = "flex";
    btnSignatureCancel.focus();
    trapFocus(signatureDialog);

    function cleanup() {
      signatureDialog.style.display = "none";
      btnSignatureContinue.removeEventListener("click", onContinue);
      btnSignatureCancel.removeEventListener("click", onCancel);
      signatureDialog.removeEventListener("keydown", onKeydown);
    }

    function onContinue() {
      cleanup();
      resolve(true);
    }

    function onCancel() {
      cleanup();
      resolve(false);
    }

    function onKeydown(e) {
      if (e.key === "Escape") {
        e.preventDefault();
        e.stopPropagation();
        onCancel();
      }
    }

    btnSignatureContinue.addEventListener("click", onContinue);
    btnSignatureCancel.addEventListener("click", onCancel);
    signatureDialog.addEventListener("keydown", onKeydown);
  });
}

// ============================================================
// Operator Dialog
// ============================================================

const operatorDialog = document.getElementById("operator-dialog");
const operatorDialogTitle = document.getElementById("operator-dialog-title");
const operatorDialogMessage = document.getElementById("operator-dialog-message");
const operatorDialogOsUsername = document.getElementById("operator-dialog-os-username");
const operatorDisplayName = document.getElementById("operator-display-name");
const btnOperatorOk = document.getElementById("btn-operator-ok");
const btnOperatorCancel = document.getElementById("btn-operator-cancel");

/** Cached OS username */
let cachedOsUsername = null;

/**
 * Get the OS login username from the backend (cached after first call).
 */
async function getOsUsername() {
  if (cachedOsUsername) return cachedOsUsername;
  if (!isTauri) return "browser_user";
  try {
    cachedOsUsername = await invoke("get_os_username");
    return cachedOsUsername;
  } catch {
    return "unknown";
  }
}

/**
 * Show operator name input dialog.
 * Pre-fills the display name with the OS username.
 * @param {string} title - Dialog title
 * @param {string} message - Dialog message
 * @returns {Promise<{osUsername: string, displayName: string}|null>}
 */
export async function showOperatorDialog(title, message) {
  const osUsername = await getOsUsername();

  return new Promise((resolve) => {
    operatorDialogTitle.textContent = title;
    operatorDialogMessage.textContent = message;
    operatorDialogOsUsername.textContent = osUsername;
    operatorDisplayName.value = osUsername;
    operatorDialog.style.display = "flex";

    setTimeout(() => {
      operatorDisplayName.focus();
      operatorDisplayName.select();
    }, 50);

    function cleanup() {
      operatorDialog.style.display = "none";
      btnOperatorOk.removeEventListener("click", onOk);
      btnOperatorCancel.removeEventListener("click", onCancel);
      operatorDisplayName.removeEventListener("keydown", onKeydown);
    }

    function onOk() {
      const displayName = operatorDisplayName.value.trim();
      if (!displayName) {
        operatorDisplayName.focus();
        return;
      }
      cleanup();
      resolve({ osUsername, displayName });
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

    btnOperatorOk.addEventListener("click", onOk);
    btnOperatorCancel.addEventListener("click", onCancel);
    operatorDisplayName.addEventListener("keydown", onKeydown);
  });
}

// ============================================================
// Finalizer Warning Dialog
// ============================================================

const finalizerWarningDialog = document.getElementById("finalizer-warning-dialog");
const btnFinalizerWarningProceed = document.getElementById("btn-finalizer-warning-proceed");
const btnFinalizerWarningCancel = document.getElementById("btn-finalizer-warning-cancel");

/**
 * Show finalizer/creator match warning dialog.
 * @returns {Promise<boolean>}
 */
export function showFinalizerWarningDialog() {
  return new Promise((resolve) => {
    finalizerWarningDialog.style.display = "flex";
    btnFinalizerWarningCancel.focus();
    trapFocus(finalizerWarningDialog);

    function cleanup() {
      finalizerWarningDialog.style.display = "none";
      btnFinalizerWarningProceed.removeEventListener("click", onProceed);
      btnFinalizerWarningCancel.removeEventListener("click", onCancel);
      finalizerWarningDialog.removeEventListener("keydown", onKeydown);
    }

    function onProceed() {
      cleanup();
      resolve(true);
    }

    function onCancel() {
      cleanup();
      resolve(false);
    }

    function onKeydown(e) {
      if (e.key === "Escape") {
        e.preventDefault();
        e.stopPropagation();
        onCancel();
      }
    }

    btnFinalizerWarningProceed.addEventListener("click", onProceed);
    btnFinalizerWarningCancel.addEventListener("click", onCancel);
    finalizerWarningDialog.addEventListener("keydown", onKeydown);
  });
}

// ============================================================
// Settings Dialog
// ============================================================

const FONT_SIZE_CLASSES = {
  standard: "",
  large: "font-size-large",
  xlarge: "font-size-xlarge",
};

const DEFAULT_SETTINGS = {
  fontSize: "standard",
  compression: "png",
  jpegQuality: 90,
};

/** Load settings from localStorage */
export function loadSettings() {
  try {
    const stored = localStorage.getItem("redactsafe_settings");
    if (stored) {
      return { ...DEFAULT_SETTINGS, ...JSON.parse(stored) };
    }
  } catch {
    // Ignore parse errors
  }
  return { ...DEFAULT_SETTINGS };
}

/** Save settings to localStorage */
export function saveSettings(settings) {
  try {
    localStorage.setItem("redactsafe_settings", JSON.stringify(settings));
  } catch {
    // Ignore storage errors
  }
}

/** Apply settings to the UI */
export function applySettings(settings) {
  document.body.classList.remove("font-size-large", "font-size-xlarge");
  const fontClass = FONT_SIZE_CLASSES[settings.fontSize] || "";
  if (fontClass) document.body.classList.add(fontClass);
}

/** Get current settings */
export let currentSettings = loadSettings();
applySettings(currentSettings);

const settingsDialog = document.getElementById("settings-dialog");
const btnSettingsOk = document.getElementById("btn-settings-ok");
const btnSettingsCancel = document.getElementById("btn-settings-cancel");
const jpegQualitySlider = document.getElementById("jpeg-quality-slider");
const jpegQualityValue = document.getElementById("jpeg-quality-value");
const jpegQualitySection = document.getElementById("jpeg-quality-section");

export function showSettingsDialog() {
  const settings = loadSettings();

  const fontRadios = document.querySelectorAll('input[name="font-size"]');
  fontRadios.forEach((r) => { r.checked = r.value === settings.fontSize; });

  const compRadios = document.querySelectorAll('input[name="compression"]');
  compRadios.forEach((r) => { r.checked = r.value === settings.compression; });

  jpegQualitySlider.value = settings.jpegQuality;
  jpegQualityValue.textContent = settings.jpegQuality;
  jpegQualitySection.style.display = settings.compression === "jpeg" ? "block" : "none";

  settingsDialog.style.display = "flex";

  setTimeout(() => {
    const firstRadio = settingsDialog.querySelector('input[type="radio"]');
    if (firstRadio) firstRadio.focus();
  }, 50);
}

export function hideSettingsDialog() {
  settingsDialog.style.display = "none";
}

export function isSettingsDialogOpen() {
  return settingsDialog.style.display === "flex";
}

// JPEG quality slider live update
jpegQualitySlider.addEventListener("input", () => {
  jpegQualityValue.textContent = jpegQualitySlider.value;
});

// Show/hide JPEG quality section when compression changes
document.querySelectorAll('input[name="compression"]').forEach((r) => {
  r.addEventListener("change", () => {
    jpegQualitySection.style.display = r.value === "jpeg" && r.checked ? "block" : "none";
  });
});

btnSettingsOk.addEventListener("click", () => {
  const fontSize = document.querySelector('input[name="font-size"]:checked')?.value || "standard";
  const compression = document.querySelector('input[name="compression"]:checked')?.value || "png";
  const jpegQuality = parseInt(jpegQualitySlider.value, 10);

  currentSettings = { fontSize, compression, jpegQuality };
  saveSettings(currentSettings);
  applySettings(currentSettings);
  hideSettingsDialog();
});

btnSettingsCancel.addEventListener("click", () => {
  hideSettingsDialog();
});

// Escape to close settings
settingsDialog.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    e.preventDefault();
    hideSettingsDialog();
  }
});

// ============================================================
// Help Dialog
// ============================================================

const helpDialog = document.getElementById("help-dialog");
const btnHelpClose = document.getElementById("btn-help-close");

export function showHelpDialog() {
  helpDialog.style.display = "flex";
  setTimeout(() => {
    btnHelpClose.focus();
  }, 50);
}

export function hideHelpDialog() {
  helpDialog.style.display = "none";
}

export function isHelpDialogOpen() {
  return helpDialog.style.display === "flex";
}

btnHelpClose.addEventListener("click", () => {
  hideHelpDialog();
});

helpDialog.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    e.preventDefault();
    hideHelpDialog();
  }
});
