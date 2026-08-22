"""The tests that hold Phase 1 together.

`proofpay.core` is a pure library: no I/O, and no wall clock. Both properties
are enforced here rather than promised in a docstring, because either one
silently regressing turns every stored decision into something that cannot be
reproduced.

The import check is an **allowlist**, not a blocklist. A blocklist only catches
the dependencies somebody thought of in advance, and the one that breaks purity
is by definition the one nobody thought of; an allowlist makes every new import
into `core` a deliberate, reviewed decision.
"""

from __future__ import annotations

import ast
import pathlib
import re

CORE = pathlib.Path(__file__).resolve().parents[1] / "proofpay" / "core"

#: Every top-level module `proofpay.core` is permitted to import. Stdlib entries
#: are pure computation only — no `os`, `pathlib`, `io`, `socket`, `urllib`,
#: `subprocess`, `random` (unseeded non-determinism) or `time`. Adding a name
#: here is a decision about what "pure" means, so it should be argued for in the
#: pull request, not slipped in.
ALLOWED_IMPORTS = frozenset(
    {
        # -- the language itself -------------------------------------------
        "__future__",
        "collections",
        "dataclasses",
        "datetime",
        "decimal",
        "enum",
        "functools",
        "itertools",
        "math",
        "re",
        "types",
        "typing",
        "unicodedata",
        "zoneinfo",
        # -- pure computation over bytes, not I/O --------------------------
        "hashlib",  # policy fingerprinting
        "json",     # the fingerprint's canonical serialisation, never a file
        # -- the two third-party libraries this layer is allowed -----------
        "jellyfish",
        "rapidfuzz",
        # -- itself --------------------------------------------------------
        "proofpay",
    }
)

#: Reading the wall clock inside `core` is what makes a decision irreproducible:
#: replaying the same claim against the same ledger a month later must reach the
#: same verdict, so the current instant is always an argument named `now`.
CLOCK = re.compile(r"(datetime\.now|utcnow|time\.time|time\.monotonic|perf_counter)\(")

#: Builtin escape hatches that are calls rather than imports, so the allowlist
#: above cannot see them. The lookbehind keeps this to the *builtins*: `re.compile`
#: is pure, `compile` is not, and `pathlib.Path.open` is already unreachable
#: because `pathlib` is not on the allowlist.
IO_CALLS = re.compile(r"(?<![.\w])(open|input|eval|exec|compile)\s*\(")


def _core_modules() -> list[pathlib.Path]:
    paths = sorted(CORE.rglob("*.py"))
    assert paths, f"no modules found under {CORE} — the check would pass vacuously"
    return paths


def _imported_roots(tree: ast.AST) -> set[str]:
    """Top-level package name of every import in the module."""
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        # `from . import x` has no module name; a relative import can only
        # reach inside `proofpay`, so it is allowed by construction.
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".", 1)[0])
    return roots


def test_core_imports_only_the_allowlist():
    offenders: dict[str, set[str]] = {}
    for path in _core_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        bad = _imported_roots(tree) - ALLOWED_IMPORTS
        if bad:
            offenders[path.name] = bad
    assert not offenders, (
        f"{offenders} — `proofpay.core` is pure. Either move this code above the "
        f"core layer, or argue the import into ALLOWED_IMPORTS deliberately."
    )


def test_core_never_reads_the_clock():
    for path in _core_modules():
        source = path.read_text(encoding="utf-8")
        assert not CLOCK.search(source), f"{path} reads the clock; pass `now` in"


def test_core_never_touches_the_filesystem():
    for path in _core_modules():
        source = path.read_text(encoding="utf-8")
        assert not IO_CALLS.search(source), f"{path} performs I/O or dynamic execution"


def test_core_is_importable_without_the_layers_above_it():
    """`core` must not depend on anything in `proofpay` outside itself.

    Phase 2 puts a database and an HTTP API in `proofpay.api` / `proofpay.adapters`.
    The moment `core` reaches back up into one of those, the dependency runs both
    ways and the pure library stops being independently testable.
    """
    for path in _core_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            module = None
            if isinstance(node, ast.ImportFrom) and node.level == 0:
                module = node.module
            elif isinstance(node, ast.Import):
                module = next(
                    (a.name for a in node.names if a.name.startswith("proofpay")), None
                )
            if module and module.startswith("proofpay") and not module.startswith(
                "proofpay.core"
            ):
                raise AssertionError(f"{path} imports {module}, which sits above core")
