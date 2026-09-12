#!/usr/bin/env python3
"""pr-gate.py -- run before proposing anything upstream.

The hook (.claude/hooks/guard-upstream.sh) is the mechanical half of the
no-upstream rule: it refuses the command. This is the judgement half, and it is
deliberately only PART mechanical. Six things a script can check are checked; the
rest print as questions that must be answered with evidence, because the failure
this is built against was never a missing check -- it was a conclusion formed
first and a check chosen afterwards that it would pass.

    python .claude/pr-gate.py                # check the current branch
    python .claude/pr-gate.py --branch NAME

Exit 0 only when every mechanical check passes. Exit 0 is NOT permission: the
questions at the bottom are the gate, and `.claude/COLLAB.md` is what they mean.

Reads only. Fetches origin if the network allows, and writes nothing anywhere.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UPSTREAM = "origin"
FORK = "fork"

# Files the maintainer has removed from our PRs, or that are ours alone. A diff
# touching one of these is not automatically wrong -- it is automatically a
# conversation, which is why this prints rather than decides.
NEVER_UPSTREAM = ("CHANGELOG.md", ".claude/", "CLAUDE.md", ".aider.conf.yml")

results: list[tuple[str, bool, str]] = []


def git(*args: str, check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                          text=True, timeout=120, check=check)


def record(name: str, ok: bool, detail: str = "") -> bool:
    results.append((name, ok, detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n          {detail}" if detail else ""))
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--branch", default=None, help="branch to gate (default: current)")
    args = ap.parse_args()

    branch = args.branch or git("symbolic-ref", "--short", "HEAD").stdout.strip()
    print(f"\nupstream gate -- {branch}\n" + "=" * 66)

    # 1. Freshness. A gate run against a stale ref is the mistake that reported a
    # deleted branch as pushed and a missing ci.yaml as still missing.
    print("\n[1] is the base current")
    fetched = git("fetch", "--quiet", "--prune", UPSTREAM)
    record(f"fetch {UPSTREAM}", fetched.returncode == 0,
           "" if fetched.returncode == 0 else "no network -- every check below is against a stale ref")
    behind = git("rev-list", "--count", f"{branch}..{UPSTREAM}/main").stdout.strip() or "?"
    record(f"{branch} is not behind {UPSTREAM}/main", behind == "0",
           "" if behind == "0" else f"{behind} commits behind -- rebase before gating")

    # 2. One at a time. Two open PRs is two things asking for the same attention.
    print("\n[2] how much of his attention is already spent")
    gh = subprocess.run(
        ["gh", "pr", "list", "--repo", "Immersive-commons/living-portraits",
         "--author", "@me", "--state", "open", "--json", "number,title"],
        cwd=ROOT, capture_output=True, text=True, timeout=60)
    if gh.returncode != 0:
        record("open PRs from us", False, "gh could not answer -- check by hand, do not assume zero")
    else:
        import json
        open_prs = json.loads(gh.stdout or "[]")
        record("no other open PR from us", not open_prs,
               "; ".join(f"#{p['number']} {p['title']}" for p in open_prs))

    # 3. Diff hygiene.
    print("\n[3] what the diff touches")
    base = f"{UPSTREAM}/main"
    files = [f for f in git("diff", "--name-only", f"{base}...{branch}").stdout.splitlines() if f]
    record("the diff is not empty", bool(files))
    flagged = [f for f in files if any(f.startswith(n) or f == n for n in NEVER_UPSTREAM)]
    record("nothing that never goes upstream", not flagged, ", ".join(flagged))
    record("one thing (<= 12 files)", len(files) <= 12,
           f"{len(files)} files -- if this needs a table to explain, it is an issue")

    # 4. The bench, on a TEST-MERGE, in a throwaway worktree. Green on the branch
    # is what 340 passing tests looked like on a tree with three dead entry points.
    print("\n[4] bench on a test-merge onto " + base)
    import tempfile
    wt = Path(tempfile.mkdtemp(prefix="lp-gate-")) / "tree"
    made = git("worktree", "add", "--detach", str(wt), base)
    if made.returncode != 0:
        record("test-merge worktree", False, made.stderr.strip().splitlines()[-1:][0] if made.stderr else "")
    else:
        try:
            merged = subprocess.run(["git", "merge", "--no-edit", "--no-ff", branch],
                                    cwd=wt, capture_output=True, text=True, timeout=120)
            if not record("merges onto " + base + " without conflict", merged.returncode == 0,
                          (merged.stdout + merged.stderr).strip().splitlines()[-1:][0] if merged.returncode else ""):
                pass
            else:
                bench = subprocess.run([sys.executable, str(ROOT / ".claude" / "bench.py"), str(wt)],
                                       cwd=wt, capture_output=True, text=True, timeout=1800)
                tail = [ln for ln in bench.stdout.splitlines() if "passed" in ln]
                record("bench green on the merged tree", bench.returncode == 0,
                       (tail[-1] if tail else "").strip() + "  -- rerun in the worktree to see which")
        finally:
            git("worktree", "remove", "--force", str(wt))
            __import__("shutil").rmtree(wt.parent, ignore_errors=True)

    # ---------------------------------------------------------------- verdict
    bad = [n for n, ok, _ in results if not ok]
    print("\n" + "=" * 66)
    print(f"{len(results) - len(bad)}/{len(results)} mechanical checks passed")
    for n in bad:
        print(f"  - {n}")

    print("""
The mechanical half is the easy half. None of the following is checkable, and
each one is a way a PR has actually gone wrong here:

  1. Which words of HIS are the trigger for this? Quote them, with a link.
     No quote -> the gate is closed. "He would probably want this" is not a
     trigger; it is the reasoning that opened a PR mid-turn after the problem
     had been named.
  2. Every sentence in the body with a number, a ref, or "every"/"never"/
     "since" -- what command produced it, and did you run that command in THIS
     session? Five findings shipped with false premises because the answer was
     "I read it".
  3. Who other than the author tried to falsify the central claim, and with
     what command? An author agreeing with itself is not review -- run it past
     a DIFFERENT model (an Agent call with model: "fable" is one), not the one
     that wrote the change re-reading its own premise. This is not decoration:
     on 2026-09-11 a falsifier-plus-Fable pass found a live, exploitable bug
     (a real git-push bypass, confirmed against a credential that actually has
     write access to upstream) in a hook its own author had just finished
     covering with a 24-case PASSING regression suite the day before.
  4. Can you explain WHY the fix works, not only that it does? If not, it is an
     issue with the controlled comparison, not a PR.
  5. What does merging it cost him? Every merge is a port into a private tree.
     Public-side-only plumbing costs that port for nothing visible on the wall.
  6. Did the user say, in words, in this session, to open it?
""")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
