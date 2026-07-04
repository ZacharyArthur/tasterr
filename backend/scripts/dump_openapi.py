"""Dump the OpenAPI schema for frontend type generation (`just types`)."""

import json
import sys
from pathlib import Path

from tasterr.main import create_app


def main() -> None:
    out = Path(sys.argv[1])
    out.write_text(json.dumps(create_app().openapi(), indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
