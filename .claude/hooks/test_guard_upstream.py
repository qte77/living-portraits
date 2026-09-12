#!/usr/bin/env python3
"""Regression matrix for guard-upstream.sh.

The guard has one job -- refuse a push or PR against the UPSTREAM remote, while
leaving the fork alone -- and two ways to fail at it. A false ALLOW costs a push
to a repo we do not own. A false DENY costs less, but it costs the guard's
credibility: it once refused a heredoc whose *body* merely described the rule,
and a guard that forbids documenting itself is a guard someone switches off.

So both directions are asserted here, and the fork/upstream pairs are kept
adjacent on purpose -- each false-deny case has a true-deny twin one line away,
so a change that "fixes" a false positive by weakening the check fails loudly.

    python .claude/hooks/test_guard_upstream.py

Exits 0 on a full pass, 1 on any mismatch. No network, no repo writes; the hook
only reads git config for the current branch's remote.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HOOK = Path(__file__).resolve().parent / "guard-upstream.sh"
ROOT = HOOK.parent.parent.parent

# (label, command, expect_denied)
CASES = [
    # --- the fork is allowed, upstream is not -----------------------------
    ("push to fork",                "git push fork work/all",                          False),
    ("push to origin",              "git push origin main",                            True),
    ("bare push (tracks origin)",   "git push",                                        True),
    ("push chained after &&",       "make test && git push origin main",               True),
    ("gh pr create --repo fork",    "gh pr create --repo qte77/living-portraits --fill", False),
    ("gh pr create, no --repo",     "gh pr create --fill",                             True),

    # --- every other way gh writes something upstream ---------------------
    # A PR was the incident on record; twenty issues went through this door.
    ("gh issue create",             "gh issue create --title x --body y",              True),
    ("gh issue comment",            "gh issue comment 44 --body hi",                   True),
    ("gh pr comment",               "gh pr comment 44 --body hi",                      True),
    ("gh pr review",                "gh pr review 44 --approve",                       True),
    ("gh issue create on the fork", "gh issue create -R qte77/living-portraits -t x -b y", False),
    ("gh api POST to upstream",     "gh api -X POST repos/Immersive-commons/living-portraits/issues", True),
    ("gh api -f to upstream",       "gh api repos/Immersive-commons/living-portraits/issues -f title=x", True),
    # Reading is how you check whether a thing is already fixed. Never blocked.
    ("gh api GET upstream",         "gh api repos/Immersive-commons/living-portraits/pulls", False),
    ("gh issue list upstream",      "gh issue list -R Immersive-commons/living-portraits", False),
    ("gh api POST to the fork",     "gh api -X POST repos/qte77/living-portraits/issues", False),

    # --- text ABOUT the rule is data, not a command -----------------------
    # Each of these mentions the guarded phrase and must pass; the twin above
    # is the same phrase as an actual command and must not.
    ("echo mentioning the phrase",  "echo 'never git push origin main'",               False),
    ("grep for the phrase",         "grep -rn 'git push origin' AGENTS.md",            False),
    ("heredoc body mentions it",    "cat > doc.md <<EOF\nNever do this:\ngit push origin main\nEOF", False),
    ("quoted heredoc body",         "cat > d.md <<'EOF'\ngit push origin main\nEOF",   False),
    ("indented heredoc <<-",        "cat > d.md <<-EOF\n\tgit push origin main\n\tEOF", False),

    # --- a heredoc must not become a hiding place -------------------------
    ("real push AFTER a heredoc",   "cat > d.md <<EOF\nhello\nEOF\ngit push origin main", True),
    ("real push BEFORE a heredoc",  "git push origin main\ncat > d.md <<EOF\nhi\nEOF", True),
    # An unterminated heredoc swallows the rest of the input -- which is what
    # bash does too, so the "push" on the next line is never a command there
    # either. Recorded as a known and harmless limit rather than left implicit.
    ("unterminated heredoc",        "cat > d.md <<EOF\ngit push origin main",          False),

    # --- regression: a heredoc consumer that EXECUTES its body, not one that
    # only reads it. The first version of the cat/tee stripping fix above
    # stripped every heredoc body unconditionally, which made this a real
    # bypass -- `bash <<EOF ... EOF` runs its body as commands, and a push
    # inside sailed through as documentation. Only cat/tee are data sinks;
    # everything else must still be scanned. These two are pinned expecting
    # DENY specifically so a future "fix" of some other false positive can't
    # silently widen the sink list and reopen this. -----------------------
    ("heredoc EXECUTED by bash",    "bash <<'EOF'\ngit push origin main\nEOF",        True),
    ("heredoc EXECUTED by sh",      "sh <<'EOF'\ngit push origin main\nEOF",          True),

    # --- known, accepted, NOT fixable at this layer -----------------------
    # A push assembled inside an interpreted language's own syntax (a python
    # subprocess.run([...]) call, a perl system(), a ruby %x{}) is invisible
    # to a shell command-line scan -- that would require parsing the target
    # language itself. This is unchanged by the heredoc fix (a bare
    # `python3 -c "...subprocess..."` has the identical gap with no heredoc
    # in sight) and is recorded here so it reads as a known limit, not a
    # silent hole discovered later.
    ("push via python heredoc script", "python3 - <<'EOF'\nimport subprocess; subprocess.run(['git','push','origin','main'])\nEOF", False),
    ("push via python -c one-liner",   'python3 -c "import subprocess; subprocess.run([\'git\',\'push\',\'origin\',\'main\'])"', False),

    # --- regression: four confirmed real bypasses, closed 2026-09-11 -------
    # Each was found by a Fable falsifier pass, then INDEPENDENTLY reproduced
    # by hand in a scratch repo before being trusted -- one of the falsifier's
    # own first reproductions (`git push --repo=<url> main`, WITH a trailing
    # branch name) turned out not to work in real git at all; the form below
    # is the one that does. Pinned here so a future "cleanup" of the parser
    # can't quietly reopen any of them.
    ("--repo alone, no positional remote", "git push --repo=https://github.com/Immersive-commons/living-portraits.git", True),
    ("case-varied org in a push URL",      "git push https://github.com/Immersive-Commons/living-portraits.git main", True),
    ("remote add+push, one compound command",
     "git remote add zz https://github.com/Immersive-commons/living-portraits.git && git push zz main", True),
    # The false-positive twin for the remote-add/set-url check: naming the
    # FORK under a new local alias must keep working normally.
    ("remote add naming the fork -- must stay allowed",
     "git remote add zz2 https://github.com/qte77/living-portraits.git && git push zz2 main", False),
]


def denied(command: str, cwd: Path = ROOT) -> bool:
    payload = json.dumps({"tool_input": {"command": command}, "cwd": str(cwd)})
    out = subprocess.run([str(HOOK)], input=payload, capture_output=True,
                         text=True, timeout=20).stdout
    return '"deny"' in out


def run_git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                   timeout=20, check=True)


def test_pushurl_bypass(tmp_path: Path) -> tuple[str, bool, bool]:
    """A remote's FETCH url can be harmless while its PUSH url is upstream --
    `git remote get-url NAME` (no --push) only ever sees the fetch url, so a
    check built on that alone misses the real destination entirely. Needs a
    real configured remote, not just a command string, so it lives outside
    the static CASES table. Confirmed as a real gap by execution, 2026-09-11,
    then closed in `remote_is_forbidden` by also checking `--push`."""
    work = tmp_path / "work"
    work.mkdir()
    run_git(work, "init", "-q")
    run_git(work, "-c", "user.email=t@t", "-c", "user.name=t",
            "commit", "-q", "--allow-empty", "-m", "x")
    run_git(work, "remote", "add", "safe", "https://github.com/qte77/living-portraits.git")
    run_git(work, "remote", "set-url", "--push", "safe",
            "https://github.com/Immersive-commons/living-portraits.git")
    return ("push-url swapped to upstream (fetch url stays the fork)",
            denied("git push safe main", cwd=work), True)


def main() -> int:
    if not HOOK.is_file():
        print(f"guard test: {HOOK} not found")
        return 1
    bad = 0
    for label, command, expect in CASES:
        got = denied(command)
        ok = got == expect
        bad += not ok
        want = "DENY" if expect else "allow"
        print(f"  {'ok  ' if ok else 'FAIL'}  {label:28} -> {want}")

    import tempfile
    with tempfile.TemporaryDirectory(prefix="lp-guard-test-") as td:
        label, got, expect = test_pushurl_bypass(Path(td))
        ok = got == expect
        bad += not ok
        want = "DENY" if expect else "allow"
        print(f"  {'ok  ' if ok else 'FAIL'}  {label:28} -> {want}")

    if bad:
        print(f"\n{bad} of {len(CASES) + 1} FAILED")
        return 1
    print(f"\nall {len(CASES) + 1} pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
