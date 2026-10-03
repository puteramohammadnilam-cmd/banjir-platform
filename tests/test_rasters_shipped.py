"""The JRC rasters shipped with the app (plan card A2): recorded checksums, deploy filters and the deploy.sh guard.

The depth files (about 39 MB) are not in git. app/data/rasters/SOURCES.txt records what they are, and the tests that
need the files skip on a clone without them. The ignore-file checks read .gcloudignore (gcloud follows .gitignore
rules) and .dockerignore (Docker's own rules) as closely as fnmatch allows. Standard library only.
"""
import fnmatch
import hashlib
import re
from collections.abc import Sequence
from pathlib import Path
from typing import NamedTuple

import pytest

ROOT = Path(__file__).resolve().parent.parent
RASTER_DIR = ROOT / "app" / "data" / "rasters"
SOURCES = RASTER_DIR / "SOURCES.txt"
PENINSULA_FILES = tuple(f"ID211_N10_E100_RP{rp}_depth.tif" for rp in (10, 100, 500))
BORNEO_FILES = tuple(f"ID220_N10_E110_RP{rp}_depth.tif" for rp in (10, 100, 500))     # Sabah and Sarawak
LANGKAWI_FILES = tuple(f"ID202_N10_E90_RP{rp}_depth.tif" for rp in (10, 100, 500))
PROBE = "app/data/rasters/x.tif"   # any raster: no ignore file may keep it out of the image
RASTER_PATHS = (PROBE, *(f"app/data/rasters/{name}" for name in PENINSULA_FILES))
INCLUDE = "#!include:"   # in .gcloudignore, gcloud reads another file's rules in place of this line
ENTRY = re.compile(
    r"^File:[ \t]*(?P<name>\S+)[ \t]*\nBytes:[ \t]*(?P<size>\d+)[ \t]*\nSHA-256:[ \t]*(?P<sha>[0-9A-Fa-f]{64})[ \t]*$",
    re.MULTILINE)
CREDIT = (
    "European Commission JRC, global river flood hazard maps v2.1 (Baugh and others, 2024)",
    "https://developers.google.com/earth-engine/datasets/catalog/JRC_CEMS_GLOFAS_FloodHazard_v2_1",
    "CC BY 4.0",
)


# --- SOURCES.txt and the files it records ---

class Recorded(NamedTuple):
    name: str
    size: int
    sha256: str


def sources_text() -> str:
    return SOURCES.read_text(encoding="utf-8") if SOURCES.is_file() else ""


def recorded_files() -> tuple[Recorded, ...]:
    """The files SOURCES.txt records, each as File:, Bytes: and SHA-256: lines. Empty when SOURCES.txt is missing."""
    return tuple(Recorded(m["name"], int(m["size"]), m["sha"].lower()) for m in ENTRY.finditer(sources_text()))


