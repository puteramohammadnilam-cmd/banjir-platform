"""deploy.sh run against a stub gcloud and a stub curl (plan card A10). No network, no real gcloud.

Each test copies deploy.sh into a temporary folder, puts the stubs first on PATH and runs it there, so the script's
relative paths (app/data/rasters/) point at the temporary folder. The stubs share one log, CALLS, so the order of
gcloud and curl calls can be read from a single list. Standard library and pytest only.
"""
import os
import shutil
import subprocess
from pathlib import Path
from typing import NamedTuple

import pytest

ROOT = Path(__file__).resolve().parent.parent
GRIDS = ("ID211_N10_E100", "ID220_N10_E110", "ID202_N10_E90")   # Peninsula, Sabah and Sarawak, Langkawi
RASTER_NAMES = tuple(f"{grid}_RP{rp}_depth.tif" for grid in GRIDS for rp in (10, 20, 50))
FAKE_URL = "https://banjir-check-test.a.run.app"
POINT_BODY = '{"lat":3.0297599,"lon":101.5364982,"source":"pin"}'
POINT_ID = "pt:3.02998,101.53667"
DOMAIN = "banjir.example.org"
SECRET_MARKER = "BODY-THAT-MUST-NOT-BE-PRINTED"

# STUB_DIR/bind_failures holds a number: that many add-iam-policy-binding calls fail first (IAM not propagated yet).
# A file STUB_DIR/no_runner makes "iam service-accounts describe" fail until "... create" has run.
GCLOUD_STUB = """#!/usr/bin/env bash
printf 'gcloud %s\\n' "$*" >> "$CALLS"
case "$*" in
  "iam service-accounts describe"*) [ ! -e "$STUB_DIR/no_runner" ] || [ -e "$STUB_DIR/runner_created" ] || exit 1 ;;
  "iam service-accounts create"*) touch "$STUB_DIR/runner_created" ;;
  "secrets add-iam-policy-binding"*)
    left=$(cat "$STUB_DIR/bind_failures" 2>/dev/null || echo 0)
    if [ "$left" -gt 0 ]; then echo $((left - 1)) > "$STUB_DIR/bind_failures"; echo "not found" >&2; exit 1; fi ;;
  "run services describe"*) echo "$FAKE_URL" ;;
  "beta run domain-mappings create"*) touch "$STUB_DIR/mapped" ;;
  "beta run domain-mappings describe"*)
    [ -e "$STUB_DIR/mapped" ] || exit 1
    echo "- name: banjir  rrdata: ghs.googlehosted.com.  type: CNAME" ;;
esac
"""

# Answers from the file named after the last part of the URL path: responses/status.json for .../api/status. No
# file means the request failed, which real curl -f reports as exit code 22.
CURL_STUB = """#!/usr/bin/env bash
printf 'curl %s\\n' "$*" >> "$CALLS"
url=""
for arg in "$@"; do case "$arg" in http*) url=$arg ;; esac; done
file="$STUB_DIR/responses/${url##*/}.json"
[ -f "$file" ] || exit 22
cat "$file"
"""

GOOD_RESPONSES = {
    "status": '{"success":true,"data":{"ai_ready":false,"model":"m","maps_ready":false,"points_ready":true},"error":null}',
    "coverage": '{"success":true,"data":{"data_version":"x","block_cells":24,"grids":[],"regions":[]},"error":null}',
    "point": '{"success":true,"data":{"coverage":"covered","region":"peninsula","place":{"id":"%s"}},"error":null}'
    % POINT_ID,
}


class Run(NamedTuple):
    proc: subprocess.CompletedProcess
    calls: list[str]

    @property
    def output(self) -> str:
        return self.proc.stdout + self.proc.stderr

    def index(self, prefix: str) -> int:
        """Position of the first call that starts with prefix; fails the test when there is none."""
        found = [i for i, call in enumerate(self.calls) if call.startswith(prefix)]
        assert found, f"no call starting with {prefix!r} in {self.calls}"
        return found[0]

    def where(self, text: str) -> int:
        """Position of the first call that contains text; fails the test when there is none."""
        found = [i for i, call in enumerate(self.calls) if text in call]
        assert found, f"no call containing {text!r} in {self.calls}"
        return found[0]

    def count(self, text: str) -> int:
        return sum(text in call for call in self.calls)


