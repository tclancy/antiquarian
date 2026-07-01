# Visualizing at scale

Companion to [`visual-vocabulary.md`](visual-vocabulary.md). That doc owns the *aesthetic* commitments of the broadsheet; this one owns the *information-design* commitments — how a view stays legible as the underlying codebase grows from a toy to `cpython`.

It exists as a doc, not just code, for the same reason: so the larger visualization rework can be evaluated *against* these principles rather than re-deciding them per atom. The worked example (Files surveyed, issues #108/#109) is here to make the principles concrete — but the principles are the point.

---

## Principles

### 1. Spend an information budget; disclose the rest progressively

A view has a **budget**: the number of elements a reader can take in at a glance before it becomes noise. Past that, every additional element subtracts from comprehension instead of adding to it. So: render up to the budget initially, and put the remainder one deliberate interaction away.

The budget is a property of the *reader*, not the data — so it's a near-constant (~30 rows for a list; fewer for denser marks). Treat it as a named constant per atom, tunable in one place.

### 2. Adapt to the shape of the data, not to fixed thresholds

"At 100 files do X, at 50 do Y" is a smell: magic numbers that fit the repo you happened to test on. Instead, **derive the layout from the actual data and the budget.** A repo with 60 files in one flat folder and a repo with 60 files nested ten deep want different initial states; a rule keyed on the count alone can't tell them apart, but a rule keyed on the realized tree can.

Concretely: pick the *most-revealed* state that still fits the budget. This degrades smoothly — small inputs render fully, large inputs collapse exactly as much as they must, and nothing snaps at an arbitrary boundary.

### 3. Static-complete; interactivity is additive (carries #40 forward — print demoted 2026-07-01)

The broadsheet must say everything as a **complete static page** — readable with JavaScript off and to assistive tech. Every interactive affordance is progressive enhancement: collapsing, filtering, hover cards, and tabbing are conveniences layered on top of a page that is already whole without them. The static baseline carries the data (e.g. an SVG `<title>` where a JS card merely adds a link). If a feature can't degrade to that baseline, it doesn't belong on the broadsheet.

Literal print-to-paper is now a **nice-to-have, not a requirement** (#40 demoted — nobody prints a 25,000px broadsheet). `@media print` rules stay welcome and are nearly free once a page is static-complete, but they no longer gate a feature. The discipline that survives is *static-completeness*, which was the part actually earning its keep — no-JS and screen-reader robustness, not paper.

### 4. Degrade gracefully without JavaScript; reach for native primitives first

Structure should come from the markup, not a script. Prefer native primitives — `<details>/<summary>` for disclosure, `<table>` for tabular data, anchors for navigation — so the view is fully usable with JS disabled or still loading. Reserve JavaScript for genuine *enhancements* (live search), never for the baseline. This also means less code to own and fewer ways to break.

### 5. Separate pure layout-logic from rendering

The decisions — how to nest, where to cut, what starts open — are pure data→data transforms and belong in their own module, unit-tested in isolation against many shapes and sizes. Rendering is then a thin shell that walks the computed structure and emits markup. This keeps `render.py` from accreting logic it can't be tested for, and lets the hard part (the adaptive rule) be proven independently of HTML.

### 6. Search is progressive reveal, not a separate view

Filtering is the same budget principle run in reverse: the reader narrows the data, so more of it can be shown. A search box should reveal matches *in place* — opening the branches that contain them, hiding the rest — not navigate to a different page or mode. It composes with disclosure rather than replacing it, and it's a pure enhancement (principle 4): no box, no problem.

---

## Worked example: Files surveyed (#108 collapse, #109 search)

The flat `<ul>` of every surveyed file is overwhelming at scale (115 files for httpx; thousands for a real codebase). Applying the principles:

### Module structure (principle 5)

New pure module `antiquarian/file_tree.py`:

- **in:** the flat list of file paths (+ per-file descriptions, + which have story pages).
- **out:** a nested tree of folder/file nodes, and the computed initial **open-depth**.
- no HTML, no I/O. `render.py` consumes the tree and emits `<details>`.

### The depth-target formula (principles 1 + 2)

Let *open-depth `D`* mean: folders shallower than `D` render `open`; folders at depth ≥ `D` render collapsed. Let *visible(`D`)* be the count of nodes (folder summaries + files) whose ancestors are all open — i.e. nodes at tree-depth ≤ `D`.

> **Choose `D* = the largest D such that visible(D) ≤ TARGET`** (default `TARGET = 30`), with a floor of `D = 0`.

- Small repo → even full depth fits the budget → everything open.
- httpx-scale → only the top-level folder summaries fit → opens to those.
- Adapts to the realized tree, not a file-count bucket (principle 2). Uniform depth (not per-folder) keeps it predictable and trivially testable.
- Sorting: folders first, then files, alphabetically.

### Collapse rendering (principles 3 + 4)

Each folder → `<details{ open if depth < D* }><summary>name (count)</summary>…</details>`; files stay `<li><a href="stories/…">`. One CSS block. For print:

```css
@media print {
  details > * { display: block; }  /* force every disclosure open, regardless of [open] */
  .file-search { display: none; }  /* hide the live-search control */
}
```

Zero JavaScript required to read or navigate the tree.

### Search (principle 6)

A search `<input>` above the tree plus a small inline vanilla `<script>`: on input, hide files whose path doesn't match and `open` any `<details>` that contains a match (empty branches hide); clearing restores the server's initial open-depth. No-JS → the box isn't wired but the tree is fully usable; print → box hidden, full tree shown.

### Testing (principle 5)

- `file_tree.py`: unit tests for tree-building, the depth formula across sizes and shapes (flat, deep, lopsided), root-level files, and edge cases (empty, single file).
- `render.py`: assert nested `<details>` appear, the computed open-depth is applied, and the search scaffold + `@media print` rules are present.
- TDD throughout (red → green).

### Deliberately out of v1

**Single-child path compression** (collapsing `a/b/c/file.py` chains into one `a/b/c/` row, VS Code-style). It would spend the budget more efficiently, but adds real complexity. Ship the adaptive tree first; revisit compression as a follow-up if the budget feels wasted on deep lonely chains.

---

## Applying this to the larger visualization rework

The same six principles govern the other atoms. Each currently renders everything; each needs a scale story:

- **Swimlane (per-author commit lanes).** Budget = lanes shown. Adapt: rank authors by contribution, show the top lanes within budget, fold the long tail into an "others" lane that discloses on demand (principles 1, 2, 6). Print shows all lanes.
- **Arc band (named arcs over time).** This is the open research item (#112). Budget applies to simultaneous arcs; progressive disclosure might mean small-multiples or a foldable legend (principles 1, 3).
- **Timeline / dormancy strip.** Already dense by design; the budget here is *tick labels*, not events — thin the labels adaptively while keeping every mark (principle 2). The marks are the data; the labels are the budget.
- **Dramatis personae.** Same shape as the swimlane: top-N within budget, tail disclosed.
- **TODO strip.** Budget = bars shown; adapt by age or severity, disclose the rest.

The recurring move: **identify what the budget is measured in for that atom** (rows, lanes, labels, bars), **derive the cut from the realized data**, and **make every fold survive as a complete static view**. When in doubt, the lossy-region ethos applies here too — if something is elided, *say so* (a visible "+N more"), never silently truncate.

---

## See also

- [`visual-vocabulary.md`](visual-vocabulary.md) — the aesthetic commitments these scale.
- [`ethos.md`](ethos.md) — lossiness as first-class output; "say what was lost."
- Issue #40 — print-first broadsheet. Issues #108/#109 — the worked example. #112 — named-arcs-at-scale research.
