"""Guard rails (plan card A0): file size, function size, innerHTML and console.log. Standard library only."""
import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MAX_FILE_LINES = 800
MAX_FUNCTION_LINES = 50
SIZED_FOLDERS = ("app", "tests", "tools")
SIZED_SUFFIXES = {".py", ".js", ".mjs", ".css", ".html"}
SKIPPED_FOLDERS = (Path("app/static/vendor"), Path("app/data"))   # third-party Leaflet, built data
PAGE_SCRIPTS = Path("app/static/js")
INNERHTML_HOME = "app/static/js/chat.js"   # Google's search suggestions arrive as HTML
PAGE_FOLDER = Path("app/static")
PAGE_SUFFIXES = {".html", ".js"}
PLACE_NAMES = ("Sri Muda", "Taman Sri Muda", "Shah Alam", "Seksyen", "MBSA")   # a curated area's own words: area.json only

# A breach that already exists in code card A0 may not edit: dom.js line 1 is a comment saying "never innerHTML", and
# the rule is a plain text search. It is a strict xfail on that one script, so every other script stays guarded. Once
# the comment is reworded the run fails (XPASS) until this entry is deleted.
KNOWN_INNERHTML_BREACHES: dict[str, str] = {}   # path -> reason, for a breach waiting on a fix


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def is_skipped(path: Path) -> bool:
    return any(path.relative_to(ROOT).is_relative_to(skip) for skip in SKIPPED_FOLDERS)


def sized_files() -> list[Path]:
    found = (p for folder in SIZED_FOLDERS for p in (ROOT / folder).rglob("*") if p.suffix in SIZED_SUFFIXES and p.is_file())
    return sorted(p for p in found if not is_skipped(p))


def python_sources() -> list[Path]:
    return sorted(p for folder in ("app", "tools") for p in (ROOT / folder).rglob("*.py"))


def page_scripts() -> list[Path]:
    return sorted((ROOT / PAGE_SCRIPTS).rglob("*.js"))


def page_sources() -> list[Path]:
    """The page's own html and scripts, not the vendored Leaflet."""
    found = (p for p in (ROOT / PAGE_FOLDER).rglob("*") if p.suffix in PAGE_SUFFIXES and p.is_file())
    return sorted(p for p in found if not is_skipped(p))


def place_names_in(text: str) -> list[str]:
    return [name for name in PLACE_NAMES if name.lower() in text.lower()]


def line_count(path: Path) -> int:
    with path.open(encoding="utf-8") as lines:
        return sum(1 for _ in lines)


