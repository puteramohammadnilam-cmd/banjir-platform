// The floating chat: a button on every tab that opens the Ask AI conversation (chat.js) in a native modal <dialog>.
// showModal() gives the focus trap and makes the rest of the page inert, and Escape closes it, all by the browser. This
// file adds what the browser does not: aria-expanded on the button, focus back to whatever opened it, a click on the
// backdrop, and the end of a recording or a spoken answer when the conversation is closed.

const PHONE = "(max-width: 720px)";   // the same width views.css turns the panel into a bottom sheet at

/** Whether a click landed on the backdrop: the dialog is its target, but outside the dialog's own box. */
function isBackdropClick(dialog, event) {
  if (event.target !== dialog) return false;
  const box = dialog.getBoundingClientRect();
  return event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom;
}

/** `button` is the floating button, `dialog` the conversation, `input` the question box. onClose() runs after each
 *  close (main.js stops the reading aloud there). Returns open(opener), close() and isOpen. opener is the control that
 *  asked, so closing gives it focus back; with none, or one that has left the page, focus goes to the floating button.
 *  The button starts hidden: it shows once this is built, so a page that failed to start has no button that does nothing. */
export function createChatWidget({ button, dialog, input = null, onClose = () => {} }) {
  let opener = null;

  /** On a phone the keyboard would cover most of the sheet, so the dialog itself is read first, not the question box. */
  const focusStart = () => ((input && !input.disabled && !globalThis.matchMedia?.(PHONE).matches) ? input : dialog).focus();

  function open(from = null) {
    if (dialog.open) return;
    opener = from;
    dialog.showModal();
    button.setAttribute("aria-expanded", "true");
    focusStart();
  }

  function close() {
    dialog.close();   // its `close` event does the rest, so Escape and a button end the same way
  }

  // A recording left on would go on listening behind a closed dialog: stopping it sends what was heard, as it would anyway.
  function stopMicrophone() {
    const mic = dialog.querySelector(".mic");
    if (mic?.getAttribute("aria-pressed") === "true") mic.click();
  }

  dialog.addEventListener("close", () => {
    button.setAttribute("aria-expanded", "false");
    stopMicrophone();
    onClose();
    const target = opener?.isConnected ? opener : button;
    opener = null;
    target.focus();
  });
  dialog.addEventListener("click", (event) => {
    if (isBackdropClick(dialog, event)) close();
  });
  button.addEventListener("click", () => open(button));
  button.hidden = false;
  return { open, close, get isOpen() { return dialog.open; } };
}
