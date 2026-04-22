/**
 * UndoManager - Tracks operations for Ctrl+Z undo support.
 *
 * Each operation stores enough info to reverse it.
 * Operations: add, remove, move, resize, toggle.
 */

export class UndoManager {
  constructor() {
    /** @type {Array<object>} undo stack (newest last) */
    this._stack = [];
    /** Max undo depth */
    this._maxDepth = 50;
    /** @type {object|null} Current macro being recorded */
    this._macro = null;
  }

  get canUndo() {
    return this._stack.length > 0;
  }

  get depth() {
    return this._stack.length;
  }

  /** Clear all undo history */
  clear() {
    this._stack = [];
    this._macro = null;
  }

  /**
   * Begin recording a macro (batch of operations that undo as one step).
   * @param {string} label - Description for the macro (e.g. "全てON")
   */
  beginMacro(label = "macro") {
    this._macro = { type: "macro", label, ops: [] };
  }

  /**
   * End recording a macro and push it onto the undo stack.
   * If no macro is being recorded, this is a no-op.
   */
  endMacro() {
    if (!this._macro) return;
    if (this._macro.ops.length > 0) {
      this._stack.push(this._macro);
      if (this._stack.length > this._maxDepth) {
        this._stack.shift();
      }
    }
    this._macro = null;
  }

  /**
   * Push an operation onto the undo stack (or into the current macro).
   * @param {object} op - { type, pageNum, regionId, snapshot? }
   *   - type: "add" | "remove" | "move" | "resize" | "toggle"
   *   - pageNum: page number the operation affects
   *   - regionId: the region's ID
   *   - snapshot: the region object before the change (for add/remove/toggle)
   *   - prevBbox: [x,y,w,h] before move/resize
   */
  push(op) {
    if (this._macro) {
      this._macro.ops.push(op);
    } else {
      this._stack.push(op);
      if (this._stack.length > this._maxDepth) {
        this._stack.shift();
      }
    }
  }

  /**
   * Pop the most recent operation (or macro). Returns null if empty.
   * @returns {object|null}
   */
  pop() {
    return this._stack.length > 0 ? this._stack.pop() : null;
  }
}
