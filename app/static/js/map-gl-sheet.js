// The old interface's place tabs on the new map (map.html), in one sheet over it, Google Maps style: My business
// (card.js, with the flood plan and Compare places under it), Flood cost (cost.js) and Insurance (insurance.js), the
// same code as the old page's. "Full details" or "Flood cost" on a card, or a tab chip, opens it; its Back button,
// Escape and the phone's own back close it (opening it adds one step to the browser's history; moving between its tabs
// adds none). What it shows beyond the place is asked for only when it is on show: the Google Maps listing (Places has
// a free monthly cap, so never on a tap of a dot), where to move the car, and Flood cost's first look. The answers are
// kept for the visit, each under the place it was asked for.
import * as api from "./api.js";
import { createBusiness } from "./card.js";
import { addCompared, createCompareCard, readCompared, saveCompared } from "./compare.js";
import { createCost, estimateState } from "./cost.js";
import { createFloodMode } from "./floodmode.js";
import { lang, t } from "./i18n.js";
import { createInsurance } from "./insurance.js";
import { loadOnce, printSheet, readShopPhoto, shrinkPhoto } from "./place-data.js";
import { isPoint } from "./place.js";
import { createPlanCard, planFigures } from "./plan.js";
import { MAX_PHOTOS } from "./stock.js";

export const SHEET_TABS = ["business", "cost", "insurance"];
const pageKey = (page) => `${page?.id}|${page?.section_id ?? ""}`;

/** `sheet` holds `panels` ({business, cost, insurance}: #panel-business and so on, where the old stylesheets lay them
 *  out), its `back` button and its `label`; `status` is GET /api/status's answer; areas() resolves the listed areas. `on`
 *  is what the map does: pickRp(rp), showOnMap(place), movePin(place), goto(tab, place) for the old interface's other
 *  tabs, ask(opener) for the chat, openArea(areaId, place), openCompared(place), find() and checkPoint() (or null) for
 *  the empty state, and changed() when the sheet opens, closes or changes tab (the map writes its link). */
