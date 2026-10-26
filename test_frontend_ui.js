const assert = require("node:assert/strict");
const ui = require("./frontend/ui_helpers.js");
let passed = 0;
function test(name, fn) {
  fn();
  passed++;
  console.log("PASS " + name);
}
test("undercoverage warns with percentage points", () => {
  const v = ui.coverageStatus(0.44);
  assert.equal(v.warning, true);
  assert.match(v.message, /36\.0 percentage points below/);
});
test("nominal coverage is not called proof", () => {
  const v = ui.coverageStatus(0.8);
  assert.equal(v.warning, false);
  assert.match(v.message, /not proof/);
});
test("overcoverage warns without implying significance", () => {
  const v = ui.coverageStatus(0.95);
  assert.equal(v.warning, true);
  assert.match(v.message, /above/);
});
test("missing coverage remains unavailable", () => {
  assert.equal(ui.coverageStatus(null).message, "Coverage unavailable");
  assert.equal(ui.percent(null), "—");
});
test("datasets with matching coverage group without losing IDs", () => {
  const g = ui.groupDatasets([
    { id: "a", hours: 168, start: "s", end: "e" },
    { id: "b", hours: 168, start: "s", end: "e" },
    { id: "c", hours: 9095, start: "x", end: "y" },
  ]);
  assert.equal(g.length, 2);
  assert.equal(g[0].hours, 9095);
  assert.deepEqual(g[1].ids, ["a", "b"]);
});
test("different date ranges do not merge", () => {
  assert.equal(
    ui.groupDatasets([
      { id: "a", hours: 168, start: "a", end: "b" },
      { id: "b", hours: 168, start: "c", end: "d" },
    ]).length,
    2,
  );
});
test("axis label explicitly denotes UTC", () => {
  assert.equal(ui.utcLabel("2026-10-15T00:00:00+02:00"), "10-14 22:00Z");
});
test("battery period states count and local dates", () => {
  assert.match(
    ui.periodLabel(["2026-10-16", "2026-10-15"]),
    /2 evaluated delivery days · 2026-10-15 to 2026-10-16 · Europe\/Berlin/,
  );
});
test("calibration gaps are percentage points", () => {
  assert.equal(ui.signedPoints(0.031 - 0.1), "-6.9 pp");
  assert.equal(ui.signedPoints(0.11 - 0.1), "+1.0 pp");
});
test("dataset and metric strings are escaped", () => {
  assert.equal(ui.escape("<script>"), "&lt;script&gt;");
});
console.log(`${passed} JavaScript regression checks passed.`);
