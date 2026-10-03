// A very small stand-in for the browser's DOM, just enough for dom.js's h() and s() and for the tab modules (card.js,
// chat.js) to build and update a view under node:test. It keeps what the tests read (tag, attributes, children, text,
// hidden, disabled, value) and is not a spec-complete DOM. installFakeDom() gives each test a fresh `document`.

class FakeText {
  constructor(text) {
    this.text = String(text);
    this.parent = null;
  }

  get textContent() {
    return this.text;
  }
}

/** A selector as the modules use them: a tag, .class, or [attribute="value"]. */
function matches(element, selector) {
  const attribute = /^\[([\w-]+)="([^"]*)"\]$/.exec(selector);
  if (attribute) return element.getAttribute(attribute[1]) === attribute[2];
  if (selector.startsWith(".")) return (element.getAttribute("class") ?? "").split(/\s+/).includes(selector.slice(1));
  return element.tagName === selector;
}

export class FakeElement {
  constructor(tagName) {
    Object.assign(this, { tagName, attrs: new Map(), children: [], parent: null, listeners: new Map() });
    Object.assign(this, { hidden: false, disabled: false, value: "", scrollTop: 0, scrollHeight: 0, style: {}, dataset: {} });
  }

  setAttribute(name, value) {
    this.attrs.set(name, String(value));
    if (name === "hidden") this.hidden = true;
    if (name === "disabled") this.disabled = true;
  }

  getAttribute(name) {
    return this.attrs.get(name) ?? null;
  }

  removeAttribute(name) {
    this.attrs.delete(name);
    if (name === "hidden") this.hidden = false;
    if (name === "disabled") this.disabled = false;
  }

  get placeholder() {
    return this.getAttribute("placeholder") ?? "";
  }

  set placeholder(text) {
    this.setAttribute("placeholder", text);
  }

  addEventListener(type, listener) {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
  }

  /** Run this element's listeners for `type`, as the browser does for a user's click or submit. */
  dispatch(type, event = {}) {
    for (const listener of this.listeners.get(type) ?? []) listener({ preventDefault() {}, target: this, ...event });
  }

  /** A click does nothing on a disabled control, as in the browser. */
  click() {
    if (!this.disabled) this.dispatch("click");
  }

  append(...nodes) {
    for (const node of nodes) {
      const child = typeof node === "string" ? new FakeText(node) : node;
      child.parent?.removeChild(child);
      child.parent = this;
      this.children.push(child);
    }
  }

  replaceChildren(...nodes) {
    for (const child of this.children) child.parent = null;
    this.children = [];
    this.append(...nodes);
  }

  removeChild(child) {
    this.children = this.children.filter((node) => node !== child);
    child.parent = null;
  }

  after(node) {
    node.parent?.removeChild(node);
    node.parent = this.parent;
    this.parent.children.splice(this.parent.children.indexOf(this) + 1, 0, node);
  }

  remove() {
    this.parent?.removeChild(this);
  }

  contains(node) {
    return node === this || this.children.some((child) => child.contains?.(node));
  }

  get textContent() {
    return this.children.map((child) => child.textContent).join("");
  }

  set textContent(text) {
    this.replaceChildren(...(text === "" ? [] : [String(text)]));
  }

  focus() {}

  /** Every element below this one, in document order. */
  get descendants() {
    return this.children.filter((child) => child instanceof FakeElement).flatMap((child) => [child, ...child.descendants]);
  }

  querySelectorAll(selector) {
    return this.descendants.filter((element) => matches(element, selector));
  }

  querySelector(selector) {
    return this.querySelectorAll(selector)[0] ?? null;
  }
}

/** Put a fresh fake `document` (and the few browser globals the modules touch) on globalThis. */
export function installFakeDom() {
  globalThis.document = { createElement: (tag) => new FakeElement(tag), createElementNS: (_ns, tag) => new FakeElement(tag), activeElement: null };
  globalThis.requestAnimationFrame = () => 0;   // the gauge's water animation never runs here
  globalThis.getComputedStyle = () => ({ transform: "none" });
}
