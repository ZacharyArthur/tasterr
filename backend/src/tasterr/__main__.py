"""Production entrypoint: `python -m tasterr` binds uvicorn per settings."""

import uvicorn

from tasterr.settings import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "tasterr.main:create_app",
        factory=True,
        host=settings.tasterr_host,
        port=settings.tasterr_port,
    )


if __name__ == "__main__":
    main()
