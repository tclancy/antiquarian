// Shared time-axis helper for the Observable Framework variant.
//
// Implements the dual-axis approach Tom asked for in PR #11 review:
//   - The "full span" axis is the absolute project lifespan (cache min → max).
//   - The "active axis" is a piecewise scale that maps only the active windows
//     to pixel space, with explicit gap segments drawn between windows.
//
// Both axes share the same pixel range so a tick at e.g. 2015-02 in the
// reference strip aligns with the same position in the chart below.

const GAP_PX = 56; // width reserved for a "gap" segment between active windows

export function buildActiveScale(timeline, pixelWidth) {
  if (!timeline || !timeline.full_span) {
    return {
      scale: () => 0,
      gapBlocks: [],
      windows: [],
      pixelWidth,
      domain: [],
      tickValues: [],
    };
  }
  const windows = timeline.active_windows.map((w) => ({
    start: new Date(w.start),
    end: new Date(w.end),
    commitCount: w.commit_count,
  }));
  const gaps = timeline.gaps.map((g) => ({
    start: new Date(g.start),
    end: new Date(g.end),
    days: g.days,
  }));

  const winDurations = windows.map((w) => Math.max(1, w.end - w.start));
  const totalWindowMs = winDurations.reduce((a, b) => a + b, 0);

  const totalGapPx = gaps.length * GAP_PX;
  const remainingPx = Math.max(120, pixelWidth - totalGapPx);
  const MIN_WIN_PX = 36;

  let allocations = winDurations.map((d) => (d / totalWindowMs) * remainingPx);
  let undershoot = 0;
  allocations = allocations.map((a) => {
    if (a < MIN_WIN_PX) {
      undershoot += MIN_WIN_PX - a;
      return MIN_WIN_PX;
    }
    return a;
  });
  if (undershoot > 0) {
    const maxIdx = allocations.indexOf(Math.max(...allocations));
    allocations[maxIdx] = Math.max(MIN_WIN_PX, allocations[maxIdx] - undershoot);
  }

  const winStartsPx = [];
  let cursor = 0;
  for (let i = 0; i < windows.length; i++) {
    winStartsPx.push(cursor);
    cursor += allocations[i];
    if (i < gaps.length) cursor += GAP_PX;
  }
  const totalPx = cursor;

  function scale(date) {
    const d = date instanceof Date ? date : new Date(date);
    for (let i = 0; i < windows.length; i++) {
      const w = windows[i];
      const px0 = winStartsPx[i];
      const pxW = allocations[i];
      if (d >= w.start && d <= w.end) {
        const dur = Math.max(1, w.end - w.start);
        const frac = (d - w.start) / dur;
        return px0 + frac * pxW;
      }
      if (d < w.start) {
        if (i === 0) return px0;
        const prevEndPx = winStartsPx[i - 1] + allocations[i - 1];
        return prevEndPx + GAP_PX / 2;
      }
    }
    const lastIdx = windows.length - 1;
    return winStartsPx[lastIdx] + allocations[lastIdx];
  }

  const gapBlocks = gaps.map((g, i) => {
    const x0 = winStartsPx[i] + allocations[i];
    return {
      x: x0,
      width: GAP_PX,
      days: g.days,
      label: g.days >= 365 ? `${(g.days / 365).toFixed(1)}y gap` : `${g.days}d gap`,
    };
  });

  return {
    scale,
    gapBlocks,
    windows,
    allocations,
    winStartsPx,
    pixelWidth: totalPx,
    fullSpan: timeline.full_span,
  };
}
