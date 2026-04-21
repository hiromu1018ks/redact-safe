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
  }

  /**
   * Push an operation onto the undo stack.
   * @param {object} op - { type, pageNum, regionId, snapshot? }
   *   - type: "add" | "remove" | "move" | "resize" | "toggle"
   *   - pageNum: page number the operation affects
   *   - regionId: the region's ID
   *   - snapshot: the region object before the change (for add/remove/toggle)
   *   - prevBbox: [x,y,w,h] before move/resize
   */
  push(op) {
    this._stack.push(op);
    if (this._stack.length > this._maxDepth) {
      this._stack.shift();
    }
  }

  /**
   * Pop the most recent operation. Returns null if empty.
   * @returns {object|null}
   */
  pop() {
    return this._stack.length > 0 ? this._stack.pop() : null;
  }
}
