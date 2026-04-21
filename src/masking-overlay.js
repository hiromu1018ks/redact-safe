/**
 * MaskingOverlay - Canvas API based overlay for rendering masking regions on PDF.
 *
 * Colors:
 *   Enabled regions:  black fill (#000000)
 *   Disabled regions: grey fill 50% opacity (#808080, 50%)
 *   Selected region:  red border (#FF0000) + corner handles
 *   Auto-detected:    blue border (#4488FF)
 *   Manual:           green border (#44AA44)
 */

export class MaskingOverlay {
  /**
   * @param {HTMLCanvasElement} canvasEl - The overlay canvas element
   * @param {import('./pdf-viewer.js').PdfViewer} pdfViewer - The PDF viewer instance
   */
  constructor(canvasEl, pdfViewer) {
    this.canvas = canvasEl;
    this.ctx = canvasEl.getContext("2d");
    this.pdfViewer = pdfViewer;

    /** @type {Array<object>} regions stored for current page */
    this.regions = [];
    this.selectedRegionId = null;
    this._hoveredRegionId = null;

    // Callbacks
    this.onRegionClick = null; // (region: object | null) => void
    this.onRegionHover = null; // (region: object | null) => void
  }

  // ----------------------------------------------------------------
  // Public API
  // ----------------------------------------------------------------

  /**
   * Set the regions to render (for the current page).
   * @param {Array<object>} regions - Array of region objects with id, bbox, enabled, source
   */
  setRegions(regions) {
    this.regions = regions || [];
    this.render();
  }

  /**
   * Set or clear the selected region.
   * @param {string|null} regionId
   */
  setSelectedRegion(regionId) {
    this.selectedRegionId = regionId;
    this.render();
  }

  /**
   * Resize the overlay canvas to match the PDF canvas dimensions.
   * @param {number} width
   * @param {number} height
   */
  resize(width, height) {
    if (this.canvas.width !== width || this.canvas.height !== height) {
      this.canvas.width = width;
      this.canvas.height = height;
      this.render();
    }
  }

  /**
   * Clear all regions and selection.
   */
  clear() {
    this.regions = [];
    this.selectedRegionId = null;
    this._hoveredRegionId = null;
    this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
  }

  /**
   * Set the hovered region (for hover highlighting).
   * @param {string|null} regionId
   */
  setHoveredRegion(regionId) {
    if (this._hoveredRegionId === regionId) return;
    this._hoveredRegionId = regionId;
    this.render();
  }

  /**
   * Handle identifiers for the 8 resize handles of a selected region.
   * Corners: nw, ne, sw, se. Edge midpoints: n, e, s, w.
   */
  static HANDLE_SIZE = 6;

  /**
   * Find which resize handle is at the given client position, if any.
   * Only checks handles of the currently selected region.
   * @param {number} clientX
   * @param {number} clientY
   * @returns {string|null} Handle id ("nw","n","ne","e","se","s","sw","w") or null
   */
  findHandleAtPoint(clientX, clientY) {
    if (!this.selectedRegionId) return null;
    const region = this.regions.find((r) => r.id === this.selectedRegionId);
    if (!region) return null;

    const bbox = this.pdfViewer.getBBoxInCanvas(region.bbox);
    if (!bbox || bbox.width <= 0 || bbox.height <= 0) return null;

    const rect = this.canvas.getBoundingClientRect();
    const canvasX = (clientX - rect.left) * (this.canvas.width / rect.width);
    const canvasY = (clientY - rect.top) * (this.canvas.height / rect.height);

    const hs = MaskingOverlay.HANDLE_SIZE;
    const threshold = hs + 3; // slightly larger hit area

    const handles = {
      nw: [bbox.x, bbox.y],
      n:  [bbox.x + bbox.width / 2, bbox.y],
      ne: [bbox.x + bbox.width, bbox.y],
      e:  [bbox.x + bbox.width, bbox.y + bbox.height / 2],
      se: [bbox.x + bbox.width, bbox.y + bbox.height],
      s:  [bbox.x + bbox.width / 2, bbox.y + bbox.height],
      sw: [bbox.x, bbox.y + bbox.height],
      w:  [bbox.x, bbox.y + bbox.height / 2],
    };

    for (const [id, [hx, hy]] of Object.entries(handles)) {
      if (Math.abs(canvasX - hx) <= threshold && Math.abs(canvasY - hy) <= threshold) {
        return id;
      }
    }
    return null;
  }

