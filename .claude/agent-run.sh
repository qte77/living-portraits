#!/usr/bin/env bash
# agent-run.sh -- run one harness, in its own worktree, against one prompt.
#
# This is the whole "harness router" and it is deliberately forty lines rather
# than a gateway. HarnessRouter solves an N x M problem: many harnesses times
# many product integrations, behind one Responses-shaped API, for a product
# backend spawning throwaway sessions. Here N x M is 1 x 1 -- a person driving
# one or two interactive sessions -- and the thing it does to make sessions
# uniform is exactly wrong for us: a fresh per-session workspace with a
# redirected HOME has no project hooks, no user hooks, and permission prompts
# turned off. Every guardrail this directory installs would be gone, on a
# codebase whose recorded failure mode is confident unverified claims.
#
# What is actually worth having from several harnesses is ONE thing: an author
# and a falsifier that are not the same model. That is this script.
#
#   .claude/agent-run.sh claude   author    prompts/my-task.md
#   .claude/agent-run.sh codex    falsify   prompts/my-claim.md
#
# Each run gets a worktree off fork/main, a copy of .claude/, the bench, and a
# handoff note. Nothing is pushed and nothing is merged; that is a person's job.
#
# NOT the same problem as director/llm.py. That routes ONE inference call at
# show-runtime on the wall host, stdlib-only by contract, and its job is to fall
# back and never block so a character never stops thinking. This routes agentic
# sessions on a dev box, and its job is the opposite: block, and demand
# evidence. They must never share a component.

set -euo pipefail

HARNESS="${1:-}"
ROLE="${2:-author}"
PROMPT="${3:-}"

ROOT=$(git rev-parse --show-toplevel)
BASE="${LP_AGENT_BASE:-fork/main}"

usage() {
  cat <<'USAGE'
usage: .claude/agent-run.sh <harness> <role> <prompt-file>

  harness   claude | codex | aider     (whichever are installed)
  role      author | falsify
  prompt    a file; its text is the task

  author    may edit, in its own worktree, and must declare a file allowlist
            as the first line of the prompt: "allowlist: a.py b.py"
  falsify   read-only. Given a claim, it returns the command that would
            disprove it and that command's output. Never the same harness that
            authored the claim.
USAGE
  exit 2
}

[ -n "$HARNESS" ] && [ -n "$PROMPT" ] || usage
[ -f "$PROMPT" ] || { echo "agent-run: no such prompt file: $PROMPT" >&2; exit 2; }
command -v "$HARNESS" >/dev/null 2>&1 || {
  echo "agent-run: '$HARNESS' is not installed." >&2
  echo "installed harnesses:" >&2
  for h in claude codex aider; do
    command -v "$h" >/dev/null 2>&1 && echo "  $h" >&2
  done
  exit 127
}

STAMP=$(date +%Y%m%d-%H%M%S)
WT="${LP_AGENT_WORKTREES:-$ROOT/../lp-agents}/$HARNESS-$ROLE-$STAMP"
HANDOFF="$WT.handoff.md"

git -C "$ROOT" fetch --quiet --prune "${BASE%%/*}" || true
mkdir -p "$(dirname "$WT")"

if [ "$ROLE" = "falsify" ]; then
  # Read-only: a detached worktree nobody will commit from.
  git -C "$ROOT" worktree add --detach "$WT" "$BASE" >/dev/null
else
  git -C "$ROOT" worktree add -b "agent/$HARNESS-$STAMP" "$WT" "$BASE" >/dev/null
fi

# A fresh worktree has no .claude/, so none of the hooks or deny rules that make
# this safe would be in effect there. Copy them in before anything runs.
cp -r "$ROOT/.claude" "$WT/.claude"

TASK=$(cat "$PROMPT")
PREAMBLE="Read AGENTS.md first; its five rules are not expressible in code and a
test suite will not catch you breaking them. Read .claude/COLLAB.md for the role
you are in. Do not push anywhere and do not open anything upstream.

Your role is: $ROLE."
if [ "$ROLE" = "falsify" ]; then
  PREAMBLE="$PREAMBLE
You may not edit any file. You are given a CLAIM, not an argument for it. Find
the command that would show the claim is FALSE, run it, and report the command
and its exact output. If the claim survives, say which command it survived. Do
not restate the claim approvingly; a verification that reads is not a
verification."
fi

echo "worktree : $WT"
echo "harness  : $HARNESS ($ROLE), base $BASE"
echo

case "$HARNESS" in
  # acceptEdits, never --dangerously-skip-permissions: the deny rules in
  # .claude/settings.json and the upstream guard are the point of this setup.
  claude) (cd "$WT" && claude -p --permission-mode acceptEdits "$PREAMBLE

$TASK") | tee "$HANDOFF" ;;
  codex)  (cd "$WT" && codex exec "$PREAMBLE

$TASK") | tee "$HANDOFF" ;;
  aider)  printf '%s\n\n%s\n' "$PREAMBLE" "$TASK" > "$WT/.agent-task.md"
          (cd "$WT" && aider --read AGENTS.md --message-file .agent-task.md) | tee "$HANDOFF" ;;
  *)      echo "agent-run: unknown harness '$HARNESS'" >&2; exit 2 ;;
esac

echo
echo "=== bench, in the worktree ===" | tee -a "$HANDOFF"
(cd "$WT" && python "$WT/.claude/bench.py" "$WT") 2>&1 | tee -a "$HANDOFF" || true

echo
echo "handoff  : $HANDOFF"
echo "diff     : git -C $WT diff --stat $BASE"
echo "when done: git -C $ROOT worktree remove $WT"
