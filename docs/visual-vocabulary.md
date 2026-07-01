# Visual vocabulary

The commitments baked into the broadsheet renderer (`antiquarian/render.py`). These exist as a doc, not just as code, so future renderer changes can be evaluated *against* them rather than drifting silently.

The aesthetic is part of the moat. There are a dozen git-history visualizers in the world; there are zero that look like a 19th-century broadsheet. That difference is the differentiation.

> **Companion:** [`visualizing-at-scale.md`](visualizing-at-scale.md) owns the *information-design* commitments — how these atoms stay legible as a codebase grows from a toy to `cpython`. This doc owns the *aesthetic*.

## What this is

**Broadsheet in the streets, Tufte in the sheets.**

Three lineages, each with a specific job:

- **Edward Tufte for the discipline.** *The Visual Display of Quantitative Information* and *Envisioning Information* set the rules every atom obeys: high data-ink ratio (every mark earns its place), multifunctioning graphical elements (the dual-axis timeline is both a chart axis *and* the structural signal of dense vs dormant periods — one mark, two jobs), show the data including what's missing (the lossy hatch is drawn at the same weight as the active windows because absence is also data), small multiples (atoms stack vertically with a shared time axis so the eye does the comparison), no chartjunk (no 3D, no decorative gradients, no animated reveals). When in doubt about a mark, ask "would Tufte cut this?" The answer is usually yes.

- **Albrecht Dürer for the mark-making language.** The diagonal woodblock-style hatching for lossy regions isn't from a chart library — it's from Renaissance engraving, where Dürer made hatching the canonical way to give weight without color. We use it the same way: lossy regions have weight, even when they have no commits to plot. Density of stroke is signal, just as it was on a 16th-century copper plate.

- **18th–19th-century broadsheet print culture for the page idiom.** The masthead, the small-caps dateline, the drop cap in oxide red, the double-rule borders, the parchment yellow paper, the printer's-chase pigment palette, the roman-numeral chapter marks between atoms. This is where the *look* lives — the discipline above is invisible until something violates it; the broadsheet idiom is the thing the reader actually sees first.

The three don't fight. Tufte's rules tell us *what* belongs on the page; Dürer's tradition tells us *how* the marks are drawn; the broadsheet tells us *where they sit*. A chart-library default would do all three jobs badly at once.

## Atoms (the commitments)

### 1. Lossy regions are first-class

Where the channel went dark — `git log --follow` rename truncation, multi-year SVN-to-Git dormancies, periods of zero commits — gets the **diagonal hatched pattern** with an explicit duration label ("1.4y gap", "the silence — 730 days"). This is the most-load-bearing visual atom in the project. The hatched-fill pattern is project-vocabulary (defined in `_defs()` with two variants: standard 8px-grid hatch and a denser 5px variant for especially-lossy stretches). Don't replace it with a "data not available" label; don't smooth it into blank space; don't render it in the same color as the active windows.

The rule comes from `ethos.md`: lossy regions are themselves signal. The visual treatment has to match.

### 2. Diff size (LoC) lives in the swimlane legend

Each commit mark on the swimlane is sized by `additions + deletions`. The legend says so explicitly. We don't render diff size as commit-message length, file-count, or any other proxy — the LoC count is the most honest cheap proxy for "how much actually changed."

### 3. One absolute time spine; the dual-axis strip is the orientation map

Two distinct surfaces, with two jobs:

