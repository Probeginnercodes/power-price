/* Hosted transport must keep bearer tokens out of URLs and share one session handshake. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const calls = [];
const storage = new Map();
const originalFetch = async (url, options = {}) => {
  calls.push({ url, options });
  return {
    ok: true,
    status: 200,
    json: async () =>
      url.endsWith("/api/session") ? { token: "test-opaque-session" } : { job: { status: "idle" } },
  };
};
const context = {
  window: {
    FORECAST_CONFIG: { hosted: true, apiBase: "https://api.example.com" },
    fetch: originalFetch,
  },
  sessionStorage: {
    getItem: (key) => storage.get(key),
    setItem: (key, value) => storage.set(key, value),
    removeItem: (key) => storage.delete(key),
  },
  document: { addEventListener() {} },
  setTimeout() {},
  URL,
  console,
};
vm.createContext(context);
vm.runInContext(fs.readFileSync("frontend/api_client.js", "utf8"), context);
(async () => {
  await Promise.all([context.window.fetch("/api/status"), context.window.fetch("/api/status")]);
  assert.equal(calls.filter((call) => call.url.endsWith("/api/session")).length, 1);
  assert.equal(calls[1].url, "https://api.example.com/api/status");
  assert.equal(calls[1].options.headers.Authorization, "Bearer test-opaque-session");
  assert.ok(calls.every((call) => !call.url.includes("test-opaque-session")));
  assert.equal(storage.size, 1);
  console.log("5 hosted transport checks passed.");
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
