---
title: Antiquarian story view
toc: false
---

```js
// All atoms in this page read from the same data set the other two stacks read.
// `FileAttachment(...)` is the Observable Framework-native way to load a static
// asset at build time.
const meta = await FileAttachment("data/active-project.json").json();
const commits = await FileAttachment("data/commits.json").json();
const todos = await FileAttachment("data/todos.json").json();
const swimlane = await FileAttachment("data/swimlane.json").json();
const arcBand = await FileAttachment("data/arc_band.json").json();
const timeline = await FileAttachment("data/timeline.json").json();
const lifespans = await FileAttachment("data/file_lifespans.json").json();
```

```js
import {timelineStrip} from "./components/timelineStrip.js";
import {todoStrip} from "./components/todoStrip.js";
import {swimlaneChart} from "./components/swimlane.js";
import {arcBandChart} from "./components/arcBand.js";
```

<div class="dateline">Antiquarian field notes · ${meta.project}</div>

# A history reconstructed from the surviving record

<div class="byline">${meta.files.length} files surveyed · ${commits.length} commits in cache · ${meta.stories.length} per-file stories · ${arcBand.arc_count} named arcs</div>

This is what an Observable Framework page looks like when the priority is **reading**, not dashboard-browsing. The charts below are evidence cited inline next to the paragraph that explains them — not panels in a grid, not tiles in a control surface. Same JSON the other two stacks read; a deliberately different presentation.

The project under examination is <code>${meta.project}</code>. The historian's record runs from <strong>${new Date(timeline.full_span.start).toLocaleDateString("en-US", {month: "long", year: "numeric"})}</strong> to <strong>${new Date(timeline.full_span.end).toLocaleDateString("en-US", {month: "long", year: "numeric"})}</strong> — ${(timeline.full_span.days / 365).toFixed(1)} years across the surviving commit history. The visible activity falls into ${timeline.active_windows.length} cluster${timeline.active_windows.length === 1 ? "" : "s"}, with ${timeline.gaps.filter(g => g.days >= 365).length} significant dormancy gap${timeline.gaps.filter(g => g.days >= 365).length === 1 ? "" : "s"} between them. The bar atop each chart below shows the full span as a reference strip; the chart proper compresses time to only when the files existed, with the dormancies preserved as visible gaps.

```js
display(timelineStrip(timeline, {variant: "header"}))
```

<div class="section-mark">I.</div>

## What admissions has this code been carrying?

```js
const todoIntro = todos.length === 0
  ? html`The files in this survey currently carry <strong>no TODO/FIXME admissions</strong>. Read that as the maintainers either fixing things they noticed or deciding the source isn't the place to leave a note. In other codebases, this column is a quiet archaeology — the oldest TODOs are usually the ones the author couldn't fix but couldn't delete.`
  : html`Below: every TODO and FIXME currently live in the surveyed files, sorted by the date the admission was first introduced. The longer the bar, the longer the admission has survived. The bands suggest cohorts — clusters of TODOs introduced in a single cleanup pass, which then sit in place for years afterward.`;
