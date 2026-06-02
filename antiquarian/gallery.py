"""Gallery assembler — compose rendered broadsheets into one Pages site (#92).

The gallery is the Option B adoption surface (issue #86): a precomputed
collection of famous-repo broadsheets published to GitHub Pages, so a curious
visitor sees the beautiful artifact *for free* before being asked to run
anything. This module is the cheap, idempotent half of that — it takes
broadsheets that ``antiquarian render`` already produced and assembles them
into a self-contained gallery tree. It makes no network or ``claude -p``
calls; generation (the expensive, API-key half) lives in #93.

The visual identity (parchment palette, EB Garamond, oxide-red accent) is
shared with the broadsheet via :data:`antiquarian.render.PALETTE` so the
landing page reads as the same publication.
"""

from __future__ import annotations

import re
import shutil
import tomllib
from dataclasses import dataclass
from html import escape
from pathlib import Path
from string import Template

from antiquarian.render import PALETTE

_FONT_STACK = "EB Garamond, Iowan Old Style, Palatino, Georgia, serif"
_REQUIRED_REPO_FIELDS = ("slug", "name", "tagline", "github_url", "render_dir")
# A slug becomes both a filesystem directory under the output dir and an href
# in the landing page, so it must be a single safe path segment — no slashes,
# no leading dot (rejects "." / ".."), no traversal.
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


class GalleryError(Exception):
    """Raised for any malformed manifest or missing render input."""


@dataclass(frozen=True)
class RepoEntry:
    """One featured repository in the gallery."""

    slug: str
    name: str
    tagline: str
    github_url: str
    render_dir: str


@dataclass(frozen=True)
class GalleryManifest:
    """Parsed ``gallery.toml`` — the gallery's masthead plus its repos."""

    title: str
    subtitle: str
    action_url: str
    repos: list[RepoEntry]


# --------------------------------------------------------------------------
# Manifest loading
# --------------------------------------------------------------------------


def load_manifest(path: Path) -> GalleryManifest:
    """Parse and validate a ``gallery.toml`` manifest.

    Fails loudly: a missing file, a missing required repo field, an empty
    repo list, or a duplicate slug all raise :class:`GalleryError`.
    """
    if not path.exists():
        raise GalleryError(f"manifest not found: {path}")
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise GalleryError(f"manifest is not valid TOML: {e}") from e

    section = raw.get("gallery", {})
    repos = [_parse_repo(i, entry) for i, entry in enumerate(raw.get("repos", []))]
    _reject_duplicate_slugs(repos)
    return GalleryManifest(
        title=section.get("title", "The Antiquarian Gallery"),
        subtitle=section.get("subtitle", ""),
        action_url=section.get("action_url", ""),
        repos=repos,
    )


def _parse_repo(index: int, entry: object) -> RepoEntry:
    """Build a :class:`RepoEntry`, raising on any malformed field."""
    label = f"repo #{index + 1}"
    if not isinstance(entry, dict):
        raise GalleryError(
            f"{label} must be a [[repos]] table, got {type(entry).__name__}"
        )
    for field in _REQUIRED_REPO_FIELDS:
        value = entry.get(field)
        if not value or not isinstance(value, str):
            raise GalleryError(f"{label} is missing required string field '{field}'")
    repo = RepoEntry(**{f: entry[f] for f in _REQUIRED_REPO_FIELDS})
    if not _SLUG_RE.match(repo.slug):
        raise GalleryError(
            f"{label} has invalid slug '{repo.slug}' — slugs must match "
            f"{_SLUG_RE.pattern} (a single safe path segment, no slashes or '..')"
        )
    return repo


def _reject_duplicate_slugs(repos: list[RepoEntry]) -> None:
    if not repos:
        raise GalleryError("manifest must list at least one repo under [[repos]]")
    seen: set[str] = set()
    for repo in repos:
        if repo.slug in seen:
            raise GalleryError(f"duplicate slug '{repo.slug}' — slugs must be unique")
        seen.add(repo.slug)


# --------------------------------------------------------------------------
# Assembly
# --------------------------------------------------------------------------


