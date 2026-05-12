// TODO-age strip — Observable Plot variant.
//
// Horizontal bars, age in days on X. Color encodes age cohort. Sorted with
// oldest at top. The bar's tail also carries the introducing-author so the
// reader can see which contributor's admissions are accumulating.

import * as Plot from "npm:@observablehq/plot";

const PALETTE = {
  ink: "#1a1a1a",
  inkDim: "#555",
  rule: "#d4d4d4",
  paper: "#fafaf7",
  accent: "#b35a1f",
  accentDim: "#dba37e",
};

export function todoStrip(todos /* , timeline */) {
  if (!todos || todos.length === 0) {
    const div = document.createElement("div");
    div.className = "aside";
    div.innerHTML =
      "<strong>No admissions.</strong> The surveyed files carry no TODO/FIXME annotations.";
    return div;
  }

  const rows = todos
    .slice()
    .sort((a, b) => b.age_days - a.age_days)
    .map((t) => ({
      ...t,
      label:
        `${t.kind} L${t.line_number}: ${t.text.length > 40 ? t.text.slice(0, 40) + "…" : t.text}`,
    }));

  const longest = rows[0].age_days;

  return Plot.plot({
    marginLeft: 280,
    marginRight: 90,
    marginTop: 8,
    marginBottom: 30,
    width: 720,
    height: Math.max(80, rows.length * 24 + 40),
    style: {
      background: PALETTE.paper,
      fontFamily: "-apple-system, sans-serif",
      fontSize: "11px",
      color: PALETTE.ink,
    },
    x: {
      label: "Days survived in tree →",
      labelAnchor: "right",
      labelOffset: 26,
      tickFormat: (d) => `${d}d`,
      grid: false,
      domain: [0, longest * 1.05],
    },
    y: {
      domain: rows.map((r) => r.label),
      label: null,
      axis: "left",
      tickSize: 0,
    },
    color: {
      type: "threshold",
      domain: [365, 1000],
      range: [PALETTE.accentDim, "#c97a4a", PALETTE.accent],
      legend: true,
      label: "TODO age",
    },
    marks: [
      Plot.barX(rows, {
        x: "age_days",
        y: "label",
        fill: "age_days",
        sort: { y: null },
        tip: true,
        channels: {
          text: "text",
          introducedBy: "introduced_by",
          sha: "introduced_short",
          line: "line_number",
        },
      }),
      Plot.text(rows, {
        x: "age_days",
        y: "label",
        text: (d) => `  ${d.age_days}d · ${d.introduced_by}`,
        textAnchor: "start",
        dx: 4,
        fill: PALETTE.inkDim,
      }),
    ],
  });
}
