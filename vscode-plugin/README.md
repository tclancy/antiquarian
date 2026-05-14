# Antiquarian VS Code extension (proof of concept)

Proof-of-concept VS Code extension per [#69](https://github.com/tclancy/antiquarian/issues/69). Adds one command:

> **Antiquarian: Show story for this file**

When invoked from any file in a workspace, looks for a pre-existing markdown story at `<workspace>/.antiquarian/stories/<safe-name>.md` (the convention the CLI's `antiquarian story` command writes to) and opens it in VS Code's built-in markdown preview.

If no story exists for the file, opens a Zork-style empty-state tab.

## Read-only by design

The extension **never** invokes the Antiquarian CLI, **never** writes anywhere, and **never** generates new stories on the fly. Stale data is the user's problem — they decide when to regenerate via `antiquarian story` / `antiquarian survey`. This is per the issue's hard constraint.

## Dev workflow

```bash
cd vscode-plugin
npm install                  # install @types/vscode + typescript
npm run compile              # tsc → out/extension.js
```

Then in VS Code:

1. Open the `vscode-plugin/` folder as the workspace.
2. Press **F5** — launches a *new* VS Code window ("Extension Development Host") with this extension loaded.
3. In that window, open any file inside a repo that has an `.antiquarian/` folder.
4. **Cmd-Shift-P → "Antiquarian: Show story for this file"**.

## Packaging a `.vsix`

For sharing or installing locally without going through `npm` each time:

```bash
npm install -g @vscode/vsce      # one-time
vsce package                     # produces antiquarian-vscode-0.0.1.vsix

# install on your real VS Code (outside the dev host):
code --install-extension antiquarian-vscode-0.0.1.vsix
```

## What it does NOT do (yet)

Per #69, the POC is deliberately tiny. Out of scope:

- CodeLens at the top of the file (Tom hates CodeLens — palette only).
- Hover tooltips on lines.
- A sidebar tree view of stories.
- Custom typography matching the broadsheet (relies on VS Code's built-in markdown styling).
- Staleness banner ("this story is N days old, the file was edited M times since"). The user decides regen cadence.
- Calling out to the Antiquarian CLI to generate stories on demand.
- The MCP-server alternative discussed in #69. That's a separate research direction.

## Where to file feedback

Issue [#69](https://github.com/tclancy/antiquarian/issues/69). The POC's whole job is to be looked at and either earn its way into a real product or get scrapped — like the viz playground that became the broadsheet.
