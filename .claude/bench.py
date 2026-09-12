#!/usr/bin/env python3
"""Local bench: nothing leaves this machine until it is green.

Written because 340 green tests coexisted with four entry points that died on
import. tests/conftest.py inserts the repo root AND runtime/ AND director/ AND
pipeline/, so the suite runs under the union of every loader shape and no import
spelling can fail there. The suite cannot see this class of bug. This can.

Checks, in order of how much they have actually caught:
  1. LOADER   -- each entry point's real sys.path shape, in a subprocess, with
                 PYTHONPATH unset. Catches the bare-vs-package import regression.
  2. RUNNERS  -- BOTH documented runners, each with and without cv2. Catches the
                 run_all.py shim bug that pytest structurally cannot see.
  3. LINT     -- BOTH scopes. `ruff check .` is 90 where the CI list is 0.
  4. PURITY   -- runtime/ PURE modules import with only stdlib available.
  5. SCRIPTS  -- the short entry points that exit, executed for real.

Side-effect free by construction: no daemon is launched and nothing under data/
is written, so it cannot violate the single-writer invariant.
"""
import os, shutil, subprocess, sys, time
from pathlib import Path

# The bench lives outside the tree it tests, so resolve the repo explicitly:
# argv[1], else git's toplevel from cwd, else cwd.
if len(sys.argv) > 1:
    ROOT = Path(sys.argv[1]).resolve()
else:
    try:
        ROOT = Path(subprocess.run(["git", "rev-parse", "--show-toplevel"],
                                   capture_output=True, text=True,
                                   check=True).stdout.strip())
    except Exception:
        ROOT = Path.cwd()
if not (ROOT / "runtime").is_dir():
    sys.exit(f"bench: {ROOT} is not the living-portraits root")

