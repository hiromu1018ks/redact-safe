import * as pdfjsLib from "pdfjs-dist";

// Configure PDF.js worker using Vite's URL resolution
pdfjsLib.GlobalWorkerOptions.workerSrc = new URL(
  "pdfjs-dist/build/pdf.worker.min.mjs",
  import.meta.url
).toString();

// CMap URL for CJK (Japanese/Chinese/Korean) text rendering
const cMapUrl = new URL(
  "pdfjs-dist/cmaps/",
  import.meta.url
).toString().replace(/\/?$/, "/");

export class PdfViewer {
  constructor(canvasEl) {
    this.canvas = canvasEl;
    this.ctx = canvasEl.getContext("2d");
    this.pdfDoc = null;
    this.currentPage = 1;
    this.totalPages = 0;
    this.scale = 1.5;
    this.rendering = false;
    this.pendingPage = null;
    this._pageWidthPt = 0;
    this._pageHeightPt = 0;
    this._fileName = "";

    // Callbacks
    this.onPageChange = null;
    this.onZoomChange = null;
    this.onLoad = null;
  }

  get fileName() {
    return this._fileName;
  }

  get pageWidthPt() {
    return this._pageWidthPt;
  }

  get pageHeightPt() {
    return this._pageHeightPt;
  }

  get zoomPercent() {
    return Math.round(this.scale * 100);
  }

  get isLoaded() {
    return this.pdfDoc !== null;
  }

  async loadPdf(source, fileName = "") {
    let loadingTask;
    if (source instanceof Uint8Array || source instanceof ArrayBuffer) {
      loadingTask = pdfjsLib.getDocument({
        data: source,
        cMapUrl: cMapUrl,
        cMapPacked: true,
      });
    } else {
      loadingTask = pdfjsLib.getDocument({
        url: source,
        cMapUrl: cMapUrl,
        cMapPacked: true,
      });
    }

    this.pdfDoc = await loadingTask.promise;
    this.totalPages = this.pdfDoc.numPages;
    this.currentPage = 1;
    this._fileName = fileName;

    // Get first page dimensions at scale=1 (PDF points)
    const page = await this.pdfDoc.getPage(1);
    const viewport = page.getViewport({ scale: 1.0 });
    this._pageWidthPt = viewport.width;
    this._pageHeightPt = viewport.height;

    await this.renderPage(1);

    if (this.onLoad) {
      this.onLoad({ numPages: this.totalPages, fileName });
    }

    return { numPages: this.totalPages };
  }

  async renderPage(pageNum) {
    if (!this.pdfDoc) return;
    if (this.rendering) {
      this.pendingPage = pageNum;
      return;
    }

    this.rendering = true;
    try {
      const page = await this.pdfDoc.getPage(pageNum);

      // Update page dimensions at scale=1 (PDF points)
      const unscaledViewport = page.getViewport({ scale: 1.0 });
      this._pageWidthPt = unscaledViewport.width;
      this._pageHeightPt = unscaledViewport.height;

      const viewport = page.getViewport({ scale: this.scale });

      this.canvas.width = viewport.width;
      this.canvas.height = viewport.height;

      const renderContext = {
        canvasContext: this.ctx,
        viewport: viewport,
      };

      await page.render(renderContext).promise;
      this.currentPage = pageNum;

      if (this.onPageChange) {
        this.onPageChange(pageNum, this.totalPages);
      }
    } finally {
      this.rendering = false;
      if (this.pendingPage !== null) {
        const next = this.pendingPage;
        this.pendingPage = null;
        this.renderPage(next);
      }
    }
  }

  goToPage(pageNum) {
    pageNum = parseInt(pageNum, 10);
    if (isNaN(pageNum) || pageNum < 1 || pageNum > this.totalPages) return;
    return this.renderPage(pageNum);
  }

  nextPage() {
    if (this.currentPage < this.totalPages) {
      return this.renderPage(this.currentPage + 1);
    }
  }

  prevPage() {
    if (this.currentPage > 1) {
      return this.renderPage(this.currentPage - 1);
    }
  }

  setZoom(scale) {
    this.scale = Math.max(0.25, Math.min(5.0, scale));
    if (this.pdfDoc) {
      this.renderPage(this.currentPage);
    }
    if (this.onZoomChange) {
      this.onZoomChange(this.scale);
    }
  }

  zoomIn() {
    return this.setZoom(this.scale * 1.25);
  }

  zoomOut() {
    return this.setZoom(this.scale / 1.25);
  }

  fitToWidth(containerWidth) {
    if (!this.pdfDoc || !this._pageWidthPt) return;
    this.setZoom(containerWidth / this._pageWidthPt);
  }

  /**
   * Convert screen/client coordinates to PDF point coordinates.
   * clientX, clientY are relative to the browser viewport.
   * Returns {x, y} in PDF points.
   */
  screenToPdfPoint(clientX, clientY) {
    const rect = this.canvas.getBoundingClientRect();
    const canvasX = (clientX - rect.left) * (this.canvas.width / rect.width);
    const canvasY = (clientY - rect.top) * (this.canvas.height / rect.height);
    return {
      x: canvasX / this.scale,
      y: canvasY / this.scale,
    };
  }

  /**
   * Convert PDF point coordinates to screen/client coordinates.
   * Returns {x, y} relative to the browser viewport.
   */
  pdfPointToScreen(pdfX, pdfY) {
    const rect = this.canvas.getBoundingClientRect();
    const canvasX = pdfX * this.scale;
    const canvasY = pdfY * this.scale;
    return {
      x: (canvasX / this.canvas.width) * rect.width + rect.left,
      y: (canvasY / this.canvas.height) * rect.height + rect.top,
    };
  }

  /**
   * Get bounding box in canvas pixel coordinates from PDF point bbox.
   * bbox: [x, y, width, height] in PDF points.
   * Returns {x, y, width, height} in canvas pixels.
   */
  getBBoxInCanvas(bbox) {
    return {
      x: bbox[0] * this.scale,
      y: bbox[1] * this.scale,
      width: bbox[2] * this.scale,
      height: bbox[3] * this.scale,
    };
  }

  /**
   * Get page info (dimensions in PDF points) for a specific page.
   */
  async getPageInfo(pageNum) {
    if (!this.pdfDoc) return null;
    const page = await this.pdfDoc.getPage(pageNum);
    const vp = page.getViewport({ scale: 1.0 });
    return { width: vp.width, height: vp.height };
  }

  close() {
    this.pdfDoc = null;
    this.currentPage = 1;
    this.totalPages = 0;
    this._fileName = "";
    this._pageWidthPt = 0;
    this._pageHeightPt = 0;
    this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
    this.canvas.width = 0;
    this.canvas.height = 0;
  }
}
