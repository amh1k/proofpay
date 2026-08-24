"""Architecture test: enforce that vendor SDKs are isolated to proofpay/extraction/.

Runs in CI to prevent accidental imports of cloud SDKs (dashscope, openai)
in core domain logic or API layers outside extraction.
"""

import ast
import pathlib

import pytest

BANNED = {"dashscope", "openai"}

# Path to the proofpay package root
PROOFPAY_ROOT = pathlib.Path(__file__).parents[1] / "proofpay"
EXTRACTION_DIR = PROOFPAY_ROOT / "extraction"


def _imports(path: pathlib.Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            yield from (a.name.split(".")[0] for a in n.names)
        elif isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
            yield n.module.split(".")[0]


def _get_non_extraction_py_files():
    files = []
    for p in PROOFPAY_ROOT.rglob("*.py"):
        # Skip files inside proofpay/extraction/
        if EXTRACTION_DIR.resolve() in p.resolve().parents:
            continue
        files.append(p)
    return files


@pytest.mark.parametrize("p", _get_non_extraction_py_files())
def test_no_cloud_sdk_outside_extraction(p: pathlib.Path):
    leaked = BANNED & set(_imports(p))
    assert not leaked, f"{p} imports {leaked}; cloud SDKs belong in proofpay/extraction/"