export function createPlaceSheet({ sheet, panels, back, label, status, areas, on }) {
  const st = { place: null, page: null, rp: "50", tab: "business", business: null, viewKey: null, areas: [], pushed: false,
    ignorePop: false, photos: {}, listings: {}, drySpots: {}, estimates: {}, stocks: {}, plans: {}, planLanguage: lang,
    compared: readCompared() };
  const isReady = status?.ai_ready === true;
  const idOf = () => st.place?.id;
  /** The setter for one place's answer, that place taken when it is asked for: an answer that comes after another
   *  place is on show is kept under its own place, and not drawn. */
  const store = (key, id = idOf()) => (value) => {
    st[key] = { ...st[key], [id]: value };
    if (idOf() === id) draw();
  };
  const floodMode = createFloodMode();
  const context = () => {
    const photo = st.photos[idOf()]?.estimate;
    return { premise: st.place, rp: st.rp, floorCm: photo?.is_shop_front ? photo.floor_height_cm : 0, stock: st.stocks[idOf()],
      dry: st.drySpots[idOf()], tide: null };
  };
  const empty = { onFind: () => { close(); on.find(); }, onCheckPoint: on.checkPoint && (() => { close(); on.checkPoint(); }) };
  const goto = (tab) => (SHEET_TABS.includes(tab) ? showTab(tab) : on.goto(tab, st.place));
  const floorCm = () => {
    const photo = st.photos[idOf()]?.estimate;
    return photo?.is_shop_front ? photo.floor_height_cm : null;
  };

  // ---------- what the tabs send ----------

  async function sendEstimate(figures, { isAssumed = false } = {}) {
    const id = idOf();
    const set = store("estimates", id);
    const before = st.estimates[id];
    set(estimateState.busy(before, isAssumed));
    try {
      set(estimateState.done(await api.estimate({ place: id, ...figures }), isAssumed));
    } catch (error) {
      set(estimateState.failed(before, error.message, isAssumed));
    }
  }

  /** A photo of the stock inside, as main.js sendStock: one at a time, and no more than the card takes. */
  async function sendStock(file, floor) {
    const id = idOf();
    if (st.stocks[id]?.busy || (st.stocks[id]?.photos?.length ?? 0) >= MAX_PHOTOS) return;
    const set = store("stocks", id);
    const before = { photos: [], off: [], ...st.stocks[id], reject: null, error: null };
    set({ ...before, busy: true });
    try {
      const image = await shrinkPhoto(file).catch(() => { throw new Error(t("common.photoUnreadable")); });
      const result = await api.sendStock({ place: id, image, floor_height_cm: floor, language: lang });
      const reject = !result.estimate.is_shop_inside ? "notInside" : !result.estimate.items.length ? "nothing" : null;
      set({ ...before, reject, photos: reject ? before.photos : [...before.photos, result] });
    } catch (error) {
      set({ ...before, error: error.message });
    }
  }

  function toggleStock(key) {
    const now = st.stocks[idOf()];
    if (!now?.photos) return;
    const off = now.off.includes(key) ? now.off.filter((k) => k !== key) : [...now.off, key];
    store("stocks")({ ...now, off });
  }

  async function writePlan(language) {
    const id = idOf();
    if (st.plans[id]?.busy) return;
    const set = store("plans", id);
    const before = st.plans[id];
    set({ result: before?.result, busy: true });
    try {
      set({ result: await api.writePlan({ place: id, language, ...planFigures(st, id) }) });
    } catch (error) {
      set({ result: before?.result, error: error.message });
    }
  }

  function setCompared(compared) {
    saveCompared(compared);
    st.compared = compared;
    draw();
  }

  // ---------- the tabs ----------

  const plan = createPlanCard({ isReady, onWrite: writePlan, onPrint: () => printSheet(plan.node.querySelector(".plan-sheet")),
    onLanguage: (language) => { st.planLanguage = language; draw(); } });
  const compare = createCompareCard({
    onAdd: () => setCompared(addCompared(st.compared, { ...st.place, page: { areaId: st.page.id, sectionId: st.page.section_id ?? null } })),
    onRemove: (id) => setCompared(st.compared.filter((kept) => kept.id !== id)),
    onOpen: (place) => on.openCompared(place),
    onFind: empty.onFind,
  });
  const cost = createCost(panels.cost, {
    onEstimate: (figures) => sendEstimate(figures), onPick: (rp) => on.pickRp(rp), isReady, ...empty,
    onStockPhoto: (file, floor) => sendStock(file, floor), onStockToggle: toggleStock, onStockClear: () => store("stocks")(undefined),
    // as My business: the page's own area's example, for a business or a point in that area
    floodExample: (place) => (!place.is_point || place.area_id === st.page.id ? st.page.bigger_flood_example : null),
  });
  const insurance = createInsurance(panels.insurance, { goto, ...empty });

  /** My business is made for one page's area (its flood record and example), so it is made again for another; the
   *  flood plan and Compare places go under it each time. */
  function business() {
    if (st.business && st.viewKey === pageKey(st.page)) return st.business;
    st.viewKey = pageKey(st.page);
    st.business = createBusiness(panels.business, {
      area: st.page, areas: st.areas, isReady, hasMaps: status?.maps_ready === true, goto, ...empty,
      onWarning: (opener) => floodMode.open(context(), opener),
      onPhoto: (file) => {
        const id = idOf();
        if (!file || st.photos[id]?.busy) return;   // a picker closed with no photo, or one still being read
        readShopPhoto(file, st.photos[id], store("photos", id), (image) => api.sendPhoto({ place: id, image }));
      },
      onPick: (rp) => on.pickRp(rp),
      showOnMap: () => { const place = st.place; close(); on.showOnMap(place); },
      onMovePin: () => { const place = st.place; close(); on.movePin(place); },
      onAsk: (opener) => on.ask(opener),
      onOpenArea: (areaId) => on.openArea(areaId, st.place),
    });
    panels.business.append(plan.node, compare.node);
    return st.business;
  }

  /** Flood cost works out a first look by itself when it, or Insurance, is opened on a place with no estimate yet. */
  function firstLook() {
    if (!st.place || st.tab === "business" || st.estimates[idOf()]) return;
    const figures = cost.figures();
    if (figures) sendEstimate(figures, { isAssumed: true });
  }

  function draw() {
    const id = idOf();
    for (const tab of SHEET_TABS) panels[tab].hidden = tab !== st.tab;
    label.textContent = t(`tab.${st.tab}`);
    if (st.tab === "business") {
      business().render({ premise: st.place, rp: st.rp, photo: st.photos[id], listing: st.listings[id], dry: st.drySpots[id] });
      plan.node.hidden = !st.place;
      compare.node.hidden = !st.place;
      plan.render(st.plans[id], st.planLanguage);
      compare.render({ current: st.place, compared: st.compared });
    } else {   // Insurance reads the estimate Flood cost works out, so both are drawn
      cost.render(st.place, floorCm(), st.estimates[id], st.stocks[id], st.rp);
      insurance.render(st.place, st.estimates[id]);
    }
    floodMode.refresh(context());
  }

  function load() {
    const id = idOf();
    if (!id) return;
    if (st.tab === "business" && status?.maps_ready && !isPoint(id)) loadOnce(st.listings[id], store("listings"), () => api.getPlace(id));
    loadOnce(st.drySpots[id], store("drySpots"), () => api.getDrySpot(id));
  }

  function focusTitle() {
    const title = panels[st.tab].querySelector("h1");
    if (!title) return;
    title.setAttribute("tabindex", "-1");
    title.focus({ preventScroll: true });
  }

  /** Another of the sheet's tabs, on the same place: no history step, and the link follows (on.changed). */
  function showTab(tab) {
    st.tab = tab;
    draw();
    load();
    firstLook();
    on.changed();
    focusTitle();
  }

  // ---------- open and close ----------

  function hide() {
    sheet.hidden = true;
    on.changed();
  }

  /** Closes the sheet from inside the page (Back, Escape, a way on to the map): the step its opening added comes off the
   *  history too, quietly. */
  function close() {
    if (sheet.hidden) return;
    hide();
    if (!st.pushed) return;
    st.pushed = false;
    st.ignorePop = true;
    history.back();
  }

  window.addEventListener("popstate", () => {
    if (st.ignorePop) {
      st.ignorePop = false;
      on.changed();   // the entry gone back to is older than what is on show: write the link again
      return;
    }
    if (!sheet.hidden) {
      st.pushed = false;
      document.querySelectorAll?.("dialog[open]").forEach((dialog) => dialog.close());   // a swipe back with a dialog open
      hide();
      return;
    }
    on.changed();   // a forward or back that left the sheet as it was: the link follows what is on show
  });
  back.addEventListener("click", close);
  // only a point in another area needs the list, for its offer: a card made before it came is made again
  areas().then((list) => {
    st.areas = list;
    st.business = null;
    if (!sheet.hidden) draw();
  }, () => {});

  return {
    isOpen: () => !sheet.hidden,
    tab: () => st.tab,
    close,
    /** Opens the sheet on `tab` for `place` (a Place, or null for the empty state) on `page` (its page area, start.js
     *  pageArea); `push` adds the history step (not for a link that opens the sheet itself). */
    open(tab, place, page, rp, { push = true } = {}) {
      const wasHidden = sheet.hidden;
      Object.assign(st, { tab: SHEET_TABS.includes(tab) ? tab : "business", place, page, rp });
      sheet.hidden = false;
      draw();
      load();
      firstLook();
      if (wasHidden && push) {
        history.pushState({ sheet: st.tab }, "");
        st.pushed = true;
      }
      on.changed();
      if (wasHidden) focusTitle();
    },
    /** Another flood size, picked on the map or in the sheet. */
    setRp(rp) {
      st.rp = rp;
      if (!sheet.hidden) draw();
    },
  };
}
