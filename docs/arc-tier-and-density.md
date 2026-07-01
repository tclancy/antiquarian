# The arc tier & information density

A reconciliation of the tickets that all circle one question from different angles. Read this **before** answering or implementing any of them — each was scoped in isolation, so their memos cross-reference each other by number without actually resolving the dependencies between them.

## The one question

> Given the telephone-in-reverse thesis, what earns a place on the page — and how is it **tiered** so the reader meets structure, not a flat wall of co-equal signal?

Several open tickets are this question at different zoom levels: the narrative structure (arcs vs a higher "Act" tier), the arc visualization at scale, the file index, the contributor lanes. Treating them as independent is how contradictory decisions get made — and shipped.

## Governing vs downstream

Some tickets decide the **unit** everything else renders. The rest decide **how to render** whatever that unit turned out to be. Answering a downstream ticket before its governing one is where things break.

```
GOVERNING ── #149  "Do arcs gain an Act tier above them?"          answer FIRST
               │    Introduces project-wide Acts (personal itch →
               │    traction → popular → maintenance); today's arcs
               │    demote to "scenes" that attach to one or more Acts.
               ▼
DOWNSTREAM ── #112  "A layout for the named arcs that holds at scale"
               │    Its own lever-question (per-file vs cross-file arcs)
               │    is a *subset* of #149. If Acts land, the scale
               │    problem largely dissolves — you lay out 3–5 Acts,
               │    not ~400 flat per-file arcs.
               ▼
CONSUMERS (already shipped — revisit if #149 = yes)
        #119 floating arc panel   ·   #136 masthead arc-density strip
               Both render "arcs" today. If Acts become the top tier,
               these should surface Acts, not raw per-file arcs.

SHARE THE DENSITY FRAME, structurally independent of the arc tier:
        #121  file-index density — the "eraser test": drop the duplicated
              per-file description sentence; index carries one derived glyph.
        #127  contributor-lane density — collapse duplicate identity lanes
              for the visual read, keep them separate for search.

ORTHOGONAL (extensibility, not density) — but collides at the index (see below):
        #150  language / VCS backends — a per-file complexity metric.
```

## Collisions — where an isolated answer breaks another ticket

1. **#149 governs #112.** #112's memo says "decide per-file vs cross-file arcs *first*." But #149 asks the larger question — a whole Act tier above arcs. Answer #112's granularity **and** #149's Act question separately and they can contradict. #149 goes first; #112 is then re-scoped to "lay out whatever #149 made the top unit."

2. **#136 and #119 were answered/shipped under an assumption #149 may overturn.** Both render per-file arcs today. If #149 introduces Acts, the masthead's "significant arcs on hover" and the floating panel should surface **Acts**. Neither is hard to revisit, but the decision was made before its governing question was settled — the canonical example of the failure this document exists to prevent.

3. **#121 and #150 contend for the file-index glyph.** #121 rules the index leaf carries **one** derived glyph (a `#148` pip) and drops the prose sentence. #150 adds a per-file complexity metric. If #150's metric wants to *be* that glyph or add a second, it reopens #121. Settle #121's "what does the leaf carry?" first; #150 then fits its output into that budget.

4. **#112's color budget retroactively amends the shipped #119.** #112 flags the palette disagreeing with itself (8 print pigments vs 6 neon lens colors); #119 already shipped on neon. Answering #112's color question is editing #119, not deciding fresh.

## Order to answer / implement

1. **#149 first** — specifically its two core forks: (a) Acts derived structurally vs from prose, and (b) fixed vocabulary vs emergent-per-project. Everything arc-shaped waits on these.
2. **#112**, re-scoped to the unit #149 chose.
3. **A follow-up pass on #136 / #119** — "does the Act decision change what these render?" Do not skip; they shipped pre-#149.
4. **#121, then #150** — the file-index glyph budget, in that order.
5. **#127** — independent of the arc tier; answerable at any time.

## For agents

If a task touches #149, #112, #121, #127, #150, #136, or #119: read this file, find the ticket in the graph above, and **confirm its upstream dependency is resolved before proceeding**. If the governing ticket is unanswered, say so and stop — do not answer the downstream ticket in a vacuum. A confident decision made without its governing context is a confident-but-wrong output, which the [ethos](ethos.md) ranks below acknowledged uncertainty.
