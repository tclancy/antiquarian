// Author swimlane — Observable Plot variant.
//
// Uses a piecewise pixel-space scale (buildActiveScale) so the active windows
// fill the plot but the dormancy gaps are still visible as labeled segments
// between windows. Plot itself doesn't support piecewise scales natively,
// so we pre-project the X values to pixel space and tell Plot to use a
// linear x scale over that.

import * as Plot from "npm:@observablehq/plot";
import { buildActiveScale } from "./timeAxis.js";

const PALETTE = {
  ink: "#1a1a1a",
  inkDim: "#555",
  rule: "#d4d4d4",
  paper: "#fafaf7",
  accent: "#b35a1f",
  lane: "#3a5e7c",
  lossy: "#999",
};

export function swimlaneChart(swimlane, timeline) {
  if (!swimlane || swimlane.lane_count === 0) {
    const div = document.createElement("div");
    div.className = "aside";
    div.textContent = "No commits in cache.";
    return div;
  }

  const plotWidth = 720;
  const marginLeft = 150;
  const marginRight = 12;
  const chartW = plotWidth - marginLeft - marginRight;

  const axis = buildActiveScale(timeline, chartW);

  const rows = [];
  let maxDiff = 1;
  for (const lane of swimlane.lanes) {
    for (const c of lane.commits) {
      const diff = c.additions + c.deletions;
      if (diff > maxDiff) maxDiff = diff;
      rows.push({
        author: lane.author,
        date: new Date(c.timestamp),
        px: axis.scale(new Date(c.timestamp)),
        diff,
        subject: c.subject,
        sha: c.short_sha,
        decisive: c.arcs && c.arcs.length > 0,
        arcs: (c.arcs || []).join(", ") || "—",
      });
    }
  }

  const laneOrder = swimlane.lanes.map((l) => l.author);
  const stripeHeight = 56;
  const chartH = laneOrder.length * stripeHeight + 56;

  const chart = Plot.plot({
    marginLeft,
    marginRight,
    marginTop: 8,
    marginBottom: 8,
    width: plotWidth,
    height: chartH,
    style: {
      background: PALETTE.paper,
      fontFamily: "-apple-system, sans-serif",
      fontSize: "11px",
      color: PALETTE.ink,
    },
    x: {
      domain: [0, axis.pixelWidth],
      axis: null,
      grid: false,
    },
    y: {
      domain: laneOrder,
      label: null,
      padding: 0.4,
    },
    r: {
      range: [3, 14],
      domain: [0, maxDiff],
      label: "Diff size (LoC)",
    },
    color: {
      domain: [true, false],
      range: [PALETTE.accent, PALETTE.lane],
      legend: true,
      label: "Mark color",
      tickFormat: (d) => (d ? "decisive commit" : "supporting commit"),
    },
    marks: [
      ...axis.gapBlocks.flatMap((g) => [
        Plot.rect([g], {
          x1: g.x,
          x2: g.x + g.width,
          y1: laneOrder[0],
          y2: laneOrder[laneOrder.length - 1],
          fill: "#eee9df",
          stroke: PALETTE.rule,
          strokeDasharray: "2,2",
        }),
        Plot.text([g], {
          x: g.x + g.width / 2,
          y: laneOrder[0],
          text: () => g.label,
          textAnchor: "middle",
          dy: -6,
          fontSize: 9,
          fill: PALETTE.lossy,
          fontStyle: "italic",
        }),
      ]),
      Plot.ruleY(laneOrder, { stroke: PALETTE.rule, strokeOpacity: 0.5 }),
      Plot.dot(rows, {
        x: "px",
        y: "author",
        r: "diff",
        fill: (d) => (d.decisive ? true : false),
        stroke: (d) => (d.decisive ? PALETTE.ink : null),
        strokeWidth: 0.8,
        opacity: 0.85,
        tip: true,
        channels: {
          sha: "sha",
          subject: "subject",
          arcs: "arcs",
          date: (d) => d.date.toISOString().slice(0, 10),
        },
      }),
    ],
  });

  const axisSvg = renderWindowAxis(axis, plotWidth, marginLeft);
  const sizeLegend = renderSizeLegend(maxDiff);

  const wrap = document.createElement("div");
  wrap.appendChild(sizeLegend);
  wrap.appendChild(chart);
  wrap.appendChild(axisSvg);
  return wrap;
}

function renderSizeLegend(maxDiff) {
  // Plot's r-legend doesn't always render when the same scale also feeds a
  // manual color encoding. We hand-roll a "Diff size (LoC)" legend per Tom's
  // PR #11 review feedback.
  const div = document.createElement("div");
  div.style.cssText =
    "display: flex; align-items: center; gap: 14px; font-family: -apple-system, sans-serif; font-size: 10px; color: #555; margin: 4px 0 6px; padding-left: 150px;";
  div.innerHTML = `
    <strong style="color:#1a1a1a; text-transform: uppercase; letter-spacing: 0.06em; font-size: 9px;">Diff size (LoC):</strong>
    <span style="display:inline-flex; align-items:center; gap:4px;">
      <svg width="14" height="14"><circle cx="7" cy="7" r="3" fill="#3a5e7c" opacity="0.6"/></svg>
      ${Math.round(maxDiff * 0.05)}
    </span>
    <span style="display:inline-flex; align-items:center; gap:4px;">
      <svg width="20" height="20"><circle cx="10" cy="10" r="7" fill="#3a5e7c" opacity="0.6"/></svg>
      ${Math.round(maxDiff * 0.25)}
    </span>
    <span style="display:inline-flex; align-items:center; gap:4px;">
      <svg width="30" height="30"><circle cx="15" cy="15" r="13" fill="#3a5e7c" opacity="0.6"/></svg>
      ${maxDiff}
    </span>
  `;
  return div;
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
