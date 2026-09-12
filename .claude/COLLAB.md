# Working this repo with more than one agent

`.claude/` is our tooling. It is gitignored on `origin/main` by the maintainer's
own policy (`.gitignore:20` there), so **nothing in this directory ever goes
upstream**. It exists to make our side trustworthy enough to be worth his
attention.

`AGENTS.md` in the repo root is the contract about the *project* and it is his.
This file is the contract about *us*.

---

## Why more than one agent, and when it is worse

Measured over the eight branches that fed `work/all`: 80 files touched, 16 of
them by more than one branch. `CHANGELOG.md` alone was touched by five, and 27
of 28 conflicting PR pairs came from that one file. The integration branch built
from those merges carries a regression `main` does not have, and its one unique
commit deleted the comment written specifically to warn against that regression.

So: **parallel authoring on this repo is net negative.** One maintainer, seven
commits in two months, one reviewer. Two agents writing code at once produce
merge conflicts, not throughput.

The division that pays is by *kind of work*, not by topic:

| Role | Who | May touch | Output |
|---|---|---|---|
| **Author** | one agent, one branch, one worktree | an explicit file allowlist, declared before the first edit | a branch |
| **Falsifier** | a **different vendor** than the author | nothing — read-only | the command that would disprove the claim, and its stdout |
| **Integrator** | one agent, never an author in the same session | the shared docs (`CHANGELOG.md`, `AGENTS.md`, `ARCHITECTURE.md`, `README.md`) and merges | a merged branch, bench green after each merge |

The falsifier is the only real reason to run more than one harness. A same-model
self-review re-reads its own premise and agrees with it; that is how five
conclusions with false premises shipped as findings. Give the falsifier the
*claim* and the repo, and withhold the author's reasoning.

**This applies inside one Claude Code session too, not only across harnesses** —
spawn a Fable-model subagent (`Agent` with `model: "fable"`) as the falsifier
even when there is no second harness in play. Confirmed necessary, not just
good practice: on 2026-09-11 a Fable falsifier pass found a live, exploitable
`git push` bypass — against a credential independently confirmed to have write
access to the real upstream repo — in a guard hook its own author (same
session, one day earlier) had just finished covering with a 24-case regression
suite that passed clean. The suite tested what the author had thought of.
Fable found what the author hadn't.

**When to spend it — not on every edit, that is waste, not rigor:**
- Always, before anything reaches upstream (`.claude/pr-gate.py` question 3).
- Any change to a security or credential boundary — a guard hook, a permission
  rule, anything gating what reaches a repo we don't own.
- Any change touching one of AGENTS.md's five non-negotiable invariants
  (single-writer files, the walker's stdlib-only import set, walk-safety,
  absence-is-a-skip, detection-never-repairs) — these are exactly the rules a
  test suite cannot catch you breaking, which is the same blind spot a
  same-model self-review has.
- Mid-implementation, not just pre-flight, for anything in the categories
  above: a falsifier pass on a half-built fix catches a wrong premise before
  the rest of the work is built on top of it, which is cheaper than catching it
  after. Do not wait for "done" to ask whether "done" is right.
- Skip it for routine edits, docs, and anything a mechanical check (the bench,
  the regression suite, walk-safety validation) already covers well — a Fable
  pass on every commit trains nobody to trust their own first-pass work and
  spends the user's attention on churn instead of findings.

## Isolation

Worktrees, one per agent: `git worktree add ../lp-<role> -b <branch> fork/main`.

Worktrees are not what went wrong — there was only ever one worktree. What went
wrong was shared file ownership and a script that resolved semantic conflicts by
stripping markers. So the rules that matter are:

1. **Declare the file allowlist before the first edit.** If two agents are in
   flight, their allowlists must not intersect. `CHANGELOG.md` is never on an
   author's allowlist.
2. **Never resolve a conflict automatically.** No `-X ours`, no `-X theirs`, no
   `--strategy=union`, no script that removes conflict markers. If a merge
   conflicts, an integrator reads both sides and writes the result.
3. **Two branches in flight, total.** Not per agent.

`.claude/` does not exist in a fresh worktree, so its hooks do not run there.
Install the guard at user level (`~/.claude/settings.json`) if you work in
worktrees, or accept that a worktree is unguarded and never push from one.

## The shared gate

Nothing an agent did is visible to another agent until all of:

- the branch is rebased onto `fork/main` **fetched this session**;
- `python .claude/bench.py` is green **in that worktree** — not on the branch as
  the author left it;
- `git diff --stat` shows only allowlisted files;
- a handoff note exists carrying every falsifier command and its output.

`.claude/bench.py` is the gate because the test suite structurally cannot be:
`tests/conftest.py:43-51` inserts the repo root *and* `runtime/` *and*
`director/` *and* `pipeline/`, so the suite runs under the union of every loader
shape and no import spelling can fail there. 340 tests passed on a tree with
three dead entry points. The bench runs each entry point's real path shape in a
subprocess with `-P`.

## Pointing each harness at AGENTS.md

