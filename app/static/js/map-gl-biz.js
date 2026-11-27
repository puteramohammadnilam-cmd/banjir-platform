// My business on the new map (map.html): the old interface's business card (card.js createBusiness) in a sheet over the
// map, Google Maps style. "Full details" on a shop's or a point's card opens it; the sheet's Back button, Escape and the
// phone's own back close it (opening it adds a step to the browser's history, so back does not leave the site). What
// the card shows beyond the place is asked for only when the sheet opens: the Google Maps listing (Places has a free
// monthly cap, so never on a tap of a dot) and where to move the car; a shop-front photo is read when the person adds
// one. The answers are kept for the visit, by place. Flood cost, Insurance and the chat are still the old interface's.
import * as api from "./api.js";
import { createBusiness } from "./card.js";
import { createFloodMode } from "./floodmode.js";
import { loadOnce, readShopPhoto } from "./place-data.js";
import { isPoint } from "./place.js";

const pageKey = (page) => `${page?.id}|${page?.section_id ?? ""}`;

/** `sheet` holds `panel` (#panel-business, where business.css lays the card out) and the `back` button; `status` is GET
 *  /api/status's answer; areas() resolves the listed areas (for a point in another area). `on` is what the map does:
 *  pickRp(rp), showOnMap(place), movePin(place), goto(tab, place) for the old interface's tabs, ask(place) for its chat,
 *  openArea(areaId, place), find() and checkPoint() for the empty state, and changed() when the sheet opens or closes
 *  (the map writes its link). */
export function createBusinessSheet({ sheet, panel, back, status, areas, on }) {
  const st = { place: null, page: null, rp: "50", view: null, viewKey: null, areas: [], pushed: false, ignorePop: false,
    photos: {}, listings: {}, drySpots: {} };
  const floodMode = createFloodMode();
  areas().then((list) => { st.areas = list; }, () => {});   // only a point in another area needs them, for its offer

  const idOf = () => st.place?.id;
  /** The setter for one place's answer, that place taken when it is asked for: an answer that comes after another
   *  place is on show is kept under its own place, and not drawn. */
  const store = (key, id = idOf()) => (value) => {
    st[key] = { ...st[key], [id]: value };
    if (idOf() === id) draw();
  };
  const context = () => {
    const photo = st.photos[idOf()]?.estimate;
    return { premise: st.place, rp: st.rp, floorCm: photo?.is_shop_front ? photo.floor_height_cm : 0, stock: undefined,
      dry: st.drySpots[idOf()], tide: null };
  };

  function view() {
    if (st.view && st.viewKey === pageKey(st.page)) return st.view;
    st.viewKey = pageKey(st.page);   // the card is made for one page's area: its flood record and example
    st.view = createBusiness(panel, {
      area: st.page, areas: st.areas, isReady: status?.ai_ready === true, hasMaps: status?.maps_ready === true,
      onWarning: (opener) => floodMode.open(context(), opener),
      onPhoto: (file) => {
        const id = idOf();
        readShopPhoto(file, st.photos[id], store("photos", id), (image) => api.sendPhoto({ place: id, image }));
      },
      onPick: (rp) => on.pickRp(rp),
      goto: (tab) => (tab === "overview" ? close() : on.goto(tab, st.place)),
      showOnMap: () => { const place = st.place; close(); on.showOnMap(place); },
      onMovePin: () => { const place = st.place; close(); on.movePin(place); },
      onAsk: () => on.ask(st.place),
      onOpenArea: (areaId) => on.openArea(areaId, st.place),
      onFind: () => { close(); on.find(); },
      onCheckPoint: () => { close(); on.checkPoint(); },
    });
    return st.view;
  }

  function draw() {
    const id = idOf();
    view().render({ premise: st.place, rp: st.rp, photo: st.photos[id], listing: st.listings[id], dry: st.drySpots[id] });
    floodMode.refresh(context());
  }

  function load() {
    const id = idOf();
    if (!id) return;
    if (status?.maps_ready && !isPoint(id)) loadOnce(st.listings[id], store("listings"), () => api.getPlace(id));
    loadOnce(st.drySpots[id], store("drySpots"), () => api.getDrySpot(id));
  }

  /** Hides the sheet; focus goes back to the map's card, or the map. */
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
      hide();
    }
  });
  back.addEventListener("click", close);

  return {
    isOpen: () => !sheet.hidden,
    close,
    /** Opens the sheet for `place` (a Place, or null for the empty state) on `page` (its page area, start.js
     *  pageArea); `push` adds the history step (not for a link that opens the sheet itself). */
    open(place, page, rp, { push = true } = {}) {
      Object.assign(st, { place, page, rp });
      const wasHidden = sheet.hidden;
      sheet.hidden = false;
      draw();
      load();
      if (wasHidden && push) {
        history.pushState({ sheet: "business" }, "");
        st.pushed = true;
      }
      on.changed();
      const title = panel.querySelector("h1");
      if (wasHidden && title) {
        title.setAttribute("tabindex", "-1");
        title.focus({ preventScroll: true });
      }
    },
    /** Another flood size, picked on the map or in the sheet. */
    setRp(rp) {
      st.rp = rp;
      if (!sheet.hidden) draw();
    },
  };
}
