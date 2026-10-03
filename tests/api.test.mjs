// Run from 11_Platform_Draft:  node --test tests/api.test.mjs
// How api.js words a failure: the server's own words, no connection at all, or an answer that is not the app's JSON
// (a proxy's error page, say), which must not be blamed on the person's connection.
import assert from "node:assert/strict";
import { test } from "node:test";

import { ApiError, getStatus } from "../app/static/js/api.js";

const answering = (json) => { globalThis.fetch = async () => ({ json }); };

test("the server's own words come through as they are", async () => {
  answering(async () => ({ success: false, data: null, error: "Too many requests. Please wait a few minutes." }));
  await assert.rejects(getStatus(), (error) => error instanceof ApiError && error.message === "Too many requests. Please wait a few minutes.");
});

test("no connection says to check it", async () => {
  globalThis.fetch = async () => { throw new TypeError("Failed to fetch"); };
  await assert.rejects(getStatus(), (error) => error instanceof ApiError && error.message.startsWith("Could not reach the server."));
});

test("an answer that is not JSON says the server did not answer properly, not that the connection failed", async () => {
  answering(async () => { throw new SyntaxError("Unexpected token '<'"); });
  await assert.rejects(getStatus(), (error) => error instanceof ApiError && error.message === "The server did not answer properly. Try again shortly.");
});

test("a good answer gives its data", async () => {
  answering(async () => ({ success: true, data: { points_ready: true }, error: null }));
  assert.deepEqual(await getStatus(), { points_ready: true });
});
