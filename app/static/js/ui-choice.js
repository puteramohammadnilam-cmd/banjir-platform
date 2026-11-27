// Which interface this browser chose last, the new map (map.html) or the old page (index.html): the switch on each
// page remembers it, and front-door.js reads it to pick where a bare address goes.
export const UI_KEY = "myflood-ui";

/** Remembers "new" or "old"; in private mode it is just not remembered, and the default is the new map. */
export function rememberUi(choice) {
  try {
    globalThis.localStorage?.setItem(UI_KEY, choice);
  } catch { /* not remembered */ }
}
