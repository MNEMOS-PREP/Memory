"""Credential loading and the service-to-service secret.

Two files, and the split between them is the point:

    required_keys.txt   COMMITTED. Every key this module can use, with dummy
                        values and a sentence saying what each one buys you.
                        Clone the repo, copy it to keys.txt, fill it in.
    keys.txt            NEVER COMMITTED. The real values. Gitignored.

Values already present in the environment are left alone, so CI and a
deployment can set real environment variables without a file, and a developer
can override one key for one shell without editing anything.

**The service secret is not optional theatre.** M04 holds every belief the
platform has about a student, including failure signatures that AC-4.10 says
no third party may ever see. `service` endpoints are the ones another module
calls with no student present, so they are the ones that need a shared secret
rather than a session — and the check is one dependency, tested, rather than a
convention eighteen repos are trusted to follow.
"""

from __future__ import annotations

import hmac
import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

KEY_FILES = ("keys.txt", ".env")

SERVICE_SECRET_VAR = "M04_SERVICE_SECRET"


def _candidate_paths() -> list[Path]:
    here = Path(__file__).resolve()
    roots = [here.parents[1], here.parents[2]]  # Backend/, repo root
    return [root / name for root in roots for name in KEY_FILES]


def load_keys(*, override: bool = False) -> list[str]:
    """Read keys.txt / .env into the environment. Returns the names loaded."""
    loaded: list[str] = []
    for path in _candidate_paths():
        if not path.exists():
            continue
        for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, _, value = line.partition("=")
            name = name.strip()
            value = value.strip().strip('"').strip("'")
            if not name or not value:
                continue
            if override or not os.getenv(name):
                os.environ[name] = value
                loaded.append(name)
    if loaded:
        # Names only. A log line that prints a key is a key in a log file.
        log.info("loaded %d credentials from %s", len(loaded), ", ".join(KEY_FILES))
    return loaded


def service_secret() -> str | None:
    value = os.getenv(SERVICE_SECRET_VAR, "").strip()
    return value or None


def secret_matches(presented: str | None) -> bool:
    """Constant-time compare, and a deliberate decision about the empty case.

    With no secret configured the service endpoints are OPEN, and the module
    logs that at startup. The alternative — failing closed on a fresh clone —
    would mean `start_all.bat` brings M04 up and every sibling module reports
    it as broken, which teaches everyone to set a dummy secret and stop reading
    the warning. Development convenience is not worth silence, so it warns
    loudly and once.
    """
    expected = service_secret()
    if expected is None:
        return True
    if not presented:
        return False
    return hmac.compare_digest(presented, expected)