display(todoIntro);
```

```js
display(html`<figure class="atom">
  <div class="fig-label">Figure 1 — TODO age</div>
  <div class="timeline-strip">${timelineStrip(timeline, {variant: "atom"})}</div>
  ${todoStrip(todos, timeline)}
  <figcaption>Lines of TODO/FIXME admission, oldest at top. Color encodes age cohort. The reference strip above shows where each admission sits in the project's full lifespan.</figcaption>
</figure>`);
```

<div class="section-mark">II.</div>

## Who worked on these files, when?

A swimlane: one row per contributor, time on the X-axis (compressed to only the active windows so the bursts are legible), and a mark per commit. Mark **area scales with diff size in lines of code** — the bigger the dot, the more LoC the commit changed. Filled marks are commits the historian flagged as decisive enough to name in a per-file story.

```js
display(html`<figure class="atom">
  <div class="fig-label">Figure 2 — Author swimlane</div>
  <div class="timeline-strip">${timelineStrip(timeline, {variant: "atom"})}</div>
  ${swimlaneChart(swimlane, timeline)}
  <figcaption>One row per contributor. Mark size = lines of code changed (legend right). Filled marks are decisive commits the historian named. Gaps between active windows are drawn explicitly with a "dormancy" label.</figcaption>
</figure>`);
```

```js
const bigGaps = timeline.gaps.filter(g => g.days >= 365).sort((a, b) => b.days - a.days);
if (bigGaps.length > 0) {
  const longest = bigGaps[0];
  const yrs = (longest.days / 365).toFixed(1);
  display(html`<div class="aside">
    <strong>Dormancy.</strong> The longest gap in the visible record runs from
    ${new Date(longest.start).toLocaleDateString("en-US", {month: "short", year: "numeric"})}
    to ${new Date(longest.end).toLocaleDateString("en-US", {month: "short", year: "numeric"})}
    — ${yrs} years. The record going dark for ${yrs} years is the data; whether the
    project actually went dormant is the inference. The historian flags this as
    a "lossy region" and refuses to fill it in.
  </div>`);
}
```

```js
const truncated = lifespans.filter(f => f.likely_rename_truncated);
if (truncated.length > 0) {
  display(html`<div class="aside">
    <strong>Truncated history.</strong>
    ${truncated.length} file${truncated.length === 1 ? "" : "s"}
    (<code>${truncated.map(f => f.file_path).join("</code>, <code>")}</code>)
    appear${truncated.length === 1 ? "s" : ""} with only one commit, isolated from the
    rest of the cluster. This is the fingerprint of a <code>git log --follow</code>
    that lost the rename chain — earlier history exists but is hidden behind a
    rename boundary the miner didn't cross. The visualization preserves the file
    in the cohort but the apparent dormancy is an artifact of the data layer,
    not the project.
  </div>`);
}
```

<div class="section-mark">III.</div>

## What arcs did the historian find?

The per-file stories surface named arcs — the historian's interpretation of what was happening in the file across stretches of commits. The chart below puts each arc on its own row and draws the time band it covers, with thick ticks marking the commits the story explicitly cited as decisive.

When arcs span multiple files (the survey synthesis identified five such cross-file arcs in `comictagger`: the 2013 SVN-to-Git boundary, the 2015 `comicapi` extraction, the fcanc PEP 8 campaign, the 2022 Welch modernization, and the pluggable-talker arc), the file basename is shown in mono prefix.

```js
display(html`<figure class="atom">
  <div class="fig-label">Figure 3 — Per-arc SC ranking band</div>
  <div class="timeline-strip">${timelineStrip(timeline, {variant: "atom"})}</div>
  ${arcBandChart(arcBand, timeline)}
  <figcaption>Each row is one arc the historian named. Band span = first → last decisive commit. Ticks within the band are the commits the story explicitly cited.</figcaption>
</figure>`);
```

```js
const fileToArcs = new Map();
for (const arc of arcBand.arcs) {
  if (!fileToArcs.has(arc.file_path)) fileToArcs.set(arc.file_path, []);
  fileToArcs.get(arc.file_path).push(arc);
}
const filesWithArcs = [...fileToArcs.keys()];
if (filesWithArcs.length > 1) {
  display(html`<p>Across the ${filesWithArcs.length} files surveyed, ${arcBand.arc_count} arcs surface. Files in <code>comicapi/</code> tend to travel as a unit — coupled birth, shared modernization pass, simultaneous dormancy — while the GUI shell and the metadata-source plugin run on their own tracks. The chart above will read most honestly if you scan it by file rather than by arc number: arcs sharing a file basename usually share an author, too.</p>`);
}
```

<hr>

<div class="aside">
  <strong>About this stack.</strong> This page is built with the real
  <a href="https://observablehq.com/framework/">Observable Framework</a> — Node + npm,
  <code>npm run dev</code> for live preview, <code>npm run build</code> for static output.
  The data is loaded as file attachments at build time and the page reads as
  narrative prose with charts cited inline. Compare to the other two stacks in
  this playground: <em>vega-lite-static</em> (instrument-panel density) and
  <em>hand-svg</em> (broadsheet typography). Same data, three very different
  presentations.
</div>
