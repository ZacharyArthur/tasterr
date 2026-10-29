import subprocess
import sys
from pathlib import Path


def test_live_contract_failures_hide_item_ids_and_bad_payloads(tmp_path: Path) -> None:
    probe = tmp_path / "test_redaction_probe.py"
    probe.write_text(
        "import httpx\n"
        "from types import SimpleNamespace\n"
        "from tests.live.test_jellyfin_live import _items, _require\n"
        "def test_id_failure():\n"
        '    own = SimpleNamespace(id="synthetic-private-actual-id")\n'
        '    expected = "synthetic-private-expected-id"\n'
        '    _require(own.id == expected, "Jellyfin user isolation failed")\n'
        "def test_shape_failure():\n"
        '    _items(httpx.Response(200, json={"Items": [{"Id": "synthetic-private-item-id"}], '
        '"TotalRecordCount": 1}))\n',
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "--tb=short",
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
    assert "2 failed" in output
    assert "Jellyfin user isolation failed" in output
    assert "Jellyfin fixture response shape invalid" in output
    assert "synthetic-private-" not in output
