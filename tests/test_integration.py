"""Integration tests: boot the real HTTP server (gunicorn, as in the container)
and exercise it over the network with the repo's data*.json fixtures."""

import json
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def server():
    port = free_port()
    if shutil.which("gunicorn"):
        cmd = ["gunicorn", "-w", "1", "-b", f"127.0.0.1:{port}", "app:app"]
    else:  # fall back to the Flask dev server (e.g. on Windows)
        cmd = [sys.executable, "-m", "flask", "--app", "app", "run", "--port", str(port)]
    proc = subprocess.Popen(
        cmd, cwd=REPO_ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(50):
            try:
                urllib.request.urlopen(base + "/", timeout=1)
                break
            except (urllib.error.URLError, OSError):
                time.sleep(0.2)
        else:
            pytest.fail("server did not come up")
        yield base
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def post(base, endpoint, payload):
    req = urllib.request.Request(
        f"{base}{endpoint}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, resp.headers.get_content_type(), json.load(resp)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode()
        return exc.code, exc.headers.get_content_type(), json.loads(body or "null")


def load_fixture(name):
    return json.loads((REPO_ROOT / name).read_text())


def test_landing_page(server):
    with urllib.request.urlopen(server + "/", timeout=5) as resp:
        assert resp.status == 200
        assert b"Team generator" in resp.read()


@pytest.mark.parametrize("fixture", ["data3.json", "data4.json", "data11.json", "data12.json"])
@pytest.mark.parametrize("endpoint", ["/rand", "/topdown", "/avg"])
def test_fixtures_against_all_endpoints(server, endpoint, fixture):
    payload = load_fixture(fixture)
    status, ctype, body = post(server, endpoint, payload)
    assert status == 200
    assert ctype == "application/json"
    ids = set(payload["players"])
    assert set(body["team_a"]) | set(body["team_b"]) == ids
    assert not set(body["team_a"]) & set(body["team_b"])


def test_balance_females_over_http(server):
    payload = load_fixture("data12.json")
    payload["balance_females"] = True
    status, _, body = post(server, "/avg", payload)
    assert status == 200
    assert body["female_difference"] <= 1


def test_validation_error_over_http(server):
    status, ctype, body = post(server, "/avg", {"players": {"only-one": {}}})
    assert status == 400
    assert ctype == "application/json"
    assert "error" in body


def test_mu_and_sigma_always_returned(server):
    status, _, body = post(server, "/rand", {"players": {"x": {}, "y": {"mu": 30}}})
    assert status == 200
    for team in (body["team_a"], body["team_b"]):
        for player in team.values():
            assert "mu" in player and "sigma" in player