  /**
   * Get the CSS cursor style for a given handle id.
   * @param {string|null} handleId
   * @returns {string}
   */
  static cursorForHandle(handleId) {
    const cursors = {
      nw: "nwse-resize", se: "nwse-resize",
      ne: "nesw-resize", sw: "nesw-resize",
      n: "ns-resize", s: "ns-resize",
      e: "ew-resize", w: "ew-resize",
    };
    return cursors[handleId] || "default";
  }

  /**
   * Find the region at a given screen/client position.
   * @param {number} clientX
   * @param {number} clientY
   * @returns {object|null} The region object or null
   */
  findRegionAtPoint(clientX, clientY) {
    const rect = this.canvas.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return null;

    const canvasX = (clientX - rect.left) * (this.canvas.width / rect.width);
    const canvasY = (clientY - rect.top) * (this.canvas.height / rect.height);

    // Iterate in reverse to find topmost region first
    for (let i = this.regions.length - 1; i >= 0; i--) {
      const region = this.regions[i];
      const bbox = this.pdfViewer.getBBoxInCanvas(region.bbox);
      if (
        bbox.width > 0 &&
        bbox.height > 0 &&
        canvasX >= bbox.x &&
        canvasX <= bbox.x + bbox.width &&
        canvasY >= bbox.y &&
        canvasY <= bbox.y + bbox.height
      ) {
        return region;
      }
    }
    return null;
  }

  // ----------------------------------------------------------------
  // Rendering
  // ----------------------------------------------------------------

  render() {
    const ctx = this.ctx;
    const w = this.canvas.width;
    const h = this.canvas.height;
    ctx.clearRect(0, 0, w, h);

    if (!this.regions.length) return;

    for (const region of this.regions) {
      this._drawRegion(region);
    }
  }

  _drawRegion(region) {
    const ctx = this.ctx;
    const bbox = this.pdfViewer.getBBoxInCanvas(region.bbox);
    if (!bbox || bbox.width <= 0 || bbox.height <= 0) return;

    const isSelected = region.id === this.selectedRegionId;
    const isHovered = region.id === this._hoveredRegionId;
    const isAuto = region.source === "auto";
    const isEnabled = region.enabled;

    // --- Fill ---
    if (isEnabled) {
      ctx.fillStyle = "#000000";
      ctx.globalAlpha = 1.0;
    } else {
      ctx.fillStyle = "#808080";
      ctx.globalAlpha = 0.5;
    }
    ctx.fillRect(bbox.x, bbox.y, bbox.width, bbox.height);
    ctx.globalAlpha = 1.0;

    // --- Border ---
    let borderColor;
    if (isSelected) {
      borderColor = "#FF0000";
    } else if (isHovered) {
      borderColor = isAuto ? "#6699FF" : "#66CC66";
    } else {
      borderColor = isAuto ? "#4488FF" : "#44AA44";
    }

    ctx.strokeStyle = borderColor;
    ctx.lineWidth = isSelected ? 2.5 : 1.5;
    ctx.strokeRect(bbox.x, bbox.y, bbox.width, bbox.height);

    // --- Selection handles ---
    if (isSelected) {
      this._drawSelectionHandles(bbox);
    }
  }

  _drawSelectionHandles(bbox) {
    const ctx = this.ctx;
    const size = 6;

    ctx.fillStyle = "#FF0000";
    ctx.strokeStyle = "#FFFFFF";
    ctx.lineWidth = 1;

    const corners = [
      [bbox.x, bbox.y],
      [bbox.x + bbox.width, bbox.y],
      [bbox.x, bbox.y + bbox.height],
      [bbox.x + bbox.width, bbox.y + bbox.height],
    ];

    for (const [cx, cy] of corners) {
      const hx = cx - size / 2;
      const hy = cy - size / 2;
      ctx.fillRect(hx, hy, size, size);
      ctx.strokeRect(hx, hy, size, size);
    }

    // Edge midpoints for resize
    const midpoints = [
      [bbox.x + bbox.width / 2, bbox.y],
      [bbox.x + bbox.width, bbox.y + bbox.height / 2],
      [bbox.x + bbox.width / 2, bbox.y + bbox.height],
      [bbox.x, bbox.y + bbox.height / 2],
    ];

    for (const [cx, cy] of midpoints) {
      const hx = cx - size / 2;
      const hy = cy - size / 2;
      ctx.fillRect(hx, hy, size, size);
      ctx.strokeRect(hx, hy, size, size);
    }
  }
}
