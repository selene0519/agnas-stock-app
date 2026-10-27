/* eslint-disable @typescript-eslint/no-require-imports -- CommonJS harness for the transpiled API module. */
const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const { test } = require("node:test");
const vm = require("node:vm");
const ts = require("typescript");

// Exercise the real API cache and network path with localStorage/fetch in memory.
function runtime(fetch) {
  const storage = new Map();
  const resultModule = { exports: {} };
  const source = readFileSync(path.join(__dirname, "../lib/api.ts"), "utf8");
  const code = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  vm.runInNewContext(code, {
    module: resultModule, exports: resultModule.exports,
    require(name) {
      if (name === "./userId") return { getAuthenticatedUserId: () => "", getUserToken: () => "" };
      if (name === "./adminAuth") return { adminAuthHeaders: () => ({}) };
      throw new Error(`Unexpected dependency ${name}`);
    },
    window: {
      location: { origin: "http://localhost:3012", hostname: "localhost" },
      localStorage: {
        getItem: (key) => storage.get(key) ?? null,
        setItem: (key, value) => storage.set(key, value),
        removeItem: (key) => storage.delete(key),
        key: (index) => [...storage.keys()][index] ?? null,
        get length() { return storage.size; },
      },
    },
    process: { env: {} }, URL, AbortController, DOMException, setTimeout, clearTimeout, fetch,
  });
  return resultModule.exports;
}

const params = { market: "kr", limit: 12 };
const snapshot = { status: "OK", dataHealth: { ohlcvLatestDate: "2026-10-26" } };
const fresh = { status: "OK", dataHealth: { ohlcvLatestDate: "2026-10-27" } };
const response = (body, status = 200) => ({
  ok: status === 200, status, statusText: "test response", text: async () => JSON.stringify(body),
});

test("ordinary reads can paint a recent snapshot without a request", async () => {
  let requests = 0;
  const api = runtime(async () => { requests++; return response(fresh); });
  api.writeApiSnapshot("/api/home/summary", params, snapshot);
  assert.equal((await api.mone.homeSummary(params)).dataHealth.ohlcvLatestDate, "2026-10-26");
  assert.equal(requests, 0);
});

test("explicit home refresh fetches new data even with a fresh cache", async () => {
  let requests = 0;
  const api = runtime(async () => { requests++; return response(fresh); });
  api.writeApiSnapshot("/api/home/summary", params, snapshot);
  const value = await api.mone.homeSummary(params, { forceRefresh: true });
  assert.equal(value.dataHealth.ohlcvLatestDate, "2026-10-27");
  assert.equal(requests, 1);
  assert.equal(api.readApiSnapshot("/api/home/summary", params).dataHealth.ohlcvLatestDate, "2026-10-27");
});

test("failed refresh marks fallback without overwriting the stored snapshot", async () => {
  const api = runtime(async () => response({ error: "backend unavailable" }, 500));
  api.writeApiSnapshot("/api/home/summary", params, snapshot);
  const value = await api.mone.homeSummary(params, { forceRefresh: true });
  assert.equal(value.snapshotFallback, true);
  assert.equal(value.dataHealth.ohlcvLatestDate, "2026-10-26");
  assert.equal(api.readApiSnapshot("/api/home/summary", params).snapshotFallback, undefined);
});

test("a simultaneous cached read cannot absorb a forced refresh", async () => {
  let requests = 0;
  const api = runtime(async () => { requests++; return response(fresh); });
  api.writeApiSnapshot("/api/home/summary", params, snapshot);
  const [cached, updated] = await Promise.all([
    api.mone.homeSummary(params), api.mone.homeSummary(params, { forceRefresh: true }),
  ]);
  assert.equal(cached.dataHealth.ohlcvLatestDate, "2026-10-26");
  assert.equal(updated.dataHealth.ohlcvLatestDate, "2026-10-27");
  assert.equal(requests, 1);
});