- **The chart axis is the absolute spine (#117).** Every time-positioned mark — swimlane commits, arc bands, year ticks — is placed by its *true* position across the full lifespan (`min(timestamp)` → `max(timestamp)`) at uniform scale. The same date lands at the same x in every atom, so the eye can compare across atoms and (on the HTML surface) a reference can be cross-linked. Dormant stretches are **not** collapsed — they keep their true width, drawn as lossy regions (commitment #1), so absence occupies the space it really spanned. This is built by `build_absolute_scale`.
- **The dual-axis strip is the "you are here" map.** The thin reference strip — in the masthead and atop each atom — still shows *both* the full lifespan and the active-window markers (contiguous commit clusters; ≥1y gaps hatched), so the reader stays oriented to where the density actually is. It is a compass, not the plotting axis.

> **Why this changed (2026-06-17):** the chart axis used to be the gap-collapsed *active-windows* scale (windows allocated proportional pixels, gaps fixed-width). That kept brief active periods legible but meant x-position was not a real date, atoms didn't align with each other, and at scale (236 contributor rows) the single axis sat thousands of pixels from any mark. The absolute spine trades some legibility of brief early periods (they compress to a sliver — an accepted cost) for an honest, shared, cross-atom-comparable date axis. Decided in `09 - Scale Rework Scope`; the old `build_active_scale` was removed.

### 4. Multi-file label prefix + rename-truncation indicator

When the swimlane spans multiple files, each lane is prefixed with the file it belongs to. Files whose history has likely been truncated by `git log --follow` (single commit, dated > 1 year before the next-earliest commit) get a visible "history truncated at rename" indicator. We don't paper over rename-loss.

### 5. Arc bands with their own pigments

Each named arc parsed out of the per-file `## Major arcs` section gets a color from the eight-arc palette. The palette is **printer's chase** — oxide red, ink blue, forest, ochre, mauve, claret, bistre, olive. Less candy than chart-library defaults; closer to a 19th-century chromolithograph.

## Typography

- **Serif everywhere.** EB Garamond is preferred; the page degrades gracefully to Iowan Old Style → Palatino → Georgia. No sans-serif body text. No CDN-only fonts.
- **Small-caps datelines** for sectional headers (`antiquarian · field notes · vol. i`).
- **Drop caps** on the lede paragraph, in the oxide-red accent.
- **Double-rule borders** under the masthead.
- **Italic side-note glyphs** in margins for marginalia.
- **Roman-numeral chapter marks** between atoms.

## Palette

Earthy, restrained, print-press dark — **not** the bright/saturated chart-library defaults.

| Role | Hex | Description |
|------|-----|-------------|
| `ink` | `#1f1a14` | Warm dark — print-press ink, not pure black |
| `ink_dim` | `#5a4e3a` | Dimmed body text, axis labels |
| `rule` | `#a89b80` | Hairlines, table rules |
| `rule_dim` | `#d4c8b0` | Faint guidelines |
| `paper` | `#f4ead4` | Parchment yellow, the page background |
| `paper_alt` | `#ede1c4` | Aside backgrounds, alternating bands |
| `accent` | `#8a3a1f` | Oxide red — printer's stamp; drop caps; the survey-excerpt rule |
| `accent_dim` | `#c97a4a` | Faded accent |
| `lane` | `#3a4e6a` | Deep ink blue — swimlane fills |
| `lossy` | `#7a6f5e` | The hatched-pattern stroke color |

## What this is not

- **Not interactive *at the expense of the static page*.** The real constraint is that the broadsheet says everything as a complete static page — readable with JavaScript off and to assistive tech — not a ban on interactivity. The SVG atoms themselves stay static; interactive affordances live in the HTML wrapper around them (file index, story pages, floating references, search, disclosure) and **must degrade losslessly to that static baseline**. Literal print-to-paper is a nice-to-have, not a requirement (#40 demoted 2026-07-01). See [`visualizing-at-scale.md`](visualizing-at-scale.md) for the rules that govern this. *(Earlier revisions stated a blanket "not interactive" — removed 2026-06-17 — and framed the fallback as "print"; the surviving discipline is static-completeness, not paper.)*
- **Not chartlike.** No grid lines as the dominant visual element. No data-ink-to-grid-ink ratio shame. The page is composed; charts are typeset into it like figures in a book.
- **Not dashboard-vibe.** No KPI tiles. No "drill down through bubbles forever" navigation. Software-vibe, not report-vibe.
- **Not theme-able.** The aesthetic is the differentiation. We don't ship a dark-mode toggle. We don't ship a "minimal" variant. There is one broadsheet and it looks like the broadsheet.

## When the rules change

Update this doc *before* the code. A pull request that changes a committed atom should land with a parallel change to the corresponding section here, and the PR description should say why the old commitment didn't hold.