def write_stub(folder: Path, name: str, body: str) -> None:
    path = folder / name
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


def build_workdir(tmp_path: Path, rasters: tuple[str, ...]) -> Path:
    """A folder holding deploy.sh and empty raster files: the script only checks that they exist."""
    work = tmp_path / "work"
    raster_dir = work / "app" / "data" / "rasters"
    raster_dir.mkdir(parents=True)
    for name in rasters:
        (raster_dir / name).touch()
    shutil.copy(ROOT / "deploy.sh", work / "deploy.sh")
    return work


def build_stubs(tmp_path: Path, responses: dict[str, str]) -> Path:
    stubs = tmp_path / "stubs"
    (stubs / "responses").mkdir(parents=True)
    write_stub(stubs, "gcloud", GCLOUD_STUB)
    write_stub(stubs, "curl", CURL_STUB)
    for name, body in responses.items():
        (stubs / "responses" / f"{name}.json").write_text(body, encoding="utf-8")
    return stubs


def run_deploy(tmp_path: Path, *, rasters: tuple[str, ...] = RASTER_NAMES, responses: dict[str, str] | None = None,
               env: dict[str, str] | None = None, mapped: bool = False, bind_failures: int = 0,
               new_runner: bool = False) -> Run:
    work = build_workdir(tmp_path, rasters)
    stubs = build_stubs(tmp_path, GOOD_RESPONSES if responses is None else responses)
    if mapped:
        (stubs / "mapped").touch()
    if bind_failures:
        (stubs / "bind_failures").write_text(str(bind_failures), encoding="utf-8")
    if new_runner:
        (stubs / "no_runner").touch()
    calls = tmp_path / "calls.log"
    environment = {"PATH": f"{stubs}{os.pathsep}{os.environ['PATH']}", "HOME": str(tmp_path), "PROJECT": "test-project",
                   "CALLS": str(calls), "STUB_DIR": str(stubs), "FAKE_URL": FAKE_URL, "IAM_RETRY_SLEEP": "0",
                   **(env or {})}
    environment = {key: value for key, value in environment.items() if value is not None}
    proc = subprocess.run(["bash", "deploy.sh"], cwd=work, env=environment, capture_output=True, text=True,
                          stdin=subprocess.DEVNULL, timeout=60, check=False)
    lines = calls.read_text(encoding="utf-8").splitlines() if calls.exists() else []
    return Run(proc, lines)


# --- the happy path ---

def test_deploys_then_runs_the_three_smoke_checks(tmp_path):
    run = run_deploy(tmp_path)
    assert run.proc.returncode == 0, run.output
    deploy, describe = run.index("gcloud run deploy"), run.index("gcloud run services describe")
    assert deploy < describe
    for path in ("/api/status", "/api/coverage", "/api/point"):
        assert run.count(f"{FAKE_URL}{path}") == 1
        assert describe < run.where(f"{FAKE_URL}{path}")


def test_the_point_check_posts_the_known_square_as_json(tmp_path):
    run = run_deploy(tmp_path)
    point_call = run.calls[run.where(f"{FAKE_URL}/api/point")]
    assert "-X POST" in point_call
    assert POINT_BODY in point_call
    assert "application/json" in point_call
    for path in ("/api/status", "/api/coverage"):
        assert "-X POST" not in run.calls[run.where(f"{FAKE_URL}{path}")]


def test_the_service_url_is_read_from_cloud_run_for_this_service_and_region(tmp_path):
    run = run_deploy(tmp_path, env={"SERVICE": "my-svc", "REGION": "europe-west1"})
    describe = run.calls[run.index("gcloud run services describe")]
    assert "my-svc" in describe and "--region europe-west1" in describe
    assert "value(status.url)" in describe


