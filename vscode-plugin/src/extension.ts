// Antiquarian VS Code extension — proof of concept per issue #69.
//
// One command on the palette: "Antiquarian: Show story for this file."
// Reads the pre-existing markdown story from `.antiquarian/stories/`
// in the workspace and opens it in VS Code's built-in markdown preview.
// If no story exists for the current file, opens a Zork-style empty-state
// tab — "It is dark, you are likely to be eaten by a grue."
//
// Read-only by design (the doc-only constraint in #69). The extension
// never invokes the Antiquarian CLI, never writes to `.antiquarian/`.
// Stale data is the user's problem — they decide the regeneration cadence.

import * as vscode from "vscode";

export function activate(context: vscode.ExtensionContext) {
  const showStory = vscode.commands.registerCommand(
    "antiquarian.showStory",
    async () => {
      const editor = vscode.window.activeTextEditor;
      if (!editor) {
        vscode.window.showInformationMessage(
          "Antiquarian: open a file first."
        );
        return;
      }

      const workspaceFolder = vscode.workspace.getWorkspaceFolder(
        editor.document.uri
      );
      if (!workspaceFolder) {
        vscode.window.showWarningMessage(
          "Antiquarian: the active file isn't inside a workspace folder."
        );
        return;
      }

      // Mirror of antiquarian/pipeline.py's safe_name convention:
      // `file_path.replace("/", "__") + ".md"`. VS Code's
      // `asRelativePath` returns forward-slash paths on all platforms,
      // so this matches the CLI's stored filenames exactly.
      const relPath = vscode.workspace.asRelativePath(
        editor.document.uri,
        false
      );
      const storyName = relPath.replace(/\//g, "__") + ".md";
      const storyUri = vscode.Uri.joinPath(
        workspaceFolder.uri,
        ".antiquarian",
        "stories",
        storyName
      );

      // workspace.fs.stat throws on missing files in remote/WSL/Codespaces
      // setups too — node's fs.existsSync wouldn't.
      try {
        await vscode.workspace.fs.stat(storyUri);
      } catch {
        showEmptyState(context, relPath);
        return;
      }

      await vscode.commands.executeCommand(
        "markdown.showPreviewToSide",
        storyUri
      );
    }
  );
  context.subscriptions.push(showStory);
}

function showEmptyState(
  context: vscode.ExtensionContext,
  relPath: string
): void {
  const panel = vscode.window.createWebviewPanel(
    "antiquarianEmpty",
    "Antiquarian — no story",
    vscode.ViewColumn.Beside,
    { enableScripts: false }
  );
  panel.webview.html = emptyStateHtml(relPath);
}

function htmlEscape(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function emptyStateHtml(relPath: string): string {
  // CSP: webview is the most-locked-down VS Code surface. We allow
  // only inline styles (no scripts, no remote loads). The Zork message
  // is static text; no need for anything else.
  const safeRel = htmlEscape(relPath);
  return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline';">
  <title>Antiquarian — no story</title>
  <style>
    html, body {
      margin: 0;
      padding: 0;
      height: 100%;
      background: #0a0a0a;
      color: #e0e0e0;
    }
    body {
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      font-family: ui-monospace, "SF Mono", Menlo, Monaco, Consolas, "Liberation Mono", monospace;
      text-align: center;
      padding: 2rem;
    }
    .grue {
      font-size: 1.6rem;
      line-height: 1.6;
      max-width: 50ch;
      color: #c8c8c8;
    }
    .hint {
      margin-top: 3rem;
      font-size: 0.9rem;
      color: #707070;
      max-width: 60ch;
      line-height: 1.6;
    }
    code {
      color: #d0a050;
    }
  </style>
</head>
<body>
  <div class="grue">It is dark, you are likely to be eaten by a grue.</div>
  <div class="hint">
    No Antiquarian story exists for <code>${safeRel}</code>.<br>
    Generate one with <code>antiquarian story ${safeRel}</code>.
  </div>
</body>
</html>`;
}

export function deactivate(): void {
  // No persistent resources to clean up; everything is owned by
  // context.subscriptions and the panel is GC'd when the user closes it.
}
