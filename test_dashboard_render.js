/* Execute dashboard presentation against a tiny mocked API and DOM, without a browser. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const ui = require("./frontend/ui_helpers.js");
const html = fs.readFileSync("frontend/index.html", "utf8");
const elements = new Map();
for (const [, id] of html.matchAll(/\bid="([^"]+)"/g)) {
  elements.set(id, {
    value: "",
    innerHTML: "",
    textContent: "",
    hidden: false,
    classList: { toggle() {}, remove() {} },
    getBoundingClientRect: () => ({ top: 300 }),
  });
}
elements.get("day").value = "all";
elements.get("dispatchmodel").value = "lightgbm";
const forecastDay = "2026-10-15";
const battery = {
  power_mw: 1,
  capacity_mwh: 4,
  round_trip_efficiency: 0.9,
  throughput_cost_eur_mwh: 2,
  import_fee_eur_mwh: 0,
};
const predictions = [0, 1, 2].map((hour) => ({
  delivery_start_utc: `${forecastDay}T0${hour}:00:00Z`,
  delivery_date_local: forecastDay,
  actual: 100 + hour,
  lear: 99,
  lightgbm: 98,
  lightgbm_q10: 80,
  lightgbm_q90: 120,
}));
const metrics = [{ model: "lightgbm", mae: 2, rmse: 2, mean_pinball: 1, coverage_80: 0.8 }];
const report = {
  mode: "empirical",
  data_label: "EXPLORATORY",
  forecast_hours: 3,
  forecast_days: [forecastDay],
  config: { battery },
  metrics,
  calibration: [],
  dm_test: { statistic: 1, p_value: 0.3, days: 1, inference_eligible: false },
  battery_summary: [
    { model: "perfect_foresight", net_eur: 100, capture_fraction: 1 },
    { model: "lightgbm", net_eur: 80, capture_fraction: 0.8 },
  ],
  assumptions: [],
};
const sensitivity = [
  { scenario: "baseline", model: "lightgbm", net_eur: 80, capture_fraction: 0.8, ...battery },
];
const payload = {
  report,
  forecasts: predictions,
  sensitivity,
  battery_dispatch: predictions.map((row) => ({
    ...row,
    model: "lightgbm",
    charge_mw: 1,
    discharge_mw: 0,
    energy_start_mwh: 0,
    energy_end_mwh: 1,
    duration_hours: 1,
  })),
};
const context = {
  ForecastUI: ui,
  console,
  Date,
  Number,
  Map,
  Math,
  document: {
    getElementById: (id) => {
      assert.ok(elements.has(id), `Missing HTML element: ${id}`);
      return elements.get(id);
    },
    querySelectorAll: () => [],
    documentElement: { scrollHeight: 1000 },
  },
  window: { addEventListener() {}, innerHeight: 500, scrollY: 0 },
  location: { hash: "" },
  requestAnimationFrame() {},
  setInterval() {},
  fetch: async (url) => ({
    ok: true,
    json: async () =>
      url === "/api/status"
        ? {
            job: { running: false, status: "success" },
            runs: [{ id: "example", mode: "empirical", status: "success" }],
            datasets: [],
          }
        : payload,
  }),
};
vm.createContext(context);
vm.runInContext(fs.readFileSync("frontend/app.js", "utf8"), context);
setImmediate(() => {
  assert.match(elements.get("pricechart").innerHTML, /feDropShadow/);
  assert.match(elements.get("pricechart").innerHTML, /pricechart-floor/);
  assert.match(elements.get("sensitivity-table").innerHTML, /baseline/);
  assert.match(elements.get("research-status").textContent, /unverified/);
  assert.match(elements.get("downloads").innerHTML, /sensitivity.csv/);
  assert.match(elements.get("energychart").innerHTML, /Stored energy/);
  assert.match(elements.get("coverage").textContent, /80.0%/);
  console.log("7 dashboard rendering contract checks passed.");
});
