// The site's front door: every link opens the new map (map.html), which has all of the old page's tabs, with its query
// and fragment (a point's) as they are, unless the link asks for the old interface (ui=old: "Old interface" on the new
// map, remembered here) or this browser chose it before ("New version" in this page's header switches back). A link
// with a point in its query (made wrongly, or very old) is never sent on: this page takes the point out of its address.
// A plain script at the top of the head, so it runs before anything is drawn or fetched; ui-choice.js writes the choice
// under the same key (tests/front_door.test.mjs holds them equal).
(() => {
  const query = new URLSearchParams(location.search);
  const asksOld = query.get("ui") === "old";   // the map's links to the old interface: in a new tab, or with storage blocked
  let isOld = asksOld;
  try {
    if (asksOld) localStorage.setItem("myflood-ui", "old");
    else isOld = localStorage.getItem("myflood-ui") === "old";
  } catch { /* storage blocked: the default, the new map, unless the link asks for the old one */ }
  const pointInQuery = ["place", "shop"].some((key) => query.get(key)?.startsWith("pt:"));
  if (!isOld && !pointInQuery) location.replace(`./map.html${location.search}${location.hash}`);
})();
