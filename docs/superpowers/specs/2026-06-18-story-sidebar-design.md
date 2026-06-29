# Design: directory-navigation sidebar for story pages

- **Date:** 2026-06-18
- **Issue:** #138 (sidebar part only — PR4 of the index-as-map sequence)
- **Branch:** `claude/story-sidebar-138`
- **Status:** spec answered 2026-06-18 (Tom); implementation flipped from
  draft to ready 2026-06-28 with all 5 spec items resolved (see "Resolutions"
  at the bottom of this doc)

## What was built

A directory-navigation sidebar for per-file story pages. A reader landing on any
story page can now see sibling files (same directory), navigate to sibling stories,
and orient themselves in the path hierarchy — without returning to the broadsheet
index first.

## Structure

```
<div class="story-layout">          ← new flex wrapper (block fallback without nav)
  <nav class="story-nav">           ← injected only when siblings exist
    <div class="nav-parent">        ← single parent link: "../" or "← broadsheet"
    <ul class="nav-siblings">       ← ±5 window centered on current; current is nav-current
  </nav>
  <article class="story">           ← unchanged article
```

The layout uses `:has(.story-nav)` to activate flex only when the nav element is
actually present, so pages rendered without a sidebar (sole file in its directory,
or `all_files` not supplied) keep their existing centered single-column look. No
JS, no class toggling — CSS feature detection via `:has()`.

## How it reuses `file_tree.py`

A new pure function `siblings_for_file(file_path, all_files) -> list[str]` was
added to `file_tree.py`. It extracts the parent directory from `file_path`, then
filters `all_files` to those with the same parent — no tree construction needed.
`build_file_tree` (which builds the full nested tree) is deliberately not used here:
the sidebar only needs the current directory slice, not the whole forest.

The rendering function `_render_story_sidebar` in `render.py` calls
`siblings_for_file` and emits the HTML; pure logic and rendering stay separated,
mirroring the `file_tree.py` / `_render_file_index` pattern.

## How it slots into the story-page template

`render_story_page` gains two keyword-only parameters:

```python
render_story_page(
    file_path, story_md, project,
    *,
    all_files: list[str] | None = None,
    files_with_stories: set[str] | None = None,
)
```

`pipeline._render_story_pages` passes `data["files"]` and the full set of
`candidates` (all story `.md` filenames that exist on disk) before the parallel
render loop begins. Because all candidates will have pages written, passing all of
them up-front is correct — a sibling link will not 404.

## Print degradation

`@media print { .story-nav { display: none; } }` — the sidebar is hidden entirely.
Print is the complete record; the broadsheet "← back" link in the dateline
already provides orientation context on paper. No breadcrumb fallback is needed
because the article's dateline already shows the file path and project name.

## Open questions for Tom

1. **Sidebar placement / width.** The current design puts the sidebar on the
   *left* (180px), article on the right. Left feels natural as a table-of-contents
   analogue. But since `← back to broadsheet` is also top-left, the two navigation
   affordances compete. Should the sidebar live on the right instead? Or above the
   article at narrow widths only?

2. **Full tree vs current-dir-only.** Today the sidebar shows only the current
   directory's siblings. For files deep in a heavily-nested tree (e.g.
   `src/api/handlers/auth.py`), a reader may want to jump to `src/api/urls.py`
   without going back to the broadsheet. The alternative is a
   collapsed full-tree similar to `_render_file_index` — but that risks duplicating
   the broadsheet index. Which scope is right: current-dir slice, or full
   collapsible tree in miniature?

3. **Unlinked siblings.** Files in the same directory that have *no* story page
   appear as plain `<code>` text (greyed out). This is honest — the record doesn't
   exist — but it might look like a broken link to a reader. Should unlinked
   siblings be omitted entirely, or shown with a faint style to signal "surveyed
   but no story yet"?

4. **Deep trees / long sibling lists.** `numpy/core/` has ~80 files. A sidebar
   listing 80 siblings is not useful. A cap (top N by first-commit recency? alpha?)
   or a collapse (show 10, `… 70 more`) would help. What's the right truncation
   strategy, and should it align with the broadsheet's `file-budget` approach?

5. **Relationship to the eventual gutter timeline (#138 phase 2).** The gutter
   timeline (commit-bubble timeline down the right margin) was explicitly deferred.
   When it lands, it will occupy the right edge of the story article. The current
   sidebar is on the left — they should not conflict. But if the gutter ever moves
   to the left, the sidebar will need to relocate or merge with it. Worth flagging
   now so the gutter's layout decision is made with the sidebar in view.

## Resolutions (Tom, 2026-06-18 13:32 ET)

1. **Placement** — keep left; **drop it lower** so it stops bleeding over the
   article body. Implemented as a top padding-band on `.story-nav` so the
   sidebar's first content lines up below the article's dateline + title +
   double-rule, separating it from the article's own `← back to broadsheet`
   affordance.
2. **Full folder path → drop it.** Replaced with a single parent-nav line:
   `../` in a subdir, `← broadsheet` at the root. Both target `../index.html`;
   the label differs by context. The previous `.nav-breadcrumb` /
   `.nav-sep` / `.nav-dir` classes are gone.
3. **Sibling scope** — immediate siblings only. No change; `siblings_for_file`
   already enforces this.
4. **Unlinked siblings** — grey text. No change; `.nav-unlinked` already does this.
5. **Long lists → window of ±5.** New pure helper `file_tree.window_siblings`
   trims to at most 5 siblings above and below the current file (controllable
   via `render.STORY_SIDEBAR_WINDOW`). `numpy/core/` (~80 files) now renders
   11 entries max instead of 80.
6. **Gutter timeline (phase 2)** — acknowledged; no conflict with left placement.