Claude Code does not read `AGENTS.md`; the others mostly do.

```bash
ln -s AGENTS.md CLAUDE.md
echo CLAUDE.md >> .git/info/exclude     # never tracked: release.py would delete it
```

`.git/info/exclude` rather than `.gitignore` because the shim is tool-specific
and the maintainer publishes a subset of this tree — a tracked `CLAUDE.md` is
either deleted by `scripts/release.py` sync or lands upstream as our clutter.
Aider: `read: AGENTS.md` in `.aider.conf.yml`. Cursor: a rule that imports it.
Codex reads `AGENTS.md` natively.

---

# The upstream gate

The mechanical half is `.claude/hooks/guard-upstream.sh`: it refuses a push, a
PR, an issue, a comment, or a `gh api` write against the upstream remote it
recognises as such, and lets the fork through. **It is a trip-wire against an
honest mistake, not a security boundary** — confirmed on 2026-09-11, when the
credential live in this environment turned out to have real write access to
the actual upstream repo (`gh api repos/Immersive-commons/living-portraits
--jq .permissions` → `push: true`), and a falsifier pass found working ways
past the hook's text-scanning regardless (several patched the same day; a
class of them — an alias, an interpreted-language subprocess call, a bare
`curl` with the same token — cannot be closed at this layer at all). The real
boundary, where one exists, is the credential's own scope, not this script.
See the hook's own header for the current, honest account of what it can and
cannot promise. It cannot tell you that a technically permitted contribution
is still the wrong move, either way. This is that half.

**Run `python .claude/pr-gate.py` before proposing anything upstream.** It checks
what a script can check and prints the rest as questions you must answer with
evidence.

## The gate is closed by default

The scarce resource is the maintainer's attention, not his goodwill. He answers
by number within days, test-merges, runs his own seven-check bench, and retracts
his own claims in public. That is a maintainer worth not wasting.

**This rule covers every upstream write, not just a PR** — a pull request, an
issue, a feature request (GitHub has no separate type for one; it is filed as an
issue), or a comment on any of those. The user has stated this twice now, the
second time to strongly clarify it. The bar is not "the hook didn't block it" —
the guard is a floor, not a green light. The bar is:

> **Open nothing upstream unless we are 100% sure of the content's quality.**

Not "probably fine." Not "the mechanical checks passed." If there is a genuine
doubt about correctness, completeness, or whether the framing survives scrutiny,
the answer is to keep it local and resolve the doubt — never to open it and see
what happens. A wrong or sloppy issue costs the maintainer's attention exactly
like a wrong PR does; the mechanical guard cannot tell the difference between a
carefully-checked report and a guess, and it was never meant to.

**A PR needs a trigger from him, quoted in the body.** Not an inference that he
would probably want it. An issue where he said "PR it", or a comment on an open
question of ours that he answered. The one exception is a defect in *merged*
code that breaks the production host — and even that goes first as a comment
carrying the reproduction, not as a PR, and even that is still held to the same
100% bar: an unverified guess about a defect is not a report, it is noise with a
production host's name attached.

## What a PR must carry

1. **The trigger, quoted verbatim**, with a link.
2. **Zero other open PRs from us.** One at a time.
3. **Bench green on a test-merge onto `origin/main` fetched within the hour**,
   with the output pasted. Green on the branch alone does not count — that is
   the mistake that shipped an import regression through 340 passing tests.
4. **Every sentence containing a number, a ref, or the words "every", "never",
   or "since" carries the command that produced it.** This is the rule that
   would have caught all five false-premise findings. A claim you did not run is
   a claim you do not make.
5. **Diff hygiene.** No `CHANGELOG.md` — he has removed it from four of ours. No
   citation churn unless the change actually moved the line.
6. **One thing.** If the body wants a table of findings, it is an issue.
7. **Its cost to him, stated.** Every merge costs a port into the private tree
   (`scripts/release.py` sync overwrites the public copy). Public-side-only
   plumbing costs him that port for zero change on the wall.

## Automatic disqualifiers

- Opened mid-turn without the user saying so, in this session, in words.
- A fix that works but cannot be explained. That is an issue with the controlled
  comparison, not a PR.
- Anything found while auditing our own mess.
- Anything adding a writer to a file under `data/` — AGENTS.md rule 1 makes that
  a design conversation, not a PR.
- Anything in `pipeline/`. It spends money and cannot be tested here.
- Any claim that was not falsified by someone other than its author.

## Categories that never go upstream at all

- **Our agent tooling** — `.claude/`, the bench, the hooks, the editor shims. He
  excludes them by policy.
- **CHANGELOG entries.**
- **Lint and config churn.** Two such PRs were already rejected, and CodeFactor
  counts almost nothing our linter changed.
- **Speculative fixes for hazards nobody has reached.** The import regression
  came from exactly this.
- **CI changes unless he asks.** Not because CI cannot run there — `ci.yaml` has
  been on `origin/main` since PR #28 and runs green — but because he then owns
  the risk and the port.
