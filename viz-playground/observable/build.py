"""Observable Framework variant.

Observable Framework proper requires Node + npm at build time, which the
playground brief explicitly excludes ("static HTML + Python build only"). What
matters for feel-testing is the *authoring ergonomics* and the *Observable Plot
aesthetic* — markdown narrative interleaved with inline JS chart expressions.
We capture both by emitting a static HTML page that:

  1. Renders the narrative prose alongside the charts (markdown shell vibe).
  2. Uses Observable Plot loaded from a CDN as the rendering library.
  3. Embeds the data inline as JS variables (mimicking what `${data}` template
     literals look like in an Observable Framework page).

The result reads, line-for-line, the way an `auth.py.md` Framework page would,
except the build is a single Python script instead of an npm pipeline. That's
the right trade for feel-testing — Tom can read the source and see exactly what
"Observable Plot atoms between paragraphs of markdown" feels like to write.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

# Shared visual vocabulary — keep aligned with the other two stacks so the
# variants read as variations of the same project.
PALETTE = {
    "ink": "#1a1a1a",
    "ink_dim": "#666",
    "rule": "#d4d4d4",
    "paper": "#fafaf7",
    "accent": "#b35a1f",
    "accent_dim": "#dba37e",
    "lane": "#3a5e7c",
    "lossy": "#999",
}

ARC_COLORS = ["#7c4a3a", "#3a5e7c", "#3a7c4a", "#7c6a3a", "#5e3a7c", "#7c3a5e"]


# The Observable Plot calls — written as if inline in markdown. Each is a single
# expression returning a Plot.plot() chart. Kept terse and grammar-of-graphics
# to capture the actual library feel.

TODO_STRIP_JS = """
Plot.plot({{
  marginLeft: 90,
  marginRight: 100,
  marginTop: 20,
  width: 900,
  height: Math.max(60, todos.length * 26 + 40),
  style: {{background: "{paper}", fontSize: "11px"}},
  x: {{label: "age (days) →", labelAnchor: "right"}},
  y: {{label: null, axis: null}},
  color: {{
    type: "threshold",
    domain: [365, 1000, 2000],
    range: ["{accent_dim}", "#c97a4a", "{accent}", "#7c2a0f"],
    legend: true,
    label: "age"
  }},
  marks: [
    Plot.barX(todos, {{
      x: "age_days",
      y: d => d.introduced_short,
      fill: "age_days",
      sort: {{y: "x", reverse: false}},
      tip: true,
      channels: {{
        kind: "kind",
        line: "line_number",
        text: "text",
        introduced_by: "introduced_by",
        sha: "introduced_short"
      }}
    }}),
    Plot.text(todos, {{
      x: 0,
      y: d => d.introduced_short,
      text: d => `${{d.kind}} L${{d.line_number}}: ${{d.text.slice(0, 36)}}${{d.text.length > 36 ? "…" : ""}}`,
      textAnchor: "end",
      dx: -8,
      fill: "{ink}",
      fontFamily: "ui-monospace, SF Mono, Monaco, monospace"
    }}),
    Plot.text(todos, {{
      x: "age_days",
      y: d => d.introduced_short,
      text: d => `  ${{d.age_days}}d · ${{d.introduced_by}}`,
      textAnchor: "start",
      dx: 6,
      fill: "{ink_dim}"
    }})
  ]
}})
"""

SWIMLANE_JS = """
Plot.plot({{
  marginLeft: 160,
  marginRight: 20,
  marginTop: 20,
  marginBottom: 40,
  width: 1000,
  height: Math.max(120, swimlaneRows.length === 0 ? 100 : laneOrder.length * 60 + 60),
  style: {{background: "{paper}", fontSize: "11px"}},
  x: {{type: "time", label: null, grid: true, ticks: 8}},
  y: {{domain: laneOrder, label: null, padding: 0.4}},
  r: {{range: [3, 14]}},
  color: {{
    domain: ["decisive", "supporting"],
    range: ["{accent}", "{lane}"],
    legend: true
  }},
  marks: [
    Plot.ruleY(laneOrder, {{stroke: "{rule}", strokeWidth: 0.5}}),
    Plot.dot(swimlaneRows, {{
      x: d => new Date(d.timestamp),
      y: "author",
      r: "diff",
      fill: d => d.decisive ? "decisive" : "supporting",
      stroke: d => d.decisive ? "{ink}" : null,
      strokeWidth: 0.8,
      opacity: 0.85,
      tip: true,
      channels: {{
        sha: "short_sha",
        subject: "subject",
        arcs: "arcs"
      }}
    }})
  ]
}})
"""

ARC_BAND_JS = """
Plot.plot({{
  marginLeft: 280,
  marginRight: 80,
  marginTop: 20,
  marginBottom: 40,
  width: 1100,
  height: Math.max(120, arcOrder.length * 56 + 60),
  style: {{background: "{paper}", fontSize: "11px"}},
  x: {{type: "time", label: null, grid: true, ticks: 8}},
  y: {{domain: arcOrder, label: null, padding: 0.3}},
  color: {{domain: arcOrder, range: {arc_colors_json}, legend: false}},
  marks: [
    Plot.barX(arcBands, {{
      x1: d => new Date(d.start),
      x2: d => new Date(d.end),
      y: "arc_label",
      fill: "arc_label",
      fillOpacity: 0.22,
      tip: true,
      channels: {{
        range: "date_range",
        decisive: "commit_count"
      }}
    }}),
    Plot.tickX(arcTicks, {{
      x: d => new Date(d.timestamp),
      y: "arc_label",
      stroke: "arc_label",
      strokeWidth: 2.5,
      tip: true,
      channels: {{
        sha: "short_sha",
        subject: "subject"
      }}
    }})
  ]
}})
"""


def render_page(
    project: str,
    manifest: dict,
    todos: list[dict],
    swimlane: dict,
    arc_band: dict,
) -> str:
    swimlane_rows = []
    lane_order = []
    for lane in swimlane["lanes"]:
        lane_order.append(lane["author"])
        for c in lane["commits"]:
            swimlane_rows.append(
                {
                    "author": lane["author"],
                    "timestamp": c["timestamp"],
                    "diff": c["additions"] + c["deletions"],
                    "subject": c["subject"],
                    "short_sha": c["short_sha"],
                    "decisive": bool(c["arcs"]),
                    "arcs": ", ".join(c["arcs"]) or "—",
                }
            )

    arc_bands = []
    arc_ticks = []
    arc_order = []
    file_paths = {arc["file_path"] for arc in arc_band["arcs"]}
    multi_file = len(file_paths) > 1
    for arc in arc_band["arcs"]:
        basename = arc["file_path"].rsplit("/", 1)[-1]
        prefix = f"[{basename}] " if multi_file else ""
        label = f"{prefix}Arc {arc['arc_number']}: {arc['name']}"
        arc_order.append(label)
        datable = [c for c in arc["commits"] if c["timestamp"]]
        if datable:
            arc_bands.append(
                {
                    "arc_label": label,
                    "start": datable[0]["timestamp"],
                    "end": datable[-1]["timestamp"],
                    "date_range": arc["date_range"] or "",
                    "commit_count": arc["commit_count"],
                }
            )
        for c in arc["commits"]:
            if not c["timestamp"]:
                continue
            arc_ticks.append(
                {
                    "arc_label": label,
                    "timestamp": c["timestamp"],
                    "short_sha": c["short_sha"],
                    "subject": c["subject"],
                }
            )

    todo_strip_expr = TODO_STRIP_JS.format(**PALETTE).strip()
    swimlane_expr = SWIMLANE_JS.format(**PALETTE).strip()
    arc_band_expr = ARC_BAND_JS.format(
        arc_colors_json=json.dumps(ARC_COLORS),
        **PALETTE,
    ).strip()

    files_list = "".join(
        f"<li><code>{f}</code></li>" for f in manifest.get("files", [])
    )
    stories_list = (
        "".join(f"<li><code>{s}</code></li>" for s in manifest.get("stories", []))
        or "<li><em>none</em></li>"
    )

    # Honest empty-state messaging woven into the markdown shell, like an
    # Observable Framework page would do with a {if condition} expression.
    todo_intro = (
        "Nine TODO admissions currently in this file. Bar length = days survived. "
        "Oldest first. The clustering at the top is the archaeological cohort — "
        "branches the author couldn't justify but couldn't delete."
        if todos
        else (
            "This file currently carries no TODO/FIXME admissions. That itself is "
            "a signal of the maintainers' standards."
        )
    )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Antiquarian — Observable Plot — {project}</title>
  <script type="module">
    import * as Plot from "https://cdn.jsdelivr.net/npm/@observablehq/plot@0.6.16/+esm";
    window.Plot = Plot;
    window.dispatchEvent(new Event('plot-ready'));
  </script>
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, sans-serif;
      background: {PALETTE["paper"]};
      color: {PALETTE["ink"]};
      max-width: 1100px;
      margin: 2rem auto;
      padding: 0 1.5rem;
      line-height: 1.6;
    }}
    h1 {{ font-size: 1.6rem; margin-bottom: 0.25rem; }}
    h2 {{ font-size: 1.15rem; margin-top: 2.5rem; }}
    p {{ max-width: 70ch; color: {PALETTE["ink"]}; }}
    .subtle {{ color: {PALETTE["ink_dim"]}; font-size: 0.85rem; }}
    .atom {{
      margin: 1rem 0 2.5rem;
    }}
    .meta {{
      display: flex;
      gap: 2rem;
      flex-wrap: wrap;
      font-size: 0.85rem;
      margin: 1rem 0;
      padding: 0.75rem 1rem;
      background: #fff;
      border: 1px solid {PALETTE["rule"]};
      border-radius: 4px;
    }}
    .meta ul {{ margin: 0.25rem 0 0; padding-left: 1.25rem; }}
    code {{ font-family: ui-monospace, "SF Mono", Monaco, monospace; font-size: 0.85em; }}
    .stack-badge {{
      display: inline-block;
      padding: 2px 8px;
      background: {PALETTE["accent"]};
      color: white;
      border-radius: 3px;
      font-size: 0.7rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }}
    .plot-target {{
      background: {PALETTE["paper"]};
    }}
  </style>
</head>
<body>
  <h1>{project} <span class="stack-badge">Observable Plot</span></h1>
  <div class="subtle">Generated {manifest.get("generated_at", "")}</div>

  <div class="meta">
    <div>
      <strong>Files in cache:</strong>
      <ul>{files_list}</ul>
    </div>
    <div>
      <strong>Stories:</strong>
      <ul>{stories_list}</ul>
    </div>
  </div>

  <p>
    This page reads the way an Observable Framework markdown page reads —
    narrative prose interleaved with inline Plot expressions. The data is
    embedded inline below; the charts render via Observable Plot on page load.
  </p>

  <h2>What admissions has this file been carrying?</h2>
  <p>{todo_intro}</p>
  <div class="atom"><div id="todo-strip" class="plot-target"></div></div>

  <h2>Who worked on this file, when?</h2>
  <p>
    One row per contributor, time on X. Dot size scales with diff size; filled
    dots are commits the historian flagged as decisive (i.e., load-bearing
    enough to be named in the file's story).
  </p>
  <div class="atom"><div id="swimlane" class="plot-target"></div></div>

  <h2>What arcs did the file move through?</h2>
  <p>
    The Major Arcs the historian found in the file, rendered as time bands.
    Each tick is a commit the story explicitly cited. The shape of the band
    tells you whether an arc landed in a burst (Sync correctness, April 17)
    or unfolded across weeks (Gardener gate).
  </p>
  <div class="atom"><div id="arc-band" class="plot-target"></div></div>

  <footer class="subtle" style="margin-top: 3rem; border-top: 1px solid {PALETTE["rule"]}; padding-top: 1rem;">
    Observable Plot variant. Three Plot expressions, each authored inline next
    to its paragraph of narrative — capturing the Observable Framework
    authoring ergonomics without the Node build step. Data is embedded inline.
  </footer>

  <script>
    const todos = {json.dumps(todos)};
    const swimlaneRows = {json.dumps(swimlane_rows)};
    const laneOrder = {json.dumps(lane_order)};
    const arcBands = {json.dumps(arc_bands)};
    const arcTicks = {json.dumps(arc_ticks)};
    const arcOrder = {json.dumps(arc_order)};

    function renderAll() {{
      const Plot = window.Plot;
      document.getElementById('todo-strip').replaceChildren(
        todos.length === 0
          ? Object.assign(document.createElement('div'), {{
              textContent: '(no TODOs — empty atom)',
              style: 'padding: 1.5rem; color: {PALETTE["ink_dim"]}; font-style: italic;'
            }})
          : ({todo_strip_expr})
      );
      document.getElementById('swimlane').replaceChildren({swimlane_expr});
      document.getElementById('arc-band').replaceChildren({arc_band_expr});
    }}

    if (window.Plot) {{
      renderAll();
    }} else {{
      window.addEventListener('plot-ready', renderAll);
    }}
  </script>
</body>
</html>
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--data-dir", required=True, type=Path)
    ap.add_argument("--output-dir", required=True, type=Path)
    args = ap.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)

    manifest = json.loads((args.data_dir / "manifest.json").read_text())
    todos = json.loads((args.data_dir / "todos.json").read_text())
    swimlane = json.loads((args.data_dir / "swimlane.json").read_text())
    arc_band = json.loads((args.data_dir / "arc_band.json").read_text())

    html = render_page(args.project, manifest, todos, swimlane, arc_band)
    (args.output_dir / "index.html").write_text(html, encoding="utf-8")
    print(f"[observable] wrote {args.output_dir / 'index.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