def test_the_existing_deploy_flags_are_kept(tmp_path):
    run = run_deploy(tmp_path)
    deploy = run.calls[run.index("gcloud run deploy")]
    for flag in ("banjir-check", "--source .", "--region asia-southeast1", "--allow-unauthenticated",
                 "--service-account banjir-check-run@test-project.iam.gserviceaccount.com",
                 "GOOGLE_API_KEY=gemini-api-key:latest,GOOGLE_MAPS_API_KEY=maps-api-key:latest",
                 "--max-instances 2", "--memory 512Mi", "--timeout 300", "--quiet", "--cpu-boost"):
        assert flag in deploy, f"{flag!r} missing from {deploy!r}"
    assert run.count("secrets create") == 0   # both secrets exist, so nothing is asked or created


def test_the_script_needs_a_project(tmp_path):
    run = run_deploy(tmp_path, env={"PROJECT": None})
    assert run.proc.returncode != 0
    assert "PROJECT" in run.output
    assert run.calls == []


# --- a failing smoke check ---

BAD_STATUS = '{"success":false,"data":null,"error":"%s"}' % SECRET_MARKER
BAD_POINT = '{"success":true,"data":{"coverage":"%s","place":{"id":"%s"},"pad":"%s"}}'
FAILURES = {
    "status says not success": ({"status": BAD_STATUS}, "GET /api/status"),
    "coverage says not success": ({"coverage": BAD_STATUS}, "GET /api/coverage"),
    "status unreachable": ({"status": None}, "GET /api/status"),
    "point not covered": ({"point": BAD_POINT % ("outside", POINT_ID, SECRET_MARKER)}, "POST /api/point"),
    "point in the wrong square": ({"point": BAD_POINT % ("covered", "pt:3.1,101.5", SECRET_MARKER)}, "POST /api/point"),
    "point check fails to answer": ({"point": None}, "POST /api/point"),
}


@pytest.mark.parametrize(("change", "label"), FAILURES.values(), ids=FAILURES.keys())
def test_a_failed_smoke_check_exits_non_zero_and_names_the_check(tmp_path, change, label):
    responses = {name: body for name, body in {**GOOD_RESPONSES, **change}.items() if body is not None}
    run = run_deploy(tmp_path, responses=responses)
    assert run.proc.returncode != 0
    assert f"FAILED: {label}" in run.output
    assert SECRET_MARKER not in run.output   # a short message, never the response body
    assert run.count("gcloud run deploy") == 1   # the deploy itself had already happened


def test_every_failed_check_is_named_not_only_the_first(tmp_path):
    responses = {"status": BAD_STATUS, "coverage": BAD_STATUS, "point": BAD_STATUS}
    run = run_deploy(tmp_path, responses=responses)
    assert run.proc.returncode != 0
    for label in ("GET /api/status", "GET /api/coverage", "POST /api/point"):
        assert f"FAILED: {label}" in run.output


def test_no_domain_is_mapped_after_a_failed_smoke_check(tmp_path):
    run = run_deploy(tmp_path, responses={**GOOD_RESPONSES, "status": BAD_STATUS}, env={"DOMAIN": DOMAIN})
    assert run.proc.returncode != 0
    assert run.count("domain-mappings") == 0


# --- the raster guard ---

def without(*names: str) -> tuple[str, ...]:
    return tuple(name for name in RASTER_NAMES if name not in names)


GUARD_CASES = {
    "none": (),
    "no RP50 of the Peninsula": without("ID211_N10_E100_RP50_depth.tif"),
    "no RP10 of the Peninsula": without("ID211_N10_E100_RP10_depth.tif"),
    "Peninsula only": RASTER_NAMES[:3],
    "no Sabah and Sarawak grid": tuple(n for n in RASTER_NAMES if "ID220" not in n),
    "no Langkawi RP20": without("ID202_N10_E90_RP20_depth.tif"),
}


