"""Emit a per-project landing page at output/<project>/index.html.

Tiny side-by-side index so `make serve PROJECT=<name>` lands you on a page
that links to all three stacks. Helpful for the actual feel-test workflow:
open the project root, click into each stack in a new tab, compare.
"""

from __future__ import annotations

import argparse
from pathlib import Path

TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{project} — viz playground</title>
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, sans-serif;
      max-width: 640px;
      margin: 3rem auto;
      padding: 0 1.5rem;
      line-height: 1.6;
      background: #fafaf7;
      color: #1a1a1a;
    }}
    h1 {{ font-size: 1.6rem; margin-bottom: 0.25rem; }}
    .subtle {{ color: #666; font-size: 0.85rem; }}
    a.stack {{
      display: block;
      padding: 1rem 1.25rem;
      margin: 0.75rem 0;
      background: #fff;
      border: 1px solid #d4d4d4;
      border-radius: 4px;
      text-decoration: none;
      color: #1a1a1a;
    }}
    a.stack:hover {{ background: #f5f5f0; }}
    a.stack strong {{ display: block; font-size: 1rem; }}
    a.stack span {{ display: block; color: #666; font-size: 0.85rem; margin-top: 0.25rem; }}
  </style>
</head>
<body>
  <h1>{project}</h1>
  <p class="subtle">Three viz stacks rendering the same three atoms from the same real data. Open each in a new tab and compare.</p>
  <a class="stack" href="observable/">
    <strong>observable/</strong>
    <span>Observable Plot + inline JS in a markdown-vibe page (narrative-first authoring)</span>
  </a>
  <a class="stack" href="vega-lite-static/">
    <strong>vega-lite-static/</strong>
    <span>Python pipeline emits JSON specs; vega-embed renders. Specs are the deliverable.</span>
  </a>
  <a class="stack" href="hand-svg/">
    <strong>hand-svg/</strong>
    <span>Pure-Python SVG strings. Project-controlled visual vocabulary; canonical home of the lossy-region atom.</span>
  </a>
</body>
</html>
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--output-dir", required=True, type=Path)
    args = ap.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "index.html").write_text(
        TEMPLATE.format(project=args.project), encoding="utf-8"
    )
    print(f"[landing] wrote {args.output_dir / 'index.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
