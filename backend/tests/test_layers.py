import ast
import sys
from pathlib import Path

import pytest

_APP = Path(__file__).resolve().parents[1] / "app"

# Each ring and the app packages it may import. The longest matching prefix wins.
_ALLOWED = {
    "app.domain": ("app.domain",),
    "app.services": ("app.services", "app.domain"),
    "app.adapters": ("app.adapters", "app.services.ports", "app.domain"),
    "app.api": ("app.api", "app.services", "app.domain"),
}


def _module_name(path: Path) -> str:
    parts = path.relative_to(_APP.parent).with_suffix("").parts
    return ".".join(parts).removesuffix(".__init__")


def _ring(module: str) -> str | None:
    rings = [ring for ring in _ALLOWED if module == ring or module.startswith(f"{ring}.")]
    return max(rings, key=len, default=None)


def _imports(path: Path) -> list[ast.Import | ast.ImportFrom]:
    tree = ast.parse(path.read_text(), filename=str(path))
    return [node for node in ast.walk(tree) if isinstance(node, ast.Import | ast.ImportFrom)]


def _imported_names(node: ast.Import | ast.ImportFrom) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]

    return [node.module or ""]


def _is_allowed(name: str, allowed: tuple[str, ...]) -> bool:
    return any(name == prefix or name.startswith(f"{prefix}.") for prefix in allowed)


def _violations(path: Path) -> list[str]:
    ring = _ring(_module_name(path))
    if ring is None:
        return []

    found = []
    for node in _imports(path):
        # A relative import hides which package it reaches, so the rule cannot check it.
        if isinstance(node, ast.ImportFrom) and node.level > 0:
            found.append(f"relative import on line {node.lineno}")
            continue

        for name in _imported_names(node):
            root = name.split(".")[0]
            if root == "app" and not _is_allowed(name, _ALLOWED[ring]):
                found.append(name)
            # The domain stays free of frameworks, so it runs and tests without them.
            if ring == "app.domain" and root != "app" and root not in sys.stdlib_module_names:
                found.append(name)

    return found


_MODULES = sorted(_APP.rglob("*.py"))


@pytest.mark.parametrize("path", _MODULES, ids=[_module_name(path) for path in _MODULES])
def test_imports_point_inward(path: Path):
    """An import against the ring direction ties business rules to I/O and frameworks."""
    violations = _violations(path)

    assert violations == []
