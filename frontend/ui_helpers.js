/* Pure presentation helpers shared by browser code and Node regression checks. */
(function (root) {
  const escape = (s) =>
    String(s ?? "").replace(
      /[&<>"']/g,
      (c) =>
        ({
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;",
        })[c],
    );
  const number = (v, n = 2) =>
    v === null || v === undefined || v === "" || !Number.isFinite(Number(v))
      ? "—"
      : Number(v).toLocaleString("en-GB", {
          maximumFractionDigits: n,
          minimumFractionDigits: n,
        });
  const percent = (v) =>
    v === null || v === undefined || v === "" ? "—" : number(Number(v) * 100, 1) + "%";
  function coverageStatus(value) {
    if (value === null || value === undefined || !Number.isFinite(Number(value)))
      return { warning: false, message: "Coverage unavailable" };
    const delta = Number(value) - 0.8;
    if (Math.abs(delta) > 0.05 + 1e-10)
      return {
        warning: true,
        message: `${number(Math.abs(delta) * 100, 1)} percentage points ${delta < 0 ? "below" : "above"} the 80% target`,
      };
    return {
      warning: false,
      message: "Within 5 percentage points of nominal · not proof of calibration",
    };
  }
  function groupDatasets(datasets) {
    const groups = new Map();
    for (const d of datasets) {
      const key = JSON.stringify([d.hours, d.start, d.end]);
      if (!groups.has(key))
        groups.set(key, {
          hours: d.hours,
          start: d.start,
          end: d.end,
          ids: [],
        });
      groups.get(key).ids.push(d.id);
    }
    return [...groups.values()].sort((a, b) => Number(b.hours) - Number(a.hours));
  }
  function utcLabel(value) {
    return new Date(value).toISOString().slice(5, 16).replace("T", " ") + "Z";
  }
  function periodLabel(days) {
    const sorted = [...days].sort();
    return `${days.length} evaluated delivery day${days.length === 1 ? "" : "s"} · ${sorted[0]}${sorted.length > 1 ? " to " + sorted.at(-1) : ""} · Europe/Berlin`;
  }
  function signedPoints(value) {
    return `${value > 0 ? "+" : ""}${number(value * 100, 1)} pp`;
  }
  const helpers = {
    escape,
    number,
    percent,
    coverageStatus,
    groupDatasets,
    utcLabel,
    periodLabel,
    signedPoints,
  };
  if (typeof module !== "undefined" && module.exports) module.exports = helpers;
  else root.ForecastUI = helpers;
})(typeof window !== "undefined" ? window : globalThis);
