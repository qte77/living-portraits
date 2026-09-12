"""The walker's import set is pure stdlib and must stay import-safe (AGENTS.md rule 2).

The 10fps render loop (`_preview_graph.py`) imports `circadian`, `lived`, `mind`,
`policy` and -- soft, in a try/except -- `edge_style`; `mind` additionally pulls in
`pathfind`. It does NOT import `video_graph`: it reads the built JSON, never the builder
module. A network call, an LLM client, or a heavy dependency introduced into any of
these six modules is a stutter on a physical wall -- everything with a socket or a
model in it belongs in `director/`.

Nothing mechanical enforced this until now: PR #28's history is a boundary crossing
caught only by a human reviewer noticing. This is a lightweight regression guard --
no import-linter, just `ast` on the six files -- that should PASS today and only ever
fail on a FUTURE violation.
"""
import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# The walker's exact import set (AGENTS.md rule 2 / ARCHITECTURE.md's PURE/HEAVY table).
WALKER_MODULES = (
    "circadian",
    "lived",
    "mind",
    "policy",
    "edge_style",
    "pathfind",
)

# What these six modules actually import today (verified with
# `grep -n "^import\|^from" runtime/{circadian,lived,mind,policy,edge_style,pathfind}.py`):
# stdlib only, plus `mind` -> `runtime.pathfind` (a fellow walker-safe sibling).
PERMITTED_RUNTIME_SIBLINGS = set(WALKER_MODULES)

FORBIDDEN_MODULES = {
    "numpy", "cv2", "pygame", "urllib", "requests",
    "director", "pipeline", "video_graph",
}


def _top_level_imports(path):
    """Dotted names a file imports, via `ast` (no import side effects).

    `import a.b` and `from a import b` (any `b`) both yield `"a"` for the forbidden-set
    check; `from runtime import edge_style` yields `"runtime.edge_style"` so a sibling
    pulled in via the package (rather than the walker's bare sys.path import) is still
    checked against PERMITTED_RUNTIME_SIBLINGS.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module == "runtime":
                names.extend("runtime." + alias.name for alias in node.names)
            elif node.module:
                names.append(node.module)
    return names


@pytest.mark.parametrize("modname", WALKER_MODULES)
def test_walker_module_is_pure_stdlib(modname):
    """No numpy/cv2/pygame/urllib/requests, and no reach into director/pipeline/video_graph."""
    path = ROOT / "runtime" / (modname + ".py")
    imports = _top_level_imports(path)

    for name in imports:
        top = name.split(".")[0]
        assert top not in FORBIDDEN_MODULES, (
            "runtime/%s.py imports %r -- forbidden in the walker's pure-stdlib "
            "boundary (AGENTS.md rule 2)" % (modname, name)
        )
        if top == "runtime":
            sibling = name.split(".")[1] if "." in name else None
            assert sibling in PERMITTED_RUNTIME_SIBLINGS, (
                "runtime/%s.py imports %r -- not one of the walker-safe siblings %r"
                % (modname, name, sorted(PERMITTED_RUNTIME_SIBLINGS))
            )
