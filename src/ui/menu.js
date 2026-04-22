// ============================================================
// Menu Bar (Dropdown Menus)
// ============================================================

import { appState } from "./app-state.js";

const menuDropdowns = document.querySelectorAll(".menu-dropdown");
let activeMenu = null;

/**
 * Update aria-expanded on menu triggers when menus open/close.
 */
function updateMenuAriaExpanded(menuTrigger, expanded) {
  if (menuTrigger) {
    menuTrigger.setAttribute("aria-expanded", expanded ? "true" : "false");
  }
}

/**
 * Close all open menus.
 */
export function closeAllMenus() {
  menuDropdowns.forEach((dropdown) => {
    dropdown.querySelector(".menu-popup").classList.remove("open");
    const trigger = dropdown.querySelector(".menu-trigger");
    trigger.classList.remove("active");
    updateMenuAriaExpanded(trigger, false);
  });
  activeMenu = null;
}

/**
 * Check if a menu is currently open.
 */
export function isMenuOpen() {
  return activeMenu !== null;
}

// --- Menu dropdown event handlers ---
menuDropdowns.forEach((dropdown) => {
  const trigger = dropdown.querySelector(".menu-trigger");
  const popup = dropdown.querySelector(".menu-popup");

  trigger.addEventListener("click", (e) => {
    e.stopPropagation();
    if (activeMenu === dropdown) {
      closeAllMenus();
    } else {
      closeAllMenus();
      popup.classList.add("open");
      trigger.classList.add("active");
      updateMenuAriaExpanded(trigger, true);
      activeMenu = dropdown;
    }
  });

  // Hover to switch menus when one is already open
  dropdown.addEventListener("mouseenter", () => {
    if (activeMenu && activeMenu !== dropdown) {
      closeAllMenus();
      popup.classList.add("open");
      trigger.classList.add("active");
      updateMenuAriaExpanded(trigger, true);
      activeMenu = dropdown;
    }
  });
});

// Close menus on click outside
document.addEventListener("click", (e) => {
  if (!e.target.closest(".menu-dropdown")) {
    closeAllMenus();
  }
});

// Close menus on Escape
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && activeMenu) {
    closeAllMenus();
    e.stopPropagation();
  }
});

// --- Menu item actions ---
document.getElementById("menu-item-open").addEventListener("click", () => {
  closeAllMenus();
  if (!appState.docStatusManager.getStatus()) {
    if (appState.openPdfFile) appState.openPdfFile();
  }
});

document.getElementById("menu-item-settings").addEventListener("click", () => {
  closeAllMenus();
  if (appState.showSettingsDialog) appState.showSettingsDialog();
});

document.getElementById("menu-item-shortcuts").addEventListener("click", () => {
  closeAllMenus();
  if (appState.showHelpDialog) appState.showHelpDialog();
});
