# ResearchAssistant agent instructions

## Repository and working branch

- GitHub repository: `AkziumMerlin/researchassistant`.
- Continue development on `codex/mvp-core` unless the user explicitly names
  another branch.
- PR #1 tracks `codex/mvp-core` into `main`.
- In a fresh workspace, obtain the source without authentication:

  ```bash
  git clone --branch codex/mvp-core --single-branch \
    https://github.com/AkziumMerlin/researchassistant.git researchassistant
  ```

## Publishing changes

GitHub CLI authentication is ephemeral in ChatGPT workspaces. Do not require
`gh`, a device-login flow, a PAT, or credentials stored in files or git
remotes. Use the connected GitHub app for remote writes. Local `git` remains
the source for status, diffs, and validation.

For every requested commit and push:

1. Inspect `git status --short` and the complete intended diff. Do not include
   unrelated changes.
2. Run the relevant tests/builds and report any checks that could not run.
3. Read PR #1 immediately before publishing and take its `head_sha` as the
   parent of the new commit. Confirm that the head branch is
   `codex/mvp-core`.
4. Upload each added or modified file with the GitHub app's Git Data API:
   create blobs, then create one tree based on the parent commit's tree.
   Represent deletions with null tree entries. Preserve executable modes.
5. Create exactly one commit whose parent is the observed remote head.
6. Re-read PR #1. If its head changed meanwhile, do not force-update it:
   rebuild the commit on the new head or stop on a real conflict.
7. Fast-forward `codex/mvp-core` to the new commit with `force: false`.
8. Verify the branch head, fetch the resulting commit, and compare the remote
   file contents/tree with the intended local state.

For a single small UTF-8 file, the GitHub Contents API may replace steps 4--7,
provided it targets `codex/mvp-core`, uses the current blob SHA when updating,
and the result is verified.

The remote commit is canonical. After connector-based publication, use a
fresh checkout (or another non-destructive synchronization) before making
further changes so the local branch does not diverge from the connector-created
commit.

Never force-push, write to `main`, publish secrets, or silently fall back to
interactive GitHub authentication.