ENV = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
ENV.update(SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy")
PY = sys.executable
results = []

def run(cmd, env=None, timeout=180, cwd=None):
    return subprocess.run(cmd, cwd=cwd or ROOT, env=env or ENV, timeout=timeout,
                          capture_output=True, text=True)

def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  -- {detail}" if detail and not ok else ""))
    return ok    # so a caller can stop a chain at its first broken link

# 1. LOADER ------------------------------------------------------------------
# Each entry point puts a different directory on sys.path[0]. Replicate each
# shape exactly and import what that entry point imports.
print("\n[1] loader shapes")
SHAPES = [
    ("player.py       (runtime/ on path, bare)", "runtime", "import stage_render, clip_player"),
    ("_preview_graph  (root on path, package)",  ".",       "import runtime.stage_render, runtime.clip_player"),
    ("stage_manager   (director/ on path)",      "director","import stage_manager"),
    # ci.yaml:126 runs `python runtime/video_graph.py build`, so sys.path[0] is
    # runtime/. Import only what that entry point actually loads -- probing a
    # shape nothing exercises produces false failures (runtime/mind.py imports
    # qualified and fails here, but no entry point ever loads it bare).
    ("video_graph     (runtime/ on path)",       "runtime", "import video_graph"),
]
for label, d, stmt in SHAPES:
    # -P: do not prepend cwd. Without it ROOT is always importable and every
    # shape passes -- which is precisely how the original regression was missed.
    code = f"import sys; sys.path.insert(0, {str(ROOT / d)!r}); {stmt}"
    r = run([PY, "-P", "-c", code])
    check(label, r.returncode == 0, (r.stderr.strip().splitlines() or [""])[-1])

# 2. RUNNERS -----------------------------------------------------------------
# The whole point: pytest and run_all.py disagree, and only one is in CI.
print("\n[2] both documented runners, with and without cv2")
stub = ROOT / ".bench_stub"
stub.mkdir(exist_ok=True)
(stub / "cv2.py").write_text('raise ImportError("libGL.so.1: cannot open shared object file")\n')
degraded = dict(ENV, PYTHONPATH=str(stub))
for label, env in (("cv2 present", ENV), ("cv2 absent ", degraded)):
    for runner in (["-m", "pytest", "tests/", "-q"], ["tests/run_all.py"]):
        name = f"{'pytest    ' if 'pytest' in runner else 'run_all.py'}  ({label})"
        r = run([PY, *runner], env=env, timeout=600)
        tail = (r.stdout.strip().splitlines() or [""])[-1][:90]
        check(name, r.returncode == 0, f"exit {r.returncode}: {tail}")

# 3. LINT --------------------------------------------------------------------
print("\n[3] both lint scopes")
CI_LIST = ["runtime", "director", "scripts", "health", "tests", "gallery.py", "player.py"]
for label, args in (("ruff, CI target list", CI_LIST), ("ruff, whole repo   ", ["."])):
    r = run(["uvx", "ruff@0.16.6", "check", *args], timeout=300)
    n = (r.stdout + r.stderr).strip().splitlines()
    check(label, r.returncode == 0, next((l for l in n if "Found" in l), "?"))

# 4. PURITY ------------------------------------------------------------------
# runtime/ is imported by the 10 fps render loop and may never pull a heavy dep.
print("\n[4] runtime/ stdlib purity")
PURE = ["policy", "journal_score", "lived", "graph_provenance", "edge_style",
        "mind", "circadian", "pathfind", "video_graph", "clip_graph"]
probe = f"""
import sys, importlib.abc, importlib.machinery
BANNED = {{"numpy","cv2","yaml","pygame","PIL","torch","imageio","scipy"}}
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in BANNED:
            raise ImportError("PURE set imported a banned dependency: " + name)
        return None
sys.meta_path.insert(0, Block())
# keep the stdlib, drop third-party: purity is about deps, not about the stdlib
sys.path = [p for p in sys.path if "site-packages" not in p and "dist-packages" not in p]
sys.path.insert(0, {str(ROOT)!r})
for m in {PURE!r}:
    importlib.import_module("runtime." + m)
print("ok", len({PURE!r}))
"""
t0 = time.time()
r = run([PY, "-c", probe])
check(f"{len(PURE)} PURE modules, stdlib only", r.returncode == 0,
      (r.stderr.strip().splitlines() or [""])[-1])
print(f"        ({(time.time()-t0)*1000:.0f} ms)")

# 5. SCRIPTS -----------------------------------------------------------------
print("\n[5] short entry points, executed")
for label, cmd in (("capture_demo --selftest", ["runtime/capture_demo.py", "--selftest"]),
                   ("stage_render selftest  ", ["runtime/stage_render.py"])):
    r = run([PY, *cmd], timeout=300)
    check(label, r.returncode == 0, (r.stderr.strip().splitlines() or [""])[-1][:90])

# 6. ONBOARDING --------------------------------------------------------------
# The four commands README/AGENTS.md/CONTRIBUTING.md promise a stranger. Nothing
# else here runs them, and they are the only check that the claim "you do not
# need our art, our GPU, or our hardware" is still true.
#
# They WRITE (data/clips/video_graph.json, data/graph/, ~118 seeded files), and
# this bench's contract is that it writes nothing under data/ -- on hil that
# would be a second writer to a single-writer file while the wall is running.
# So the chain runs in a throwaway WORKTREE at the current HEAD, which has its
# own gitignored data/. Skipped, with a reason, when git cannot make one.
print("\n[6] the onboarding chain a stranger is promised")
import tempfile
wt = Path(tempfile.mkdtemp(prefix="lp-bench-")) / "tree"
made = run(["git", "worktree", "add", "--detach", str(wt), "HEAD"], timeout=120)
if made.returncode != 0:
    print(f"  SKIP  onboarding chain  -- no worktree: "
          f"{(made.stderr.strip().splitlines() or [''])[-1][:70]}")
else:
    try:
        chain = [("seed_demo_media", ["scripts/seed_demo_media.py"]),
                 ("video_graph build", ["runtime/video_graph.py", "build"]),
                 ("export_context_view", ["scripts/export_context_view.py"])]
        out = ""
        for label, cmd in chain:
            r = run([PY, *cmd], timeout=600, cwd=wt)
            out += r.stdout
            if not check(f"chain: {label:20}", r.returncode == 0,
                         (r.stderr.strip().splitlines() or [""])[-1][:90]):
                break
        else:
            # The build prints "walk-safe -> saved" only when no pose is stranded.
            # Its absence is the failure AGENTS.md rule 3 is about.
            check("chain: walk-safe        ", "walk-safe" in out,
                  "build did not report walk-safe")
    finally:
        run(["git", "worktree", "remove", "--force", str(wt)], timeout=120)
        shutil.rmtree(wt.parent, ignore_errors=True)

# ----------------------------------------------------------------------------
shutil.rmtree(stub, ignore_errors=True)
bad = [n for n, ok, _ in results if not ok]
print(f"\n{'='*66}\n{len(results)-len(bad)}/{len(results)} passed")
if bad:
    print("FAILED:"); [print("  -", n) for n in bad]
sys.exit(1 if bad else 0)
