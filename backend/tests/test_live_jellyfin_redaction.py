import subprocess
import sys
from pathlib import Path


def test_live_contract_failures_hide_item_ids_and_bad_payloads(tmp_path: Path) -> None:
    probe = tmp_path / "test_redaction_probe.py"
    probe.write_text(
        "import httpx\n"
        "import pytest\n"
        "from types import SimpleNamespace\n"
        "from tests.live import test_jellyfin_live as live\n"
        "from tests.live.test_jellyfin_live import _items, _require\n"
        "def test_id_failure():\n"
        '    own = SimpleNamespace(id="synthetic-private-actual-id")\n'
        '    expected = "synthetic-private-expected-id"\n'
        '    _require(own.id == expected, "Jellyfin user isolation failed")\n'
        "def test_shape_failure():\n"
        '    _items(httpx.Response(200, json={"Items": [{"Id": "synthetic-private-item-id"}], '
        '"TotalRecordCount": 1}))\n'
        '@pytest.mark.parametrize("phase", ["delete", "verify"])\n'
        "async def test_cleanup_transport_failure(phase, monkeypatch):\n"
        '    monkeypatch.setattr(live, "URL", "http://synthetic-private-url.invalid")\n'
        '    monkeypatch.setattr(live, "KEY", "synthetic-private-api-key")\n'
        '    monkeypatch.setenv("TASTERR_LIVE_JELLYFIN_DISPOSABLE_USERS", "true")\n'
        "    created = 0\n"
        "    deleted = []\n"
        "    def respond(request):\n"
        "        nonlocal created\n"
        '        if request.url.path == "/Users/New":\n'
        "            created += 1\n"
        '            return httpx.Response(200, json={"Id": format(created, "032x"),\n'
        '                "Name": "synthetic-private-name",\n'
        '                "Policy": {"IsAdministrator": False, "IsDisabled": False}})\n'
        '        if request.method == "DELETE":\n'
        "            deleted.append(request.url.path)\n"
        '            if phase == "delete" and len(deleted) == 1:\n'
        '                raise httpx.ReadTimeout("synthetic-private-error", request=request)\n'
        "            return httpx.Response(204)\n"
        '        if request.method == "GET":\n'
        '            if phase == "verify" and len(deleted) == 1:\n'
        '                raise httpx.ReadTimeout("synthetic-private-error", request=request)\n'
        "            return httpx.Response(404)\n"
        "        return httpx.Response(204)\n"
        "    http = httpx.AsyncClient(transport=httpx.MockTransport(respond))\n"
        '    monkeypatch.setattr(live.httpx, "AsyncClient", lambda **kwargs: http)\n'
        "    fixture = live.disposable_users.__wrapped__()\n"
        "    await anext(fixture)\n"
        "    try:\n"
        "        await anext(fixture)\n"
        "    except pytest.fail.Exception:\n"
        "        assert len(deleted) == 4\n"
        '        print("All cleanup deletions attempted")\n'
        "        raise\n"
        '    pytest.fail("Cleanup transport failure was not reported")\n',
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-c",
            "pyproject.toml",
            "-q",
            "--tb=long",
            "--showlocals",
            "--noconftest",
            "-p",
            "no:cacheprovider",
            "-o",
            "addopts=",
            str(probe),
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    output = result.stdout + result.stderr
    assert result.returncode == 1
    assert "4 failed" in output
    assert "Jellyfin user isolation failed" in output
    assert "Jellyfin fixture response shape invalid" in output
    assert "Jellyfin disposable-user cleanup failed" in output
    assert output.count("\nAll cleanup deletions attempted\n") == 2
    assert "synthetic-private-" not in output
