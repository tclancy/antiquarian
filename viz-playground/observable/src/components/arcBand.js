// Per-arc SC ranking band — Observable Plot variant.

import * as Plot from "npm:@observablehq/plot";
import { buildActiveScale } from "./timeAxis.js";

const PALETTE = {
  ink: "#1a1a1a",
  inkDim: "#555",
  rule: "#d4d4d4",
  paper: "#fafaf7",
  lossy: "#999",
};

const ARC_COLORS = [
  "#7c4a3a",
  "#3a5e7c",
  "#3a7c4a",
  "#7c6a3a",
  "#5e3a7c",
  "#7c3a5e",
  "#a08a5e",
  "#5e7c3a",
];

export function arcBandChart(arcBand, timeline) {
  if (!arcBand || arcBand.arc_count === 0) {
    const div = document.createElement("div");
    div.className = "aside";
    div.textContent = "No arcs found for this project.";
    return div;
  }

  const plotWidth = 720;
  const marginLeft = 260;
  const marginRight = 12;
  const chartW = plotWidth - marginLeft - marginRight;
  const axis = buildActiveScale(timeline, chartW);

  const filePaths = new Set(arcBand.arcs.map((a) => a.file_path));
  const multiFile = filePaths.size > 1;

  const bandRows = [];
  const tickRows = [];
  const labels = [];

  for (const arc of arcBand.arcs) {
    const basename = arc.file_path.split("/").pop();
    const prefix = multiFile ? `[${basename}] ` : "";
    const label = `${prefix}A${arc.arc_number}: ${truncate(arc.name, 40)}`;
    labels.push(label);

    const datable = arc.commits.filter((c) => c.timestamp);
    if (datable.length > 0) {
      const start = new Date(datable[0].timestamp);
      const end = new Date(datable[datable.length - 1].timestamp);
      bandRows.push({
        label,
        px1: axis.scale(start),
        px2: Math.max(axis.scale(end), axis.scale(start) + 4),
        commitCount: arc.commit_count,
        dateRange: arc.date_range || "",
        slug: arc.slug,
      });
    }
    for (const c of arc.commits) {
      if (!c.timestamp) continue;
      tickRows.push({
        label,
        px: axis.scale(new Date(c.timestamp)),
        sha: c.short_sha,
        subject: c.subject,
        slug: arc.slug,
      });
    }
  }

  const colorMap = new Map();
  labels.forEach((l, i) => colorMap.set(l, ARC_COLORS[i % ARC_COLORS.length]));

  const rowH = 30;
  const chartH = labels.length * rowH + 56;

  const chart = Plot.plot({
    marginLeft,
    marginRight,
    marginTop: 6,
    marginBottom: 8,
    width: plotWidth,
    height: chartH,
    style: {
      background: PALETTE.paper,
      fontFamily: "-apple-system, sans-serif",
      fontSize: "10px",
      color: PALETTE.ink,
    },
    x: { domain: [0, axis.pixelWidth], axis: null },
    y: { domain: labels, padding: 0.35, label: null },
    marks: [
      ...axis.gapBlocks.flatMap((g) => [
        Plot.rect([g], {
          x1: g.x,
          x2: g.x + g.width,
          y1: labels[0],
          y2: labels[labels.length - 1],
          fill: "#eee9df",
          stroke: PALETTE.rule,
          strokeDasharray: "2,2",
        }),
      ]),
      Plot.ruleY(labels, { stroke: PALETTE.rule, strokeOpacity: 0.4 }),
      Plot.barX(bandRows, {
        x1: "px1",
        x2: "px2",
        y: "label",
        fill: (d) => colorMap.get(d.label),
        fillOpacity: 0.22,
        tip: true,
        channels: {
          range: "dateRange",
          decisive: "commitCount",
        },
      }),
      Plot.tickX(tickRows, {
        x: "px",
        y: "label",
        stroke: (d) => colorMap.get(d.label),
        strokeWidth: 2.5,
        tip: true,
        channels: {
          sha: "sha",
          subject: "subject",
        },
      }),
    ],
  });

  const axisSvg = renderWindowAxis(axis, plotWidth, marginLeft);
  const wrap = document.createElement("div");
  wrap.appendChild(chart);
  wrap.appendChild(axisSvg);
  return wrap;
}

function renderWindowAxis(axis, plotW, marginLeft) {
  const svgNS = "http://www.w3.org/2000/svg";
  const h = 28;
  const svg = document.createElementNS(svgNS, "svg");
  svg.setAttribute("viewBox", `0 0 ${plotW} ${h}`);
  svg.setAttribute("width", "100%");
  svg.setAttribute("style", "max-width: 100%; height: auto; display:block;");

  const g = document.createElementNS(svgNS, "g");
  g.setAttribute("transform", `translate(${marginLeft}, 0)`);
  svg.appendChild(g);

  for (let i = 0; i < axis.windows.length; i++) {
    const w = axis.windows[i];
    const x0 = axis.winStartsPx[i];
    const wpx = axis.allocations[i];
    const ln = document.createElementNS(svgNS, "line");
    ln.setAttribute("x1", x0);
    ln.setAttribute("x2", x0 + wpx);
    ln.setAttribute("y1", 2);
    ln.setAttribute("y2", 2);
    ln.setAttribute("stroke", "#999");
    g.appendChild(ln);
    const lab = document.createElementNS(svgNS, "text");
    lab.setAttribute("x", x0 + wpx / 2);
    lab.setAttribute("y", 16);
    lab.setAttribute("text-anchor", "middle");
    lab.setAttribute("font-size", "10");
    lab.setAttribute("fill", "#555");
    lab.textContent = formatWindow(w);
    g.appendChild(lab);
  }
  for (const gap of axis.gapBlocks) {
    const lab = document.createElementNS(svgNS, "text");
    lab.setAttribute("x", gap.x + gap.width / 2);
    lab.setAttribute("y", 16);
    lab.setAttribute("text-anchor", "middle");
    lab.setAttribute("font-size", "9");
    lab.setAttribute("fill", "#999");
    lab.setAttribute("font-style", "italic");
    lab.textContent = gap.label;
    g.appendChild(lab);
  }
  return svg;
}

function formatWindow(w) {
  const sY = w.start.getUTCFullYear();
  const eY = w.end.getUTCFullYear();
  const sM = w.start.toLocaleString("en-US", { month: "short", timeZone: "UTC" });
  const eM = w.end.toLocaleString("en-US", { month: "short", timeZone: "UTC" });
  if (sY === eY && sM === eM) return `${sM} ${sY}`;
  if (sY === eY) return `${sM}–${eM} ${sY}`;
  return `${sM} ${sY} – ${eM} ${eY}`;
}

function truncate(s, n) {
  return s.length > n ? s.slice(0, n - 1) + "…" : s;
}
