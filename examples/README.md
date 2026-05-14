# Examples

Templates, not enforced infrastructure. Each file is a snippet to copy into your own repo.

## What's here

| File | Where it goes | What it does |
|------|---------------|--------------|
| [`pre-commit-antiquarian.yaml`](pre-commit-antiquarian.yaml) | Append to `.pre-commit-config.yaml` | Pre-push hook: regenerates `antiquarian story` for every changed file before allowing the push. Eager refresh, **expensive** (each file = one `claude -p` call). |
| [`github-actions-antiquarian.yml`](github-actions-antiquarian.yml) | Drop at `.github/workflows/antiquarian.yml` | On every push to `main`, re-renders the broadsheet from your committed cache + stories and publishes to `gh-pages`. Does **not** regenerate stories (waiting on a future API-key backend). |

## Cost reality

Story synthesis uses `claude -p`, your local Claude subscription session. That's why:

- The pre-push hook can take minutes for multi-file commits.
- The GitHub Actions workflow does **not** call `claude -p` — CI runners don't have your Claude session and there's no API-key backend yet.

Once a pluggable API-key backend lands ([#75 thread](https://github.com/tclancy/antiquarian/issues/75)), the workflow's commented-out story-regen step becomes uncommentable.

## What goes public

`antiquarian ghpublish` pushes the rendered broadsheet to a public `gh-pages` branch. That broadsheet references commit messages, author emails, and PR bodies that fed the stories. If any of that is sensitive in your repo, don't use the GitHub Actions example. The CLI has no redaction step today.
