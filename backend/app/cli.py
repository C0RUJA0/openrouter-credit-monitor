"""Tiny CLI helper. Usage:

    python -m app.cli hash-password 'your-password'
    python -m app.cli gen-secret
"""
from __future__ import annotations

import secrets
import sys

from app.security import hash_password


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[1] == "hash-password":
        if len(argv) < 3:
            print("usage: python -m app.cli hash-password '<password>'", file=sys.stderr)
            return 2
        print(hash_password(argv[2]))
        return 0
    if len(argv) >= 2 and argv[1] == "gen-secret":
        print(secrets.token_urlsafe(48))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
