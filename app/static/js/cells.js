/* global L */
// The flood model's squares around a point someone checked, for the part of the map no area has squares for. They come
// with the point, in the answer to POST /api/point: `blocks` (the 2 x 2 blocks of the grid they are from) and `cells` (the
// blocks' wet squares). One "neighbourhood" is the blocks that one point came with. The layer keeps the last few, draws a
// square once however many neighbourhoods hold it, and takes a square off the map when none holds it any more. It asks
// the server for nothing: a block asked for by its address would put the area in the URL, and so in every log.
import { band, bandColor } from "./dom.js";

export const MAX_NEIGHBOURHOODS = 4;
const CELL_OPACITY = 0.28;   // the squares are background: the shop dots carry the depth
const CELL_FIELDS = 5;       // [south, west, depth at 1 in 10, 1 in 100, 1 in 500], as in town.json `cells`

/** The paint of one square: the colour of its depth for the flood size at `index` of its depths, or none when dry. */
export const squareStyle = (depths, index) => ({
  fillColor: bandColor(depths[index]),
  fillOpacity: band(depths[index]) ? CELL_OPACITY : 0,
});

/** A name for the blocks one point came with, the same whatever order they are given in. */
export const neighbourhoodId = (grid, blocks) => `${grid.name}:${blocks.map(({ bi, bj }) => `${bi}.${bj}`).sort().join(",")}`;

/** The ledger of what is on the map: [{id, keys}] for each neighbourhood, oldest first. Adding one gives
 *   ledger  the ledger now, with at most `max` neighbourhoods;
 *   fresh   the squares to draw: those no neighbourhood held before;
 *   stale   the squares to take off: those only the neighbourhoods that fell out held.
 *  A neighbourhood already there is only made the newest. Nothing is changed in place. */
export function addNeighbourhood(ledger, id, keys, max = MAX_NEIGHBOURHOODS) {
  const known = ledger.find((entry) => entry.id === id);
  if (known) return { ledger: [...ledger.filter((entry) => entry !== known), known], fresh: [], stale: [] };
  const entry = { id, keys: [...new Set(keys)] };
  const onMap = new Set(ledger.flatMap((held) => held.keys));
  const overflow = Math.max(0, ledger.length + 1 - max);
  const kept = [...ledger.slice(overflow), entry];
  const stillHeld = new Set(kept.flatMap((held) => held.keys));
  const stale = [...new Set(ledger.slice(0, overflow).flatMap((held) => held.keys))].filter((key) => !stillHeld.has(key));
  return { ledger: kept, fresh: entry.keys.filter((key) => !onMap.has(key)), stale };
}

const isCell = (cell) => Array.isArray(cell) && cell.length === CELL_FIELDS && Number.isFinite(cell[0]) && Number.isFinite(cell[1]);

/** What squaresOf gives for a covered point whose squares the server could not read (blocks and cells null). */
export const SQUARES_FAILED = Object.freeze({ failed: true });

/** The squares that came with a point, {blocks, cells}, from the answer of POST /api/point; SQUARES_FAILED when the server
 *  checked the point but could not read the squares around it; null when the answer has none in that form (a point
 *  nothing could be said about has none, and a point with no water near it has blocks and no cells). */
export function squaresOf(answer) {
  const { blocks, cells } = answer ?? {};
  if (Array.isArray(blocks) && Array.isArray(cells)) return { blocks, cells };
  return answer?.coverage === "covered" && blocks === null && cells === null ? SQUARES_FAILED : null;
}

function drawSquare(map, renderer, grid, [south, west, ...depths], index) {
  const bounds = [[south, west], [south + grid.py, west + grid.px]];
  const layer = L.rectangle(bounds, { stroke: false, interactive: false, renderer, ...squareStyle(depths, index) });
  return { layer: layer.addTo(map), depths };
}

/** The squares of this map's neighbourhoods. getIndex() gives the position in a square's depths of the flood size the
 *  map shows now, so a square is painted for it as it is drawn; restyle() repaints them all when that changes.
 *  isOwned(grid, south, west) says that something else draws that square already (an area's own squares do), so it is
 *  counted but not drawn. */
export function createCellLayer(map, getIndex, isOwned = () => false) {
  const renderer = L.canvas({ padding: 0.5 });   // thousands of squares: one canvas, not an element each
  const drawn = new Map();                       // key -> {layer, depths}
  let ledger = [];

  return {
    /** Draws the squares of one point's neighbourhood: its `blocks` ([{bi, bj}], which name it) and their wet `cells`, as
     *  POST /api/point gave them, on `grid` (an entry of GET /api/coverage `grids`, for the size of a square). Returns how
     *  many squares are wet there, drawn by this layer or not. Showing a neighbourhood again only makes it the newest;
     *  a square that is malformed is skipped; blocks or cells that are not lists draw nothing. */
    show(grid, blocks, cells) {
      if (!Array.isArray(blocks) || !Array.isArray(cells)) return 0;
      const wet = new Map(cells.filter(isCell).map((cell) => [`${grid.name}:${cell[0]}:${cell[1]}`, cell]));
      const mine = [...wet].filter(([, cell]) => !isOwned(grid, cell[0], cell[1]));
      const step = addNeighbourhood(ledger, neighbourhoodId(grid, blocks), mine.map(([key]) => key));
      ledger = step.ledger;
      for (const key of step.fresh) drawn.set(key, drawSquare(map, renderer, grid, wet.get(key), getIndex()));
      for (const key of step.stale) {
        drawn.get(key)?.layer.remove();
        drawn.delete(key);
      }
      return wet.size;
    },
    restyle() {
      const index = getIndex();
      for (const { layer, depths } of drawn.values()) layer.setStyle(squareStyle(depths, index));
    },
  };
}