@pytest.mark.parametrize("present", GUARD_CASES.values(), ids=GUARD_CASES.keys())
def test_a_missing_raster_stops_the_script_before_any_gcloud_call(tmp_path, present):
    run = run_deploy(tmp_path, rasters=present)
    assert run.proc.returncode == 1
    assert "Missing flood depth raster" in run.output
    assert run.calls == []   # no gcloud, no curl


def test_the_guard_names_the_missing_file_and_points_to_the_download_list(tmp_path):
    run = run_deploy(tmp_path, rasters=without("ID202_N10_E90_RP20_depth.tif"))
    assert "ID202_N10_E90_RP20_depth.tif" in run.output
    assert "ID211" not in run.output   # only what is missing is named
    assert "app/data/rasters/SOURCES.txt" in run.output
    assert "05_Raw_Data_Sources" not in run.output   # a public clone does not have that folder


def test_the_guard_lists_every_missing_file_not_only_the_first(tmp_path):
    run = run_deploy(tmp_path, rasters=())
    assert all(name in run.output for name in RASTER_NAMES)


# --- first-run robustness ---

def test_the_deploy_does_not_stop_to_ask_questions_and_boosts_cpu_at_start(tmp_path):
    deploy = run_deploy(tmp_path).calls
    line = next(call for call in deploy if call.startswith("gcloud run deploy"))
    assert "--quiet" in line.split() and "--cpu-boost" in line.split()


def test_a_binding_refused_by_iam_is_retried_until_it_goes_through(tmp_path):
    run = run_deploy(tmp_path, bind_failures=3, new_runner=True)
    assert run.proc.returncode == 0, run.output
    assert run.count("gcloud secrets add-iam-policy-binding") == 3 + 2   # 3 refused, then the success, then 2nd secret
    assert run.index("gcloud iam service-accounts create") < run.index("gcloud secrets add-iam-policy-binding")
    assert run.count("gcloud run deploy") == 1


def test_a_binding_that_never_goes_through_stops_before_the_deploy(tmp_path):
    run = run_deploy(tmp_path, bind_failures=99)
    assert run.proc.returncode != 0
    assert run.count("gcloud secrets add-iam-policy-binding") == 5   # the limit, then it gives up
    assert "gemini-api-key" in run.output
    assert run.count("gcloud run deploy") == 0


def test_an_existing_runtime_account_is_not_created_again(tmp_path):
    run = run_deploy(tmp_path)
    assert run.count("gcloud iam service-accounts create") == 0


# --- the optional custom domain ---

def test_without_a_domain_no_mapping_is_touched(tmp_path):
    run = run_deploy(tmp_path)
    assert run.proc.returncode == 0, run.output
    assert run.count("domain-mappings") == 0


def test_a_domain_that_is_not_mapped_yet_is_created_after_the_smoke_checks(tmp_path):
    run = run_deploy(tmp_path, env={"DOMAIN": DOMAIN})
    assert run.proc.returncode == 0, run.output
    assert run.count("domain-mappings create") == 1
    create = run.calls[run.index("gcloud beta run domain-mappings create")]
    assert f"--service banjir-check --domain {DOMAIN} --region asia-southeast1" in create
    assert run.index("curl") < run.index("gcloud beta run domain-mappings create")
    assert "ghs.googlehosted.com." in run.output   # the DNS records are printed for the owner to add


def test_a_domain_that_is_already_mapped_is_not_created_again(tmp_path):
    run = run_deploy(tmp_path, env={"DOMAIN": DOMAIN}, mapped=True)
    assert run.proc.returncode == 0, run.output
    assert run.count("domain-mappings create") == 0
    assert run.count("domain-mappings describe") >= 1
    assert "ghs.googlehosted.com." in run.output


def test_the_dns_records_are_read_with_a_describe_of_the_mapping(tmp_path):
    run = run_deploy(tmp_path, env={"DOMAIN": DOMAIN}, mapped=True)
    describes = [call for call in run.calls if "domain-mappings describe" in call]
    assert all(f"--domain {DOMAIN} --region asia-southeast1" in call for call in describes)
    assert any("status.resourceRecords" in call for call in describes)
