# ResearchAssistant agent instructions

## Repository and branches

- GitHub repository: `AkziumMerlin/researchassistant`.
- Treat `main` as the protected integration branch.
- Start each development cycle from the current `main` on a descriptive namespaced branch such as
  `agent/...`, `feature/...`, `fix/...`, or a user-specified branch.
- Never force-push or write implementation commits directly to `main`.

## Publishing changes

GitHub CLI authentication may be ephemeral in agent workspaces. Prefer ordinary local Git when an
authenticated checkout is available. When it is not, use the connected GitHub app and Git Data API
without storing tokens or credentials in files or remotes.

For every requested publish operation:

1. Inspect the complete intended diff and exclude unrelated user changes.
2. Run the relevant Python tests, Ruff checks, frontend build, and wheel smoke tests.
3. Read the remote branch head immediately before constructing the commit.
4. Create commits with the observed remote head as parent and fast-forward with `force: false`.
5. Verify the resulting remote tree and CI state.
6. Open a draft PR to `main` unless the user explicitly requests another review state.

For connector-only publication, prefer one Git tree and one functional commit. Temporary bootstrap
files or workflows must be restricted to the development branch, must not contain credentials, and
must delete themselves from the resulting functional tree.

## Safety and reproducibility

- Preserve executable modes and generated UI assets.
- Do not publish secrets, local environment files, datasets, run artifacts, or caches.
- Keep the browser server loopback-only and preserve its path and process-execution boundaries.
- Document user-facing CLI or UI changes and add regression tests for new behavior.
