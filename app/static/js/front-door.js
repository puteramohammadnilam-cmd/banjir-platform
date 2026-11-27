// The site's front door: an address that names no view opens the new map (map.html), unless this browser last chose
// the old interface ("Old interface" on the new map; "New version" in this page's header switches back). So does a
// link to My business, Flood cost, Insurance or the chat (?tab=business, cost, insurance, ask), which the new map now
// opens in its sheet: its query and fragment (a point's) go along. Any other link that names an area, a section, a
// tab, a place or a flood size, or carries a point in its fragment, still opens this page, as every link made before
// does. A query that names no view (?lang=ms, a share's ?fbclid=) also goes along to the new map. A plain script at the
// top of the head, so it runs before anything is drawn or fetched; ui-choice.js writes the choice under the same key
// (tests/front_door.test.mjs holds them equal).
(() => {
  const VIEW = ["area", "section", "tab", "place", "shop", "rp"];   // place.js readUrl's fields; ?shop= from old links
  const ON_MAP = ["business", "cost", "insurance", "ask"];           // the new map's sheet tabs, and its chat
  const query = new URLSearchParams(location.search);
  let isOld = false;
  try {
    isOld = localStorage.getItem("myflood-ui") === "old";
  } catch { /* storage blocked: the default, the new map */ }
  const namesNoView = !location.hash && !VIEW.some((key) => query.has(key));
  // a point in the query (a link made wrongly, or very old) is never sent on: this page takes it out of its address
  const pointInQuery = ["place", "shop"].some((key) => query.get(key)?.startsWith("pt:"));
  if (!isOld && !pointInQuery && (namesNoView || ON_MAP.includes(query.get("tab")))) location.replace(`./map.html${location.search}${location.hash}`);
})();
