"""Throwaway email services (temp-mail and the like): accounts are not opened on them.

An account on an address that disappears in an hour can never reset its password, and such
addresses are how sign-up limits get dodged. The list is app/data/disposable_domains.txt, one
domain per line; a subdomain of a listed domain counts too.
"""

from functools import lru_cache
from pathlib import Path

LIST_FILE = Path(__file__).resolve().parents[1] / "data" / "disposable_domains.txt"


@lru_cache(maxsize=1)
def _domains() -> frozenset[str]:
    lines = LIST_FILE.read_text(encoding="utf-8").splitlines()
    return frozenset(line.strip().lower() for line in lines if line.strip() and not line.startswith("#"))


def is_disposable(email: str) -> bool:
    domain = email.rsplit("@", 1)[-1].strip().lower()
    parts = domain.split(".")
    # mail.tempmail.com is as throwaway as tempmail.com.
    return any(".".join(parts[i:]) in _domains() for i in range(len(parts) - 1))
