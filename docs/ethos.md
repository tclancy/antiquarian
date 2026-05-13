# Ethos

The project's design lens. Everything we build passes through these.

## Origin

The idea comes out of Tom's time at Box, working on a codebase that was 14 years old at the time. There were `TODO` comments staging "right away" refactors that were a decade old — by then it was unlikely anyone in the codebase even knew someone who knew the person who wrote them.

Large codebases accumulate **why-debt**: the reasoning behind decisions evaporates while the code persists. `git blame` tells you who and when, but not why. The question is whether we can build a tool that extracts or reconstructs that reasoning, ideally running locally.

The military has the role of *historian* — not to document the *what*, but the *why*, so the same mistakes don't get made again. Antiquarian is that role for a codebase.

## The Telephone game in reverse

> What we are working on here is a version of the old party game Telephone: initially software development was the process of turning ill-defined requirements into code, now we are trying to divine the original requirements from the code. — Tom

Software development is a forward Telephone game:

```
Requirements → Conversations → Specs → Tickets → PRs → Commits → Code
```

Each hop loses signal. Constraints get compressed into messages. Decisions get rolled up into commit titles. Context evaporates into deleted Slack threads, ex-employees' notebooks, retired email accounts.

Antiquarian runs Telephone backwards. Given the surviving artifacts — commits, PR descriptions, code, TODOs — reconstruct as much of the original signal as possible. Some loss is permanent and we should say so rather than confabulate. Some loss is recoverable through triangulation across many corrupted relays. Some regions of a codebase will be more recoverable than others, and **where the channel is most lossy is itself worth surfacing**.

### Implications

- **Confidence is a first-class output.** The narrative engine should be willing to say "this appears to have been," "the evidence suggests," "the channel is too lossy here." Hallucinated certainty is worse than acknowledged ignorance.
- **Triangulation beats single-source.** Commit message + PR body + co-changed test + nearby TODO is stronger evidence than any one alone. Detectors and synthesis should explicitly combine sources rather than treating commit messages as ground truth.
- **Lossy regions are themselves signal.** "We can't recover the why here" is a valid narrative element. Don't paper over it.
- **The forward direction informs the reverse.** Understanding how the original signal was *compressed* — the team's commit style, PR culture, ticketing habits — helps us decompress more accurately. This is half the argument for the messaging-pattern profilers: knowing the forward channel's compression scheme is half the game.

## Every layer is approximation

> All messaging about coding work is approximate; we even lie to ourselves (`# FIXME`). We want to find sources of truth. — Tom

The Telephone framing assumes a lossy *channel*. The deeper truth is that the *source signal itself* was already approximate before any compression happened. Software is built by humans who:

- **Lie to each other about work.** Agile artifacts — standups, sprints, story points, retros — are agreed-upon fictions optimizing for predictability and social cohesion over accuracy. The way we choose to lie to each other about work.
- **Lie to themselves about future intentions.** `# FIXME`, `# TODO`, `// will refactor later` — promises made by present-self that future-self knows will probably never be kept.
- **Optimize commit messages for many things other than honest summary.** Performance reviews, clarity for reviewers, perceived competence, time pressure, social vibes.
- **Forget what they actually meant** within days, never mind years.

### Implications

- **Don't treat any single artifact as ground truth.** Even an explicit `# DECISION: chose X because Y` comment is one moment's confidence under specific pressures.
- **Treat "sources of truth" as a sliding scale.** Code that runs in production is more trustworthy than the commit message that introduced it; the commit message is more trustworthy than the PR title; the PR title is more trustworthy than the ticket; the ticket is more trustworthy than the standup transcript.
- **The most reliable signals are behavioral, not declarative.** Commit timing, file co-change, who fixes the bugs introduced by whom, what TODOs survive across decades — these are harder to fake than commit messages, and often more informative.
- **`# FIXME` and `# TODO` are admissions, not notes.** They mark where present-self admitted future-self would inherit a problem. That admission is often the only un-spun signal in the surrounding code. This is why TODO aging carries disproportionate weight.
- **Triangulation is the operational answer.** No single relay is trustworthy, so combine relays — commit + PR + tests + TODOs + co-change patterns.

## The Gauguin Question

The three things we care about answering for any non-trivial codebase:

- **Where Do We Come From?** History of the codebase.
- **What Are We?** Decisions made.
- **Where Are We Going?** Don't break the conventions of the two above unless you know a good reason to do so — Chesterton's Fence.

## Voice rules

The narrative output (and our own commits, PRs, and reviews) follow these:

- **Banned vocabulary:** `blame`, `fault`, `culprit`, `should have`, `mistake`.
- **Required voice:** `introduced`, `wrote`, `chose`, `appears to have`, `the evidence suggests`.
- **Hemingway, not LinkedIn.** No "exciting journey," no "fixed dumb bug" energy.
- **Default to kind on people; tell the truth anyway.** Most codebases exist to improve life. Anyone willing to work on one is a good actor — with room for time pressure, real life, and incomplete information.
- **Confidence is part of the output.** Say what you don't know.

Tom on the project's name: the opposite of `git blame` ought to be something like `git explain`. `git blame` is mildly funny in the way "victim" is mildly funny as a term for the second object in an event/action model, but it also shapes attitude. Antiquarian assumes good intentions by design.

## Significant Change (SC)

The unit of meaning we're trying to surface.

> A Significant Change, or SC, is one or more commits of code that either represent a larger than normal amount of work *or* something that deviates from the typical message pattern in some way. We should always consider version marker changes (major, minor, bugfix) as potential significant changes even if the messaging does not deviate, and offer some level of summary at each level, though the bugfix level should just be whatever the fix was.

Note: we say "Significant Change" rather than "significant commit" intentionally. Codebases vary on what an atomic unit looks like — single commit, squashed set, pull request. SCs span 1-to-many commits depending on the repo's style.

## Why AGPL

Open-source product ambitions; the codebase is the moat as much as the code is. AGPL keeps derivatives open. If commercial use ever shapes up we'll reconsider.
