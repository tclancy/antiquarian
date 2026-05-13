# Notes — Warnings, Future Ideas, Candidate Signals

## Warning: AI-written repositories

Codebases that are predominantly or entirely AI-authored have messaging properties that may break naive significance detection. Properties to watch for:

- **Verbosity.** AI-generated commit messages tend to be longer and more uniformly structured than human ones. A median message length of "60 words" may say more about the agent than the repo.
- **Confidence drift.** Agents tend toward overconfidence early, then swing to apologetic over-explanation after problems. Both extremes mask actual significance.
- **Suspiciously consistent word-to-code ratio.** Humans vary wildly in commit-message length relative to diff size. Agents don't, much. Uniform ratios are themselves a signal that something other than human authorship is going on.
- **Significance shape may differ.** "Longer than baseline" loses meaning when the baseline is artificially elevated. Detectors that lean purely on message length will need fallback strategies in AI-authored corpora: diff-shape signals, reverts of prior AI work, sudden departures from the agent's own established pattern, references to context the agent couldn't have known.

Not a v1 blocker but on the radar when evaluating detectors against any modern codebase. The `dispatch-bot[bot]` commits in `itguy` are a small-scale, currently-running example.

## Candidate signals (future)

Some are in flight, some are parked. The "tracked at" column says where the work actually lives.

| Idea | Where it lives |
|------|----------------|
| **CHANGELOG handling** — skip/roll-up changelog-only commits; CHANGELOG presence as a structural signal ("real work begins") | Candidate signal for #3; needs new mining-behavior issue |
| **Casting-about → real-work-begins** transition detection — the first N commits are often `mise en place`, not the work itself | Candidate signal for #3 |
| **Tone analysis on commit messages** (NLTK VADER or similar) | Candidate signal for #3 |
| **Conventional commits (`fix`/`chore`/`feat`)** | Profiler type in #2 |
| **Requirements files as top-level early-pass targets** — their evolution sets up the larger story | From #44 |
| **Skip generic SVN-import boilerplate** — every file shouldn't start with "imported from SVN by Bitbucket" | From #44 |
| **`__init__.py` files** — ignore entirely except when meaningful | From #44 |
| **Internationalization** | Punted — most coding is in English |
| **VS Code plugin** — read-only, looks for `.antiquarian/` and annotates files on demand | Future, no issue yet |

## Test repositories to try

Picked for OSS history Tom doesn't have in his head; tracked in **#7** for `antiquarian survey` work:

- BetterBlue (in scope; has known hang trigger — see #34)
- comictagger (in scope; survey clean)
- itguy (in scope; small but rich)
- courtlistener (waiting in line as the scale test — 22k commits, 547-commit files)
- iSponsorBlockTV (future)

Tom's reference repos for long-history dogfooding:
- GroundEnergy (Tom can hold this end-to-end; needs to retrieve archive)
- `/mnt/samsungusb/work/alliance/` (long-running codebase)
- Rhumbix or others on old laptops

## Dispatch bot status

**On hold for unsupervised PR opening** (set 2026-05-13). Exception: clean up the two open bot PRs (**#56** Dramatis Personae, **#58** Statistical SC detector). Subagents dispatched inside interactive sessions are still allowed — the pause is specifically for unsupervised PR-opening. The project's frontmatter in the Obsidian index doc is the source of truth on this status.

## On `git blame`

> What is the opposite of `git blame`? Something like `git explain`? I get why it's `git blame` — it's mildly funny in the way I always call the second object in an event/action model "victim," but it's also because Linus is an asshole and forgets (or worse, knows) words matter. — Tom

`git blame` makes all the sense in the world because we often reach for it to answer "what asshole did this?" — but that attitude should be something Antiquarian actively avoids. "Assume good intentions" is worth baking into the DNA. Almost all codebases exist to improve life, and anyone willing to work on them is a good actor — with room for time pressure, real life, and incomplete information.

## On `# TODO` comments

> I don't want my experience to color design decisions too much but I think `#TODO` and similar comments are so valuable. I call `#TODO`s "Messages from a better version of myself." Often these are notes to what I should have / would have done if I had infinite time. They're not so much a message to come upgrade this thing in the future as they are an explanation or admission I too know what should have been done. We just didn't do it. — Tom

This is why TODO aging carries disproportionate weight in the narrative output. A `# FIXME` that has survived a decade is often the most honest line in a file.
