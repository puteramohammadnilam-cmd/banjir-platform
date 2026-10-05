// Run from 11_Platform_Draft:  node --test tests/map_resize.test.mjs
// map.js followResize: Leaflet hears of each change to the map's box, and the area's view comes back until the map has
// been moved. Leaflet and ResizeObserver are stand-ins.
import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import { followResize } from "../app/static/js/map.js";

/** A stand-in for the Leaflet map: it records invalidateSize, and move() fires movestart as a drag, a zoom or the page
 *  going to a shop does. */
function fakeMap() {
  const listeners = [];
  const calls = [];
  return {
    calls,
    on(event, listener) { if (event === "movestart") listeners.push(listener); },
    invalidateSize(options) { calls.push(options); },
    move() { listeners.forEach((listener) => listener()); },
  };
}

/** A ResizeObserver stand-in; the function it returns fires the observer, as a change to the map's box does. */
function fakeObserver() {
  let callback = () => {};
  globalThis.ResizeObserver = class { constructor(listener) { callback = listener; } observe() {} };
  return () => callback([]);
}

afterEach(() => { delete globalThis.ResizeObserver; });

/** The map watched, with a showView that moves the map as Leaflet's fitBounds does; returns what was shown. */
function watch(element = { clientHeight: 500 }) {
  const resize = fakeObserver();
  const map = fakeMap();
  const shown = [];
  followResize(map, element, () => { shown.push("view"); map.move(); });
  return { resize, map, shown, element };
}

test("each change to the map's box goes to Leaflet, and the area's view is shown again while nobody has moved it", () => {
  const { resize, map, shown } = watch();
  resize();
  resize();
  assert.deepEqual(map.calls, [{ pan: true }, { pan: true }]);
  assert.equal(shown.length, 2, "showing the view is not a move by anyone");
});

test("once the map has been moved, a change to its box keeps it where it is", () => {
  const { resize, map, shown } = watch();
  map.move();   // a drag, or the page going to a shop
  resize();
  assert.deepEqual(map.calls, [{ pan: true }]);
  assert.equal(shown.length, 0);
});

test("a map with no height (on a tab not on show) is left alone until it has one", () => {
  const { resize, map, shown, element } = watch({ clientHeight: 0 });
  resize();
  assert.deepEqual([map.calls, shown], [[], []]);
  element.clientHeight = 600;
  resize();
  assert.equal(shown.length, 1);
});

test("without ResizeObserver nothing is watched, and nothing breaks", () => {
  const map = fakeMap();
  assert.doesNotThrow(() => followResize(map, { clientHeight: 500 }, () => assert.fail("not shown")));
  assert.deepEqual(map.calls, []);
});
