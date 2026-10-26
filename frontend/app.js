// API responses contain saved research artefacts; presentation never retrains models.
const getElement = (id) => document.getElementById(id);
const {
  escape,
  number,
  percent,
  coverageStatus,
  groupDatasets,
  utcLabel,
  periodLabel,
  signedPoints,
} = ForecastUI;
let result = null,
  current = "",
  loaded = "",
  lastRunListSignature = "",
  previousJobRunning = false,
  preparedDatasets = [];
const names = {
  lear: "LEAR",
  lightgbm: "LightGBM",
  naive: "Yesterday naive",
  perfect_foresight: "Perfect foresight",
};
/** Escape every cell, including formatted values from saved CSV artefacts. */
function table(rows, cols) {
  return (
    "<table><thead><tr>" +
    cols.map((c) => '<th scope="col">' + escape(c[0]) + "</th>").join("") +
    "</tr></thead><tbody>" +
    rows
      .map(
        (r) =>
          "<tr>" +
          cols.map((c) => "<td>" + escape(c[2] ? c[2](r[c[1]]) : r[c[1]]) + "</td>").join("") +
          "</tr>",
      )
      .join("") +
    "</tbody></table>"
  );
}
/** Draw UTC timestamps; callers provide the units and physical bounds explicitly. */
function chart(target, rows, series, band = null, options = {}) {
  const box = getElement(target);
  if (!rows.length) {
    box.className = "chart empty";
    box.textContent = "No observations for this selection.";
    return;
  }
  box.classList.remove("empty");
  const width = 1000,
    height = options.height || 290,
    pad = { l: 65, r: 25, t: 30, b: 43 };
  const timestamps = rows.map((r) => new Date(r.delivery_start_utc).getTime());
  const first = timestamps[0],
    last = timestamps.at(-1);
  const values = rows.flatMap((r) => series.map((s) => Number(r[s.key]))).filter(Number.isFinite);
  if (band) rows.forEach((r) => values.push(Number(r[band[0]]), Number(r[band[1]])));
  let lo, hi;
  if (options.domain) {
    [lo, hi] = options.domain;
  } else {
    lo = Math.min(...values);
    hi = Math.max(...values);
    if (lo === hi) {
      lo -= 1;
      hi += 1;
    }
    const margin = (hi - lo) * 0.1;
    lo -= margin;
    hi += margin;
  }
  const x = (i) =>
      pad.l + ((timestamps[i] - first) / Math.max(1, last - first)) * (width - pad.l - pad.r),
    y = (v) => height - pad.b - ((v - lo) / (hi - lo)) * (height - pad.t - pad.b);
  const unit = options.label || "Price (EUR/MWh) · time UTC";
  let svg = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${escape(unit)}"><title>${escape(unit)}</title><text x="${pad.l}" y="14">${escape(unit)}</text>`;
  // Raised plot floor and line shadows provide depth without changing coordinates.
  // Each chart owns its filter IDs, avoiding collisions between inline SVGs.
  svg += `<defs><filter id="${target}-depth" x="-20%" y="-30%" width="140%" height="170%"><feDropShadow dx="0" dy="3" stdDeviation="2" flood-color="#003366" flood-opacity=".22"/></filter><linearGradient id="${target}-floor" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#cce0ff"/><stop offset="1" stop-color="#f2f7ff"/></linearGradient></defs>`;
  const floorY = height - pad.b;
  svg += `<path d="M ${pad.l} ${floorY} H ${width - pad.r - 10} l 10 9 H ${pad.l + 10} Z" fill="url(#${target}-floor)" stroke="#cce0ff"/><rect x="${pad.l}" y="${pad.t}" width="${width - pad.l - pad.r}" height="${floorY - pad.t}" fill="#fff" fill-opacity=".55" stroke="#dae8fa"/>`;
  for (let i = 0; i < 5; i++) {
    const value = lo + ((hi - lo) * i) / 4;
    svg += `<line x1="${pad.l}" y1="${y(value)}" x2="${width - pad.r}" y2="${y(value)}" stroke="${Math.abs(value) < 1e-8 ? "#66a3ff" : "#dae8fa"}"/><text x="${pad.l - 10}" y="${y(value) + 3}" text-anchor="end">${number(value, options.decimals ?? 0)}</text>`;
  }
  if (band) {
    const points = rows
      .map((r, i) => `${x(i)},${y(Number(r[band[1]]))}`)
      .concat(rows.map((r, i) => `${x(i)},${y(Number(r[band[0]]))}`).reverse())
      .join(" ");
    svg += `<polygon points="${points}" fill="#cce0ff" opacity=".8"/>`;
  }
  for (const s of series) {
    let path = `M ${x(0)} ${y(Number(rows[0][s.key]))}`;
    for (let i = 1; i < rows.length; i++)
      path += s.step
        ? ` H ${x(i)} V ${y(Number(rows[i][s.key]))}`
        : ` L ${x(i)} ${y(Number(rows[i][s.key]))}`;
    svg += `<path d="${path}" fill="none" stroke="${s.color}" stroke-width="${s.width || 2}" filter="url(#${target}-depth)" ${s.dash ? 'stroke-dasharray="5 4"' : ""}/>`;
    rows.forEach((r, i) => {
      svg += `<circle cx="${x(i)}" cy="${y(Number(r[s.key]))}" r="4" fill="transparent"><title>${escape(s.name || s.key)} · ${escape(utcLabel(r.delivery_start_utc))}: ${number(r[s.key])}</title></circle>`;
    });
  }
  const count = Math.min(5, rows.length);
  for (let i = 0; i < count; i++) {
    const idx = Math.round((i / Math.max(1, count - 1)) * (rows.length - 1));
    svg += `<text x="${x(idx)}" y="${height - 12}" text-anchor="${i === 0 ? "start" : i === count - 1 ? "end" : "middle"}">${escape(utcLabel(rows[idx].delivery_start_utc))}</text>`;
  }
  box.innerHTML = svg + "</svg>";
}
/** Keep power (MW) and boundary energy (MWh) on separate axes. */
function renderCharts() {
  if (!result) return;
  const day = getElement("day").value;
  let rows = result.forecasts;
  if (day !== "all") rows = rows.filter((r) => r.delivery_date_local === day);
  chart(
    "pricechart",
    rows,
    [
      { key: "actual", name: "Actual", color: "#003366", width: 2.5 },
      { key: "lightgbm", name: "LightGBM median", color: "#007acc" },
      { key: "lear", name: "LEAR", color: "#00509e", dash: true },
    ],
    ["lightgbm_q10", "lightgbm_q90"],
  );
  const dispatchDay = day === "all" ? result.report.forecast_days[0] : day;
  const schedules = result.battery_dispatch
    .filter(
      (r) => r.delivery_date_local === dispatchDay && r.model === getElement("dispatchmodel").value,
    )
    .map((r) => ({
      ...r,
      negative_discharge: -Number(r.discharge_mw),
      energy_mwh: Number(r.energy_start_mwh),
    }));
  if (schedules.length) {
    const last = schedules.at(-1);
    schedules.push({
      ...last,
      delivery_start_utc: new Date(
        new Date(last.delivery_start_utc).getTime() + Number(last.duration_hours) * 3600000,
      ).toISOString(),
      charge_mw: 0,
      negative_discharge: 0,
      energy_mwh: Number(last.energy_end_mwh),
    });
  }
  const battery = result.report.config.battery;
  getElement("dispatch-day-label").textContent =
    `Delivery day ${dispatchDay} (Europe/Berlin) · ${names[getElement("dispatchmodel").value]} · chart timestamps are UTC`;
  chart(
    "dispatchchart",
    schedules,
    [
      {
        key: "charge_mw",
        name: "Charging power (MW)",
        color: "#007acc",
        step: true,
      },
      {
        key: "negative_discharge",
        name: "Discharging power (MW)",
        color: "#00509e",
        step: true,
      },
    ],
    null,
    {
      domain: [-Number(battery.power_mw), Number(battery.power_mw)],
      label: "Power (MW) · charging + / discharging − · time UTC",
      height: 230,
      decimals: 1,
    },
  );
  chart(
    "energychart",
    schedules,
    [{ key: "energy_mwh", name: "Stored energy (MWh)", color: "#003366" }],
    null,
    {
      domain: [0, Number(battery.capacity_mwh)],
      label: "Stored energy (MWh) · hourly boundary states · time UTC",
      height: 230,
      decimals: 1,
    },
  );
}
function renderDatasets() {
  const groups = groupDatasets(preparedDatasets);
  const selected = result?.report.source_file?.split(/[\\/]/).slice(-2, -1)[0];
  getElement("datasets").innerHTML = groups.length
    ? groups
        .map(
          (d) =>
            `<div class="data-row"><div class="data-title">${number(d.hours, 0)} hourly observations ${d.ids.includes(selected) ? '<span class="data-badge">Selected run source</span>' : ""}</div><small>${escape(d.start)} → ${escape(d.end)} (exclusive)</small><details class="dataset-details"><summary>${d.ids.length} prepared run${d.ids.length === 1 ? "" : "s"} with matching coverage</summary><ul>${d.ids.map((id) => `<li>${escape(id)}</li>`).join("")}</ul></details></div>`,
        )
        .join("")
    : '<p class="muted">No prepared market datasets. Synthetic demo is available.</p>';
}
/** Load a saved experiment; keep exploratory warnings tied to its own report. */
async function loadRun(id) {
  if (!id) return;
  try {
    const response = await fetch("/api/result/" + encodeURIComponent(id));
    const data = await response.json();
    if (!response.ok) throw Error(data.error);
    result = data;
    current = id;
    loaded = id;
    const r = data.report,
      metric = r.metrics.find((x) => x.model === "lightgbm"),
      value = r.battery_summary.find((x) => x.model === "lightgbm");
    getElement("pinball").textContent = number(metric.mean_pinball);
    getElement("coverage").textContent = percent(metric.coverage_80);
    getElement("capture").textContent = percent(value.capture_fraction);
    getElement("mae").textContent = number(metric.mae);
    const coverage = coverageStatus(metric.coverage_80);
    getElement("coverage-card").classList.toggle("coverage-warning", coverage.warning);
    getElement("coverage-status").textContent = coverage.message;
    getElement("notice").textContent =
      r.data_label +
      " · " +
      (r.mode === "demo"
        ? "Use this run to test implementation and interface, not to claim market skill."
        : "Input forecast publication/vintage availability remains unverified.");
    getElement("notice").className = "notice" + (r.mode === "empirical" ? " warning" : "");
    getElement("sample").textContent =
      r.forecast_hours + " forecast hours · " + r.forecast_days.length + " evaluated local days";
    getElement("metrics").innerHTML = table(r.metrics, [
      ["MODEL", "model", (x) => names[x]],
      ["MAE", "mae", number],
      ["RMSE", "rmse", number],
      ["PINBALL", "mean_pinball", number],
      ["COVERAGE", "coverage_80", percent],
    ]);
    // Display archived sensitivity, including optional supplements for older runs.
    const sensitivityRows = data.sensitivity || r.sensitivity || [];
    getElement("sensitivity-table").innerHTML = sensitivityRows.length
      ? table(sensitivityRows, [
          ["SCENARIO", "scenario"],
          ["POLICY", "model", (value) => names[value] || value],
          ["NET EUR", "net_eur", number],
          ["CAPTURE", "capture_fraction", percent],
          ["EFFICIENCY", "round_trip_efficiency", percent],
          ["CAPACITY MWh", "capacity_mwh", number],
          ["THROUGHPUT EUR/MWh", "throughput_cost_eur_mwh", number],
          ["IMPORT EUR/MWh", "import_fee_eur_mwh", number],
        ])
      : "No sensitivity artefact in this older run. Run sensitivity.py --run-id " +
        escape(id) +
        " to create an immutable supplement.";
    getElement("research-status").textContent =
      r.mode === "demo"
        ? "Synthetic demonstration: software checks only. No empirical skill or research-readiness claim."
        : "Exploratory historical research: original forecast vintages unverified; evaluated dates already inspected; no final significance claim. Trial history is inventoried, with pre-archive attempts unknown.";
    const dm = r.dm_test;
    getElement("dm").textContent =
      `DM diagnostic: statistic ${number(dm.statistic)}, raw unadjusted p-value ${number(dm.p_value, 3)} across ${dm.days} daily losses. ${dm.inference_eligible ? "Sample-size threshold reached; research inference still requires verified vintages, complete trial accounting and an untouched holdout." : "Insufficient sample for persuasive inference."} Archived Holm adjustments are diagnostic and available in the trial ledger.`;
    getElement("calibration").innerHTML =
      '<h3>Quantile calibration</h3><p class="muted">The observed fraction below each forecast should approach its quantile level. Gaps are descriptive, not significance tests.</p>' +
      table(
        r.calibration.map((v) => ({
          ...v,
          gap: v.empirical_fraction_below - v.quantile,
        })),
        [
          ["MODEL", "model", (x) => names[x]],
          ["QUANTILE", "quantile", percent],
          ["FRACTION BELOW", "empirical_fraction_below", percent],
          ["GAP", "gap", signedPoints],
        ],
      );
    const battery = [...r.battery_summary].sort((a, b) =>
      a.model === "perfect_foresight"
        ? -1
        : b.model === "perfect_foresight"
          ? 1
          : b.net_eur - a.net_eur,
    );
    const max = Math.max(1, ...battery.map((v) => Math.abs(v.net_eur)));
    getElement("battery-period").textContent =
      "Total net energy-arbitrage value (€) across " + periodLabel(r.forecast_days);
    getElement("capture-period").textContent =
      `Share of perfect-foresight total over ${r.forecast_days.length} evaluated delivery days`;
    getElement("bars").classList.remove("empty");
    getElement("bars").innerHTML = battery
      .map(
        (v) =>
          `<div class="bar-row"><span>${escape(names[v.model])}</span><div class="track"><div class="fill" style="width:${(Math.abs(v.net_eur) / max) * 100}%;${v.net_eur < 0 ? "background:#c47a53" : ""}"></div></div><span>€${number(v.net_eur, 0)}</span></div>`,
      )
      .join("");
    getElement("batterytable").innerHTML = table(battery, [
      ["POLICY", "model", (x) => names[x]],
      ["TOTAL NET €", "net_eur", number],
      ["CAPTURE", "capture_fraction", percent],
    ]);
    const b = r.config.battery;
    getElement("battery-settings").textContent =
      `${number(b.power_mw, 1)} MW / ${number(b.capacity_mwh, 1)} MWh · ${percent(b.round_trip_efficiency)} round-trip efficiency · daily empty start/end. Throughput cost €${number(b.throughput_cost_eur_mwh)} per MWh charged plus discharged; import fee €${number(b.import_fee_eur_mwh ?? 0)}/MWh.`;
    getElement("assumptions").innerHTML = r.assumptions
      .map((s) => "<li>" + escape(s) + "</li>")
      .join("");
    getElement("day").innerHTML =
      '<option value="all">All delivery days</option>' +
      r.forecast_days
        .map((d) => `<option value="${escape(d)}">${escape(d)} · Berlin</option>`)
        .join("");
    getElement("downloads").innerHTML = [
      "forecasts.csv",
      "metrics.csv",
      "battery_values.csv",
      "battery_dispatch.csv",
      "results.json",
      ...(sensitivityRows.length ? ["sensitivity.csv"] : []),
    ]
      .map(
        (file) =>
          `<a download="${file}" href="/api/download?run=${encodeURIComponent(id)}&file=${encodeURIComponent(file)}">↓ ${escape(file)}</a>`,
      )
      .join("");
    renderCharts();
    renderDatasets();
    updateNavigation();
  } catch (error) {
    getElement("notice").textContent = error.message;
    getElement("notice").className = "notice warning";
  }
}
/** Poll job state and reload results only when the completed-run list changes. */
async function refresh() {
  try {
    const response = await fetch("/api/status");
    if (!response.ok) throw Error("Server unavailable");
    const data = await response.json();
    if (previousJobRunning && !data.job.running && data.job.status === "success") {
      current = "";
      loaded = "";
      lastRunListSignature = "";
    }
    previousJobRunning = data.job.running;
    getElement("run").disabled = data.job.running;
    getElement("job").textContent = data.job.running
      ? "Experiment running · daily refits and battery optimisation"
      : "Job status: " + data.job.status;
    getElement("log").textContent = data.log || "No active job.";
    if (data.research) {
      const inventory = data.research;
      getElement("trial-accounting").textContent =
        `${inventory.archived_executions} archived executions · ${inventory.failed_executions} recorded failures · ${inventory.distinct_archived_model_configurations} saved model configurations · ${inventory.distinct_empirical_test_signatures_with_p_values} empirical test signatures with p-values. Lifetime human trial count unknown. Holm adjustment is diagnostic only; no final inference permitted.`;
    }
    preparedDatasets = data.datasets;
    renderDatasets();
    const finished = data.runs.filter((r) => r.status === "success");
    const signature = finished.map((r) => r.id).join("|");
    if (signature !== lastRunListSignature) {
      lastRunListSignature = signature;
      getElement("runs").innerHTML = finished.length
        ? finished
            .map(
              (r) =>
                `<option value="${escape(r.id)}">${r.mode === "demo" ? "DEMO" : "EXPLORATORY"} · ${escape(r.id)}</option>`,
            )
            .join("")
        : '<option value="">No completed experiment yet</option>';
      if (finished.length) {
        const selected = finished.find((r) => r.id === current) ? current : finished[0].id;
        getElement("runs").value = selected;
        if (selected !== loaded) await loadRun(selected);
      }
    }
  } catch (error) {
    getElement("job").textContent = window.FORECAST_CONFIG?.hosted
      ? "Backend temporarily unavailable. Retry shortly."
      : "Cannot reach local server. Start python serve.py.";
  }
}
function activateNavigation(id) {
  document.querySelectorAll("aside .nav").forEach((link) => {
    const active = link.getAttribute("href") === "#" + id;
    link.classList.toggle("active", active);
    if (active) link.setAttribute("aria-current", "location");
    else link.removeAttribute("aria-current");
  });
}
function updateNavigation() {
  const ids = ["overview", "forecast", "battery", "evidence"];
  let active = "overview";
  for (const id of ids) {
    const section = getElement(id);
    if (section && section.getBoundingClientRect().top <= 170) active = id;
  }
  if (window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 8)
    active = "evidence";
  activateNavigation(active);
}
let navQueued = false;
window.addEventListener(
  "scroll",
  () => {
    if (!navQueued) {
      navQueued = true;
      requestAnimationFrame(() => {
        updateNavigation();
        navQueued = false;
      });
    }
  },
  { passive: true },
);
window.addEventListener("hashchange", () => {
  const id = location.hash.slice(1);
  if (["overview", "forecast", "battery", "evidence"].includes(id)) activateNavigation(id);
});
window.addEventListener("load", updateNavigation);
document
  .querySelectorAll("aside .nav")
  .forEach((link) =>
    link.addEventListener("click", () => activateNavigation(link.getAttribute("href").slice(1))),
  );
getElement("mode").onchange = () => {
  getElement("ackrow").hidden = getElement("mode").value !== "empirical";
};
getElement("run").onclick = async () => {
  try {
    getElement("run").disabled = true;
    const response = await fetch("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        mode: getElement("mode").value,
        days: Number(getElement("days").value),
        training_days: Number(getElement("training").value),
        acknowledge: getElement("ack").checked,
      }),
    });
    const data = await response.json();
    if (!response.ok) throw Error(data.error);
    await refresh();
  } catch (error) {
    getElement("job").textContent = error.message;
    getElement("run").disabled = false;
  }
};
getElement("runs").onchange = () => loadRun(getElement("runs").value);
getElement("day").onchange = renderCharts;
getElement("dispatchmodel").onchange = renderCharts;
refresh();
setInterval(refresh, 4000);
