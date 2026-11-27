// The site's front door: an address that names no view opens the new map (map.html), unless this browser last chose
// the old interface ("Old interface" on the new map; "New version" in this page's header switches back). A link that
// names an area, a section, a tab, a place or a flood size, or carries a point in its fragment, still opens this page,
// as every link made before does. Anything else in the query (?lang=ms, a share's ?fbclid=) goes along to the new map.
// A plain script at the top of the head, so it runs before anything is drawn or fetched; ui-choice.js writes the
// choice under the same key (tests/front_door.test.mjs holds them equal).
(() => {
  const VIEW = ["area", "section", "tab", "place", "shop", "rp"];   // place.js readUrl's fields; ?shop= from old links
  const query = new URLSearchParams(location.search);
  let isOld = false;
  try {
    isOld = localStorage.getItem("myflood-ui") === "old";
  } catch { /* storage blocked: the default, the new map */ }
  if (!isOld && !location.hash && !VIEW.some((key) => query.has(key))) location.replace(`./map.html${location.search}`);
})();