def body_length(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    """Lines after the signature and any docstring, through the function's last line."""
    first = node.body[0]
    has_docstring = ast.get_docstring(node, clean=False) is not None
    start = first.end_lineno + 1 if has_docstring else first.lineno
    return node.end_lineno - start + 1


def long_functions(source: str, label: str) -> list[str]:
    """One 'path:line name length' entry for every function or method whose body passes the limit."""
    defs = [n for n in ast.walk(ast.parse(source)) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    measured = [(n, body_length(n)) for n in sorted(defs, key=lambda n: n.lineno)]
    return [f"{label}:{n.lineno} {n.name} {length}" for n, length in measured if length > MAX_FUNCTION_LINES]


def script_case(path: Path):
    """One case per script, so a known breach can be a strict xfail without switching the rule off elsewhere."""
    reason = KNOWN_INNERHTML_BREACHES.get(rel(path))
    marks = [pytest.mark.xfail(strict=True, reason=reason)] if reason else []
    return pytest.param(path, marks=marks, id=rel(path))


def test_no_python_function_body_is_longer_than_50_lines():
    breaches = [b for p in python_sources() for b in long_functions(p.read_text(encoding="utf-8"), rel(p))]
    assert not breaches, f"function bodies over {MAX_FUNCTION_LINES} lines (path:line name length):\n" + "\n".join(breaches)


def test_no_source_file_is_longer_than_800_lines():
    breaches = [f"{rel(p)} {n}" for p in sized_files() if (n := line_count(p)) > MAX_FILE_LINES]
    assert not breaches, f"files over {MAX_FILE_LINES} lines (path lines):\n" + "\n".join(breaches)


@pytest.mark.parametrize("path", [script_case(p) for p in page_scripts() if rel(p) != INNERHTML_HOME])
def test_innerhtml_is_used_only_in_chat_js(path):
    assert "innerHTML" not in path.read_text(encoding="utf-8")


def test_the_page_never_asks_for_flood_squares_by_url():
    """GET /api/cells/{grid}/{bi}/{bj} names a block in its URL, which reaches server and proxy logs and so tells them the
    area a person is looking at (about 2 km). The squares around a point come in the answer to POST /api/point, whose
    body is never logged, so no page script may request that path (a quoted or template string that starts with it)."""
    asks = [rel(p) for p in page_scripts() if re.search(r"[\"'`]/api/cells", p.read_text(encoding="utf-8"))]
    assert not asks, "requests for /api/cells in:\n" + "\n".join(asks)


def test_the_flood_squares_scan_finds_a_request_and_leaves_comments_alone():
    asks = re.compile(r"[\"'`]/api/cells")
    assert asks.search("const getCells = (grid, bi, bj) => call(`/api/cells/${grid}/${bi}/${bj}`);")
    assert asks.search('fetch("/api/cells/N10_E100/1/2")') and asks.search("fetch('/api/cells/x')")
    assert not asks.search("// the old GET /api/cells call, gone: a block's URL names the area")


def test_console_log_is_absent_from_page_scripts():
    offenders = [rel(p) for p in page_scripts() if "console.log" in p.read_text(encoding="utf-8")]
    assert not offenders, "console.log in:\n" + "\n".join(offenders)


@pytest.mark.parametrize("path", page_sources(), ids=rel)
def test_the_page_names_no_place(path):
    """Titles, labels, greetings and floods come from the area's config (area.json), so one build serves every area."""
    assert place_names_in(path.read_text(encoding="utf-8")) == [], f"{rel(path)} holds a curated area's place name"


def test_the_place_name_scan_matches_any_case_and_leaves_other_words_alone():
    assert place_names_in("Map of TAMAN SRI MUDA") == ["Sri Muda", "Taman Sri Muda"]
    assert place_names_in("seksyen 25, mbsa and shah alam") == ["Shah Alam", "Seksyen", "MBSA"]
    assert place_names_in("Kota Tinggi town centre, Johor. Malaysia, Selangor, Banjir Check") == []


def function_source(statements: int) -> str:
    """A function with a two-line signature and a three-line docstring, then `statements` one-line statements."""
    return 'def f(a,\n      b):\n    """Doc\n\n    string."""\n' + "    x = 1\n" * statements


def test_function_length_excludes_the_signature_and_docstring():
    assert long_functions(function_source(50), "t.py") == []
    assert long_functions(function_source(51), "t.py") == ["t.py:1 f 51"]


def test_methods_and_async_functions_are_measured_too():
    method = "class C:\n    def run(self):\n" + "        x = 1\n" * 51
    coroutine = "async def go():\n" + "    x = 1\n" * 51
    assert long_functions(method, "t.py") == ["t.py:2 run 51"]
    assert long_functions(coroutine, "t.py") == ["t.py:1 go 51"]


def test_the_scans_reach_the_real_sources_and_skip_vendor_and_data():
    sized = [rel(p) for p in sized_files()]
    assert {name.split("/")[0] for name in sized} == set(SIZED_FOLDERS)
    assert {rel(p).split("/")[0] for p in python_sources()} == {"app", "tools"}
    assert INNERHTML_HOME in [rel(p) for p in page_scripts()]
    assert not [name for name in sized if name.startswith(("app/static/vendor/", "app/data/"))]
    scanned = [rel(p) for p in page_sources()]
    assert {"app/static/index.html", "app/static/js/history.js", "app/static/js/chat.js"} <= set(scanned)
    assert not [name for name in scanned if name.startswith("app/static/vendor/")]
