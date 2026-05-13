// The dual-axis reference strip.
//
// `variant: "header"` — full-width strip rendered once at the top of the
// essay. Shows project lifespan with active windows highlighted, gap
// durations labeled.
//
// `variant: "atom"` — narrow strip rendered above each chart figure.

const PALETTE = {
  ink: "#1a1a1a",
  inkDim: "#555",
  rule: "#d4d4d4",
  paper: "#fafaf7",
  accent: "#b35a1f",
  accentDim: "#dba37e",
  lossy: "#999",
};

export function timelineStrip(timeline, opts = {}) {
  const variant = opts.variant || "header";
  if (!timeline || !timeline.full_span) {
    const div = document.createElement("div");
    div.textContent = "(no timeline data)";
    return div;
  }
  const width = opts.width || 720;
  const stripH = variant === "header" ? 38 : 22;
  const labelGap = variant === "header" ? 16 : 0;
  const totalH = stripH + labelGap;

  const fullStart = new Date(timeline.full_span.start);
  const fullEnd = new Date(timeline.full_span.end);
  const fullDur = fullEnd - fullStart;
  const sx = (d) => ((d - fullStart) / fullDur) * width;

  const svgNS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(svgNS, "svg");
  svg.setAttribute("viewBox", `0 0 ${width} ${totalH}`);
  svg.setAttribute("width", "100%");
  svg.setAttribute("style", "max-width: 100%; height: auto; display:block;");

  const bg = document.createElementNS(svgNS, "rect");
  bg.setAttribute("x", 0);
  bg.setAttribute("y", labelGap);
  bg.setAttribute("width", width);
  bg.setAttribute("height", stripH);
  bg.setAttribute("fill", "#eee9df");
  bg.setAttribute("rx", 2);
  svg.appendChild(bg);

  const defs = document.createElementNS(svgNS, "defs");
  defs.innerHTML = `
    <pattern id="hatch-strip" patternUnits="userSpaceOnUse" width="6" height="6" patternTransform="rotate(45)">
      <line x1="0" y1="0" x2="0" y2="6" stroke="${PALETTE.lossy}" stroke-width="1" opacity="0.45"/>
    </pattern>
  `;
  svg.appendChild(defs);

  for (const w of timeline.active_windows) {
    const s = new Date(w.start);
    const e = new Date(w.end);
    const x = sx(s);
    const ww = Math.max(2, sx(e) - x);
    const r = document.createElementNS(svgNS, "rect");
    r.setAttribute("x", x);
    r.setAttribute("y", labelGap + 4);
    r.setAttribute("width", ww);
    r.setAttribute("height", stripH - 8);
    r.setAttribute("fill", PALETTE.accent);
    r.setAttribute("opacity", "0.85");
    r.setAttribute("rx", 1);
    const title = document.createElementNS(svgNS, "title");
    title.textContent = `${w.commit_count} commits, ${s.toLocaleDateString()} – ${e.toLocaleDateString()}`;
    r.appendChild(title);
    svg.appendChild(r);
  }

  for (const g of timeline.gaps) {
    if (g.days < 365) continue;
    const s = new Date(g.start);
    const e = new Date(g.end);
    const x = sx(s);
    const ww = sx(e) - x;
    const r = document.createElementNS(svgNS, "rect");
    r.setAttribute("x", x);
    r.setAttribute("y", labelGap);
    r.setAttribute("width", ww);
    r.setAttribute("height", stripH);
    r.setAttribute("fill", "url(#hatch-strip)");
    svg.appendChild(r);
  }

  if (variant === "header") {
    const startYear = fullStart.getUTCFullYear();
    const endYear = fullEnd.getUTCFullYear();
    const span = endYear - startYear;
    const step = span > 8 ? 2 : 1;
    for (let y = startYear; y <= endYear; y += step) {
      const d = new Date(Date.UTC(y, 0, 1));
      if (d < fullStart || d > fullEnd) continue;
      const x = sx(d);
      const tx = document.createElementNS(svgNS, "text");
      tx.setAttribute("x", x);
      tx.setAttribute("y", labelGap - 4);
      tx.setAttribute("font-size", "10");
      tx.setAttribute("font-family", "-apple-system, sans-serif");
      tx.setAttribute("fill", PALETTE.inkDim);
      tx.setAttribute("text-anchor", "middle");
      tx.textContent = y;
      svg.appendChild(tx);
      const tick = document.createElementNS(svgNS, "line");
      tick.setAttribute("x1", x);
      tick.setAttribute("x2", x);
      tick.setAttribute("y1", labelGap);
      tick.setAttribute("y2", labelGap + 2);
      tick.setAttribute("stroke", PALETTE.rule);
      svg.appendChild(tick);
    }
  }

  return svg;
}
