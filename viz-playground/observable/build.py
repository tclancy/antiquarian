"""Observable Framework variant — real npm build.

This stack is now a full Observable Framework project (under `observable/`)
with `package.json`, `observablehq.config.js`, and `src/index.md`. The build
process is:

  1. Copy per-project JSON from `output/<project>/data/` into
     `observable/src/data/` (Framework reads these as FileAttachments).
  2. Drop a tiny `data/active-project.json` that the markdown uses to label
     the page and surface metadata.
  3. Run `npm install` on first build (no package-lock yet) or `npm ci` on
     subsequent runs, then `observable build` against a per-project config
     so two parallel `make` runs don't collide.
  4. Copy `dist-<project>/` to `output/<project>/observable/` so the
     playground server can serve all three stacks from the same per-project
     root.

`make observable PROJECT=<name>` is the entry point. `npm run dev` (from the
`observable/` directory) is the dev loop — it watches `src/` and reloads.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent  # viz-playground/observable/


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--data-dir", required=True, type=Path)
    ap.add_argument("--output-dir", required=True, type=Path)
    ap.add_argument(
        "--skip-npm-install",
        action="store_true",
        help="Skip `npm install` (set if you've already installed deps).",
    )
    args = ap.parse_args()

    src_data_dir = HERE / "src" / "data"
    src_data_dir.mkdir(parents=True, exist_ok=True)

    # Copy every JSON file the markdown might want — keep the names stable
    # so `FileAttachment("data/commits.json")` resolves regardless of project.
    wanted = [
        "commits.json",
        "todos.json",
        "swimlane.json",
        "arc_band.json",
        "manifest.json",
        "timeline.json",
        "file_lifespans.json",
    ]
    for name in wanted:
        src = args.data_dir / name
        if not src.exists():
            print(f"[observable] missing {src}", file=sys.stderr)
            continue
        shutil.copy(src, src_data_dir / name)

    # Drop the project metadata file the markdown reads first.
    manifest = json.loads((args.data_dir / "manifest.json").read_text())
    active = {
        "project": args.project,
        "files": manifest.get("files", []),
        "stories": manifest.get("stories", []),
        "generated_at": manifest.get("generated_at", ""),
    }
    (src_data_dir / "active-project.json").write_text(
        json.dumps(active, indent=2), encoding="utf-8"
    )

    # Ensure node_modules — auto-install on first build if missing.
    node_modules = HERE / "node_modules"
    if not node_modules.exists() and not args.skip_npm_install:
        print("[observable] node_modules missing — running `npm install`")
        lock = HERE / "package-lock.json"
        cmd = ["npm", "ci"] if lock.exists() else ["npm", "install"]
        rc = subprocess.call(cmd, cwd=HERE)
        if rc != 0:
            print(f"[observable] {' '.join(cmd)} failed (rc={rc})", file=sys.stderr)
            return rc

    # Build into a project-scoped dist subdir. The Framework reads `output`
    # from the config, so we generate a per-project config that overrides
    # just the `output` key.
    dist_dir = HERE / f"dist-{args.project}"
    if dist_dir.exists():
        shutil.rmtree(dist_dir)

    project_config = HERE / f"observablehq.config.{args.project}.js"
    project_config.write_text(
        f"""// Generated per-project config — output dir scoped to {args.project}.
import base from "./observablehq.config.js";
export default {{ ...base, output: "dist-{args.project}" }};
""",
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["ANTIQUARIAN_PROJECT"] = args.project
    env.setdefault("OBSERVABLE_TELEMETRY_DISABLE", "1")

    print(f"[observable] building → {dist_dir}")
    rc = subprocess.call(
        [
            "npx",
            "--no",
            "observable",
            "build",
            "--config",
            str(project_config),
        ],
        cwd=HERE,
        env=env,
    )
    if rc != 0:
        print(f"[observable] observable build failed (rc={rc})", file=sys.stderr)
        return rc

    # Copy dist into the project's output dir.
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for child in args.output_dir.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
    for child in dist_dir.iterdir():
        dst = args.output_dir / child.name
        if child.is_dir():
            shutil.copytree(child, dst)
        else:
            shutil.copy(child, dst)

    print(f"[observable] wrote {args.output_dir / 'index.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
