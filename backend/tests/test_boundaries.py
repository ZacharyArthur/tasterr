"""Mechanical, list-free enforcement of the SPEC §3 boundary invariants.

Static analysis only: dynamic imports (importlib.import_module, __import__)
are out of scope — banning importlib in domain layers would be heavier than
the invariant warrants. The import-linter contracts in pyproject.toml cover
today's modules; these tests walk every file under src/tasterr so a future
module cannot silently escape the rules.
"""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "tasterr"


def _imported_modules(source: str, package_parts: tuple[str, ...]) -> set[str]:
    """Every module path a file's static imports can resolve to.

    `package_parts` is the dotted package containing the file (e.g.
    ("tasterr", "catalog") for src/tasterr/catalog/foo.py); relative imports
    resolve against it. For `from X import y`, both X and X.y are recorded,
    since y may itself be a module.
    """
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                base = node.module or ""
            else:
                anchor = package_parts[: len(package_parts) - (node.level - 1)]
                base = ".".join((*anchor, node.module)) if node.module else ".".join(anchor)
            if base:
                names.add(base)
            names.update(f"{base}.{alias.name}" if base else alias.name for alias in node.names)
    return names


def _hits(names: set[str], target: str) -> bool:
    return any(name == target or name.startswith(f"{target}.") for name in names)


def _offenders(target: str, exempt: set[Path], src: Path = SRC) -> list[str]:
    """Files under the package root whose imports can resolve into `target`."""
    found: list[str] = []
    for file in sorted(src.rglob("*.py")):
        rel = file.relative_to(src)
        if rel in exempt or (rel.parts and Path(rel.parts[0]) in exempt):
            continue
        package_parts = ("tasterr", *rel.parent.parts)
        imported = _imported_modules(file.read_text(encoding="utf-8"), package_parts)
        if _hits(imported, target):
            found.append(str(rel))
    return found


def test_httpx_imports_only_under_clients() -> None:
    offenders = _offenders("httpx", exempt={Path("clients")})
    assert offenders == [], f"httpx imported outside clients/: {offenders}"


def test_api_imported_only_by_the_app_factory() -> None:
    offenders = _offenders("tasterr.api", exempt={Path("api"), Path("main.py")})
    assert offenders == [], f"tasterr.api imported outside main.py: {offenders}"


def test_walker_resolves_bypass_spellings() -> None:
    """Regression probes for the review-found holes in the walker itself."""
    parts = ("tasterr", "catalog")

    def caught(source: str, target: str) -> bool:
        return _hits(_imported_modules(source, parts), target)

    assert caught("import httpx", "httpx")
    assert caught("from httpx import AsyncClient", "httpx")
    # `from tasterr import api` must resolve to tasterr.api
    assert caught("from tasterr import api", "tasterr.api")
    # relative spellings from a sibling package must resolve too
    assert caught("from .. import api", "tasterr.api")
    assert caught("from ..api import meta", "tasterr.api")
    assert caught("from ..api.meta import router", "tasterr.api")
    # and innocent imports stay innocent
    assert not caught("from tasterr import settings", "tasterr.api")
    assert not caught("import tasterr.apiary", "tasterr.api")


def test_exemption_is_top_level_only(tmp_path: Path) -> None:
    """A nested directory named clients/ earns no exemption."""
    nested = tmp_path / "catalog" / "clients"
    nested.mkdir(parents=True)
    (nested / "sneaky.py").write_text("import httpx\n", encoding="utf-8")
    allowed = tmp_path / "clients"
    allowed.mkdir()
    (allowed / "tmdb.py").write_text("import httpx\n", encoding="utf-8")

    offenders = _offenders("httpx", exempt={Path("clients")}, src=tmp_path)

    assert offenders == [str(Path("catalog/clients/sneaky.py"))]
