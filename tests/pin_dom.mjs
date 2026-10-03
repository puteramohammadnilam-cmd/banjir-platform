// What the "Check any point" tests need on top of fake_dom.mjs: classList, removeAttribute, closest, a <dialog> that opens
// and closes, layout boxes and a document that keeps its keydown listeners; and the flood model's coverage as the server
// sends it. A helper for pin_panel.test.mjs and pin_flow.test.mjs, not a test file. It is a stand-in for the parts of the
// browser these modules touch, no more.
import { FakeElement, installFakeDom } from "./fake_dom.mjs";

export class PanelElement extends FakeElement {
  constructor(tagName) {
    super(tagName);
    this.open = false;
    this.returnValue = "";
    this.isConnected = true;
    this.rect = { top: 0, bottom: 0, height: 0 };
    this.scrolledIntoView = 0;
  }

  removeAttribute(name) {
    this.attrs.delete(name);
    if (name === "hidden") this.hidden = false;
  }

  get classList() {
    const element = this;
    return {
      toggle(name, force) {
        const names = new Set((element.getAttribute("class") ?? "").split(/\s+/).filter(Boolean));
        if (force ?? !names.has(name)) names.add(name);
        else names.delete(name);
        element.setAttribute("class", [...names].join(" "));
      },
    };
  }

  matches(selector) {
    return selector.split(",").map((part) => part.trim()).includes(this.tagName);
  }

  /** The nearest element, this one included, that is hidden: all `closest("[hidden]")` is asked for here. */
  closest(selector) {
    if (selector !== "[hidden]") throw new Error(`the fake closest() knows only [hidden], not ${selector}`);
    for (let node = this; node; node = node.parent) if (node.hidden) return node;
    return null;
  }

  after(...nodes) {
    let at = this.parent.children.indexOf(this) + 1;
    for (const node of nodes) {
      node.parent?.removeChild(node);
      node.parent = this.parent;
      this.parent.children.splice(at, 0, node);
      at += 1;
    }
  }

  getBoundingClientRect() {
    return this.rect;
  }

  scrollIntoView() {
    this.scrolledIntoView += 1;
  }

  focus() {
    globalThis.document.activeElement = this;
  }

  /** As a browser's: opens on top, and remembers what had focus. */
  showModal() {
    this.open = true;
    this.hadFocus = globalThis.document.activeElement;
  }

  /** As a browser's: shuts, and gives focus back to what had it when it opened. */
  close() {
    if (!this.open) return;
    this.open = false;
    if (this.hadFocus) globalThis.document.activeElement = this.hadFocus;
  }
}

/** A fresh fake document, with a body, listeners that can be fired, and `window`, `Element` and `innerHeight`. */
export function installPinDom() {
  installFakeDom();
  const listeners = new Map();
  const document = globalThis.document;
  document.createElement = (tag) => new PanelElement(tag);
  document.createElementNS = (_ns, tag) => new PanelElement(tag);
  document.body = new PanelElement("body");
  document.activeElement = document.body;
  document.addEventListener = (type, listener) => listeners.set(type, [...(listeners.get(type) ?? []), listener]);
  document.removeEventListener = (type, listener) => listeners.set(type, (listeners.get(type) ?? []).filter((held) => held !== listener));
  document.listenerCount = (type) => (listeners.get(type) ?? []).length;
  /** Fire a document event, as the browser does for a key pressed anywhere in the page. */
  document.fire = (type, event) => { for (const listener of listeners.get(type) ?? []) listener({ defaultPrevented: false, ...event }); };
  globalThis.requestAnimationFrame = (callback) => { setImmediate(callback); return 0; };   // a frame comes soon, as it does
  globalThis.window = globalThis;
  globalThis.Element = PanelElement;
  globalThis.innerHeight = 800;
  return document;
}

// GET /api/coverage, as the server sends it for the shipped files.
export const E100 = { name: "N10_E100", x0: 99.97625154437965, y0: 10.00706666666666, px: 0.0008333333356347339, py: 0.0008333333333325754, rows: 11999, cols: 11999 };
export const REGIONS = [
  { id: "langkawi", box: [99.55, 6.1, 99.97, 6.55] },
  { id: "peninsula", box: [99.5, 1.15, 104.7, 6.8] },
  { id: "borneo", box: [109.5, 0.8, 119.4, 7.5] },
];
export const COVERAGE = { data_version: "a5486e860339", return_periods: [10, 100, 500], block_cells: 24, grids: [E100], regions: REGIONS };
