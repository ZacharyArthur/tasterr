"""Drift guard: .env.example documents every Settings environment field."""

from pathlib import Path

from tasterr.settings import Settings

ENV_EXAMPLE = Path(__file__).resolve().parents[2] / ".env.example"


def test_env_example_documents_every_setting() -> None:
    documented = {
        line.removeprefix("#").split("=", 1)[0].strip()
        for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()
        # `VAR=...` and `#VAR=...` count; `# prose` does not
        if "=" in line and not line.lstrip().startswith("# ")
    }

    expected = {name.upper() for name in Settings.model_fields}

    missing = expected - documented
    assert not missing, f".env.example is missing: {sorted(missing)}"
