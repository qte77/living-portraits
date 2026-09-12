# Rescued work that could not be pushed as a branch

## 0001-ci-stop-the-viewer-server.patch
Commit 5d7a732, originally branch `fix/e2e-server-teardown`, originally PR #37
(closed unmerged upstream). Fixes the e2e job hanging to the 25-minute timeout:
redirects the backgrounded viewer server's stdout to a file so inherited pipes
close, writes a PID file, and adds an `if: always()` teardown step.

It is NOT on any remote as a branch. A GitHub Codespace token is a GitHub App
user-to-server token with no `workflows` permission, so it is refused on any
push that touches `.github/workflows/`. Pushing it needs a PAT with the
`workflow` scope, from a machine that has one.

To restore:
    git checkout -b fix/e2e-server-teardown origin/main
    git am .claude/rescue/0001-ci-stop-the-viewer-server.patch

Verified still missing from origin/main as of 2026-09-12: that workflow file
contains no `server.pid`, no `server.log`, and no teardown step.
