// Before the page is drawn: the tab a link asks for (?tab=), so the header is laid out for it from the first paint and a
// shared shop link does not shift as main.js starts (main.js keeps data-tab up to date after that). A plain script, not
// a module, so it runs as the parser reaches it; its list is place.js's TABS (tests/early_tab.test.mjs holds them equal).
(() => {
  const tab = new URLSearchParams(location.search).get("tab");
  if (["overview", "business", "cost", "insurance", "reference"].includes(tab)) document.body.dataset.tab = tab;
})();
