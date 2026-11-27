// The site's front door: a bare address (nothing in the query or the fragment) opens the new map (map.html), unless
// this browser last chose the old interface ("Old interface" on the new map; "New version" in this page's header
// switches back). A link that names a view, a tab or a place still opens this page. A plain script at the top of the
// head, so it runs before anything is drawn or fetched; ui-choice.js writes the choice under the same key
// (tests/front_door.test.mjs holds them equal).
(() => {
  let isOld = false;
  try {
    isOld = localStorage.getItem("myflood-ui") === "old";
  } catch { /* storage blocked: the default, the new map */ }
  if (!location.search && !location.hash && !isOld) location.replace("./map.html");
})();