def build_gallery(
    manifest: GalleryManifest, manifest_dir: Path, output_dir: Path
) -> Path:
    """Assemble the gallery tree under *output_dir*; return the index path.

    Copies each repo's rendered broadsheet into ``<output_dir>/<slug>/``,
    writes the landing ``index.html``, and drops ``.nojekyll`` so Pages
    serves the tree verbatim. Idempotent — re-running overwrites cleanly.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    for repo in manifest.repos:
        _copy_render(repo, manifest_dir, output_dir / repo.slug)

    index_path = output_dir / "index.html"
    index_path.write_text(render_gallery_index(manifest), encoding="utf-8")
    (output_dir / ".nojekyll").touch()
    return index_path


def _copy_render(repo: RepoEntry, manifest_dir: Path, dest: Path) -> None:
    """Copy one repo's render dir into *dest*, raising if it's absent.

    ``render_dir`` is a manifest string, so it is constrained to live inside
    the manifest's own directory — a published gallery should never reach out
    and copy an arbitrary tree from elsewhere on disk.
    """
    source = (manifest_dir / repo.render_dir).resolve()
    if not _is_within(source, manifest_dir.resolve()):
        raise GalleryError(
            f"render_dir for '{repo.slug}' ({repo.render_dir}) escapes the "
            "manifest directory — it must point inside it"
        )
    if not (source / "index.html").exists():
        raise GalleryError(
            f"no rendered broadsheet for '{repo.slug}' at {source} "
            "(run `antiquarian render` for it first)"
        )
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(source, dest)


def _is_within(child: Path, parent: Path) -> bool:
    """True if *child* is *parent* or a descendant of it (both resolved)."""
    return child == parent or parent in child.parents


# --------------------------------------------------------------------------
# Landing page
# --------------------------------------------------------------------------

_PAGE = Template(
    """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>$title</title>
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=EB+Garamond:ital,wght@0,400;0,600;1,400&display=swap" rel="stylesheet">
  <style>$css</style>
</head>
<body>
  <header class="masthead">
    <h1>$title</h1>
    <p class="subtitle">$subtitle</p>
    <div class="rule"></div>
  </header>
  <main class="cards">
$cards
  </main>
  <footer class="colophon">
    <div class="rule"></div>
    <p>Each sheet above was reconstructed from a repository's own git history by
      <strong>Antiquarian</strong> — Telephone played in reverse.</p>
    <p class="cta"><a href="$action_url">Want one for your repo? &rarr;</a></p>
  </footer>
</body>
</html>
"""
)

_CARD = Template(
    """    <article class="card">
      <a class="card-link" href="$slug/index.html">
        <h2>$name</h2>
        <p class="tagline">$tagline</p>
        <span class="view">view broadsheet &rarr;</span>
      </a>
      <a class="src" href="$github_url">$github_url</a>
    </article>"""
)


def render_gallery_index(manifest: GalleryManifest) -> str:
    """Render the self-contained, JS-free gallery landing page HTML."""
    cards = "\n".join(_render_card(repo) for repo in manifest.repos)
    return _PAGE.substitute(
        title=escape(manifest.title),
        subtitle=escape(manifest.subtitle),
        action_url=escape(manifest.action_url, quote=True),
        css=_gallery_css(),
        cards=cards,
    )


def _render_card(repo: RepoEntry) -> str:
    return _CARD.substitute(
        slug=escape(repo.slug, quote=True),
        name=escape(repo.name),
        tagline=escape(repo.tagline),
        github_url=escape(repo.github_url, quote=True),
    )


def _gallery_css() -> str:
    """Inline CSS keyed off the shared broadsheet palette."""
    return f"""
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0; padding: 2.5rem 1.5rem 4rem;
      background: {PALETTE["paper"]};
      color: {PALETTE["ink"]};
      font-family: {_FONT_STACK};
      line-height: 1.5;
    }}
    .masthead, .colophon {{ max-width: 60rem; margin: 0 auto; text-align: center; }}
    .masthead h1 {{
      font-size: clamp(2.2rem, 6vw, 3.6rem); font-weight: 600;
      letter-spacing: 0.02em; margin: 0 0 0.3rem;
    }}
    .subtitle {{ font-style: italic; color: {PALETTE["ink_dim"]}; font-size: 1.15rem; margin: 0; }}
    .rule {{
      height: 0; border-top: 2px solid {PALETTE["ink"]};
      border-bottom: 1px solid {PALETTE["ink"]};
      padding-top: 2px; margin: 1.4rem auto; max-width: 60rem;
    }}
    .cards {{
      max-width: 60rem; margin: 2rem auto 0; display: grid;
      grid-template-columns: repeat(auto-fill, minmax(15rem, 1fr));
      gap: 1.5rem;
    }}
    .card {{
      background: {PALETTE["paper_alt"]};
      border: 1px solid {PALETTE["rule"]};
      padding: 1.25rem 1.25rem 0.9rem; display: flex; flex-direction: column;
    }}
    .card-link {{ text-decoration: none; color: inherit; flex: 1; }}
    .card h2 {{
      margin: 0 0 0.25rem; font-size: 1.5rem; font-weight: 600;
      color: {PALETTE["accent"]};
    }}
    .tagline {{ margin: 0 0 0.9rem; color: {PALETTE["ink_dim"]}; font-style: italic; }}
    .view {{ font-size: 0.95rem; color: {PALETTE["lane"]}; }}
    .src {{
      margin-top: 0.75rem; font-size: 0.78rem; color: {PALETTE["ink_dim"]};
      text-decoration: none; word-break: break-all; opacity: 0.8;
    }}
    .card:hover {{ border-color: {PALETTE["accent"]}; }}
    .colophon {{ margin-top: 3.5rem; color: {PALETTE["ink_dim"]}; font-size: 1.02rem; }}
    .cta a {{
      color: {PALETTE["accent"]}; font-size: 1.3rem; font-weight: 600;
      text-decoration: none;
    }}
    .cta a:hover {{ text-decoration: underline; }}
    """