def sha256_of(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def test_sources_records_the_three_peninsula_rasters():
    names = [entry.name for entry in recorded_files()]
    assert set(PENINSULA_FILES) <= set(names), f"SOURCES.txt records {names}"
    assert len(set(names)) == len(names)


def test_sources_credits_the_jrc_with_link_and_licence():
    text = sources_text()
    assert [part for part in CREDIT if part not in text] == []


def test_sources_states_coverage_and_date_and_records_borneo_and_langkawi():
    text = sources_text()
    assert re.search(r"^Coverage:[ \t]*\S", text, re.MULTILINE)
    assert re.search(r"^Date:[ \t]*\d{4}-\d{2}-\d{2}\b", text, re.MULTILINE)
    names = {entry.name for entry in recorded_files()}
    assert set(BORNEO_FILES + LANGKAWI_FILES) <= names, f"SOURCES.txt records {sorted(names)}"


@pytest.mark.parametrize("entry", recorded_files(), ids=lambda entry: entry.name)
def test_a_raster_in_the_folder_matches_its_recorded_size_and_hash(entry):
    path = RASTER_DIR / entry.name
    if not path.is_file():
        pytest.skip(f"{entry.name} is not in app/data/rasters (a clone without the rasters)")
    assert path.stat().st_size == entry.size, f"{entry.name}: size differs from SOURCES.txt"
    assert sha256_of(path) == entry.sha256, f"{entry.name}: SHA-256 differs from SOURCES.txt"


# --- ignore files: what an ignore file keeps out of git or out of the deploy ---

def _segments_match(patterns: Sequence[str], parts: Sequence[str]) -> bool:
    """fnmatch each pattern segment against a path segment. A `**` segment spans zero or more folders; at the end of
    a rule it means everything inside, so at least one more segment."""
    if not patterns:
        return not parts
    head, rest = patterns[0], patterns[1:]
    if head == "**":
        return any(_segments_match(rest, parts[i:]) for i in range(len(parts) + 1)) if rest else bool(parts)
    return bool(parts) and fnmatch.fnmatchcase(parts[0], head) and _segments_match(rest, parts[1:])


def _rule_matches(rule: str, path: str, *, is_dir: bool, gitignore: bool) -> bool:
    """Whether one ignore rule (its `!` already removed) names `path`, which is a folder when `is_dir`.

    Read as .gitignore (gcloud does): a trailing `/` limits the rule to folders; a rule with a `/` inside or in front
    is tied to the root; a bare name matches at any depth. Read as Docker (`gitignore` False): every rule is tied to
    the root and a trailing `/` is dropped. Either way `*` and `?` stop at `/`. Escapes and trailing-space rules are
    not handled; none is in use."""
    body = rule.strip("/")
    if not body or (gitignore and rule.endswith("/") and not is_dir):
        return False
    parts = path.split("/")
    if gitignore and "/" not in body and not rule.startswith("/"):
        return fnmatch.fnmatchcase(parts[-1], body)
    return _segments_match(body.split("/"), parts)


def excluding_rule(path: str, rules: Sequence[str], *, gitignore: bool) -> str | None:
    """The rule that keeps `path` out: for the path and each folder above it, the last rule naming it decides, and a
    `!` rule frees only what it names. A folder that is out stays out (Docker would let a later `!` reopen it, so
    this is the stricter reading). None when nothing excludes the path."""
    parts = path.split("/")
    for depth in range(1, len(parts) + 1):
        item, verdict = "/".join(parts[:depth]), None
        for rule in rules:
            if _rule_matches(rule.removeprefix("!"), item, is_dir=depth < len(parts), gitignore=gitignore):
                verdict = None if rule.startswith("!") else rule
        if verdict:
            return verdict
    return None


def ignore_rules(name: str) -> tuple[str, ...]:
    """The rule lines of an ignore file. In .gcloudignore a `#!include:<file>` line brings in that file's rules."""
    rules: tuple[str, ...] = ()
    for line in map(str.strip, (ROOT / name).read_text(encoding="utf-8").splitlines()):
        if name == ".gcloudignore" and line.startswith(INCLUDE):
            rules += ignore_rules(line[len(INCLUDE):].strip())
        elif line and not line.startswith("#"):
            rules += (line,)
    return rules


# rule sets, and whether they are read as .gitignore (True) or as Docker (False), judged against PROBE
EXCLUDING = (
    (("*.tif",), True), (("rasters",), True), (("rasters/",), True), (("app/data/rasters/*.tif",), True),
    (("/app",), True), (("app/data",), True), (("**/rasters",), True), (("app/**",), True), (("app/data/r*/",), True),
    (("*.tif", "!other.tif"), True),
    (("app/data/rasters", "!app/data/rasters/x.tif"), True),   # a folder that is out stays out
    (("**/*.tif",), False), (("app/data/rasters",), False), (("app",), False), (("app/*/rasters",), False),
    (("app/data/rasters/x.tif/",), False),   # Docker drops the trailing slash, so this names the file
)
KEEPING = (
    ((), True), ((".env", ".env.*", "!.env.example", "tests/", "tools/", "*.md", ".git/"), True),
    (("raster", "x.tif/", "data/rasters", "app/*.tif", "*.png"), True),   # part of a name, folders only, tied to root
    (("*.tif", "!app/data/rasters/*.tif"), True),
    (("*.tif",), False), (("rasters",), False), (("app/data/rasters/*.png", "tests", "*.md", "deploy.sh"), False),
)


def test_the_matcher_spots_every_rule_that_excludes_the_probe():
    missed = [rules for rules, gitignore in EXCLUDING if not excluding_rule(PROBE, rules, gitignore=gitignore)]
    assert missed == []


def test_the_matcher_leaves_alone_every_rule_that_does_not():
    wrong = [(rules, excluding_rule(PROBE, rules, gitignore=gitignore)) for rules, gitignore in KEEPING]
    assert [item for item in wrong if item[1]] == []


@pytest.mark.parametrize("name, gitignore", [(".gcloudignore", True), (".dockerignore", False)])
def test_the_ignore_file_lets_the_rasters_into_the_deploy(name, gitignore):
    assert (ROOT / name).is_file(), f"{name} is missing"
    rules = ignore_rules(name)
    cut = {path: rule for path in RASTER_PATHS if (rule := excluding_rule(path, rules, gitignore=gitignore))}
    assert not cut, f"{name} keeps these out of the upload (path: rule): {cut}"


def test_gitignore_hides_the_tiffs_but_not_sources_txt():
    rules = ignore_rules(".gitignore")
    assert all(excluding_rule(path, rules, gitignore=True) for path in RASTER_PATHS)
    assert excluding_rule("app/data/rasters/SOURCES.txt", rules, gitignore=True) is None


# --- deploy.sh ---

def commands_before_gcloud() -> str:
    """The commands of deploy.sh (comments left out) up to its first gcloud call."""
    lines = (ROOT / "deploy.sh").read_text(encoding="utf-8").splitlines()
    commands = "\n".join(line for line in lines if not line.lstrip().startswith("#"))
    return re.split(r"\bgcloud\s", commands, maxsplit=1)[0]


def test_deploy_script_stops_before_gcloud_when_a_raster_is_missing():
    guard = commands_before_gcloud()
    for rp in (10, 100, 500):
        assert f"app/data/rasters/*_RP{rp}_depth.tif" in guard
    assert "05_Raw_Data_Sources/jrc_glofas_v2_1" in guard   # where the message says to copy them from
    assert "exit 1" in guard
