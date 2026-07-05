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
        # Honor X-Forwarded-Proto so session cookies are Secure behind the
        # tunnel; which proxy IPs to trust is M6 deployment hardening.
        proxy_headers=True,
    )


if __name__ == "__main__":
    main()
