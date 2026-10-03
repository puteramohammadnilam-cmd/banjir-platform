// The DOM of "Check any point": the aim panel, the GPS dialog and the line under the map that says how the flood squares
// are doing. Built with h(), so text goes in as text. What they say is in pin-words.js and when, in pin.js.
import { h } from "./dom.js";
import { WORDS } from "./pin-words.js";

export const HELP_ID = "aim-help";
const GPS_TITLE_ID = "gps-title";
const GPS_BODY_ID = "gps-body";

const action = (kind, text, onclick) => h("button", { type: "button", class: `btn btn-${kind}`, onclick }, text);

/** An element's text, written only when it changes: a live region that is written again says it again. */
const setText = (element, text) => { if (element.textContent !== text) element.textContent = text; };

/** A button's state: "ready", "blocked" (off: nothing can be done here) or "busy" (working: it keeps keyboard focus, so
 *  it is marked aria-disabled, not disabled). */
function setState(button, state) {
  button.disabled = state === "blocked";
  if (state === "busy") button.setAttribute("aria-disabled", "true");
  else button.removeAttribute("aria-disabled");
  button.classList.toggle("is-busy", state === "busy");
}

/** The panel for aim mode, built hidden. Its message goes in a polite live region, or in an alert for an error; both
 *  are there from the start, so a change to either is announced. onLocate gets the button, for focus to return to.
 *  `canLocate` is false when the browser has no geolocation: that button is then left out. */
export function createAimPanel({ onCheck, onLocate, onCancel, canLocate }) {
  const check = action("primary", WORDS.check, onCheck);
  const locate = canLocate ? action("secondary", WORDS.locate, (event) => onLocate(event.currentTarget)) : null;
  const status = h("p", { class: "aim-status", role: "status" });
  const alerts = h("div", { role: "alert" });
  const node = h("section", { class: "aim-panel", "aria-labelledby": "aim-heading", hidden: true },
    h("h3", { id: "aim-heading", class: "aim-heading" }, WORDS.heading),
    h("p", { id: HELP_ID, class: "aim-help" }, WORDS.help),
    status, alerts,
    h("div", { class: "aim-actions" }, check, locate, action("secondary", WORDS.cancel, onCancel)));
  return {
    node, check,
    contains: (element) => node.contains(element),
    show: () => { node.hidden = false; },
    hide: () => { node.hidden = true; },
    /** `view` is what pin-words describe() gives for the model. */
    paint({ text, tone, check: checkState, locate: locateState }) {
      setText(status, tone === "status" ? text : "");
      const alertText = tone === "alert" ? text : "";
      if ((alerts.textContent || "") !== alertText) alerts.replaceChildren(...(alertText ? [h("p", { class: "alert alert-inline" }, alertText)] : []));
      setState(check, checkState);
      if (locate) setState(locate, locateState);
    },
  };
}

/** The dialog that asks before the location is used. open(opener) shows it and resolves true when the person shares
 *  their location, false for "Not now" or Escape. The dialog takes focus itself, not one of its buttons: it is read
 *  first, and a key held down on the button that opened it cannot repeat onto an answer. A button shuts the dialog
 *  itself and gives focus back to the opener, so nothing waits on the browser's `close` event, which can come late.
 *  Escape is the dialog's own: `cancel` is its sign, and the browser gives focus back to what had it when the dialog
 *  opened, which is the opener. */
export function createGpsDialog() {
  let finish = null;   // settles the open() that is waiting, once
  const choose = (shared) => () => {
    dialog.close();
    finish?.(shared);
  };
  const dialog = h("dialog", { class: "dialog", tabindex: "-1", "aria-labelledby": GPS_TITLE_ID, "aria-describedby": GPS_BODY_ID },
    h("h2", { id: GPS_TITLE_ID }, WORDS.dialogTitle),
    h("p", { id: GPS_BODY_ID }, WORDS.dialogBody),
    h("div", { class: "dialog-actions" }, action("primary", WORDS.share, choose(true)), action("secondary", WORDS.notNow, choose(false))));
  dialog.addEventListener("cancel", () => finish?.(false));
  return {
    node: dialog,
    get isOpen() { return dialog.open; },
    open(opener) {
      return new Promise((resolve) => {
        finish = (shared) => {
          finish = null;
          opener?.focus();   // a no-op after Escape, when the dialog is still open: the browser gives focus back
          resolve(shared);
        };
        dialog.showModal();
        dialog.focus();
      });
    },
  };
}

/** The line under the map about the flood squares: a note (polite), or a failure (an alert, with Retry when there is
 *  something to try again). A Retry that has focus is taken away when its failure goes, so the line itself takes focus
 *  then (it can, though it is not in the tab order), and a Retry made again for another failure is given focus as the
 *  old one had it. */
export function createSquaresStatus() {
  const note = h("p", { class: "fineprint", role: "status" });
  const alerts = h("div", { role: "alert" });
  const node = h("div", { class: "squares-status", tabindex: "-1" }, note, alerts);
  const clearAlerts = () => {
    if (alerts.contains(document.activeElement)) node.focus({ preventScroll: true });
    alerts.replaceChildren();
  };
  return {
    node,
    say(text) { setText(note, text); clearAlerts(); },
    clear() { setText(note, ""); clearAlerts(); },
    fail(text, onRetry = null) {
      const hadFocus = alerts.contains(document.activeElement);
      setText(note, "");
      const retry = onRetry && h("button", { type: "button", class: "btn btn-secondary", onclick: onRetry }, WORDS.retry);
      alerts.replaceChildren(h("p", { class: "alert alert-inline" }, ...[text, retry].filter(Boolean)));
      if (hadFocus) (retry || node).focus({ preventScroll: true });
    },
  };
}
