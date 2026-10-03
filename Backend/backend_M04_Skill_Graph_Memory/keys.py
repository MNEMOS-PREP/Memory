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
rather than a session.

The check itself left this file on 2026-10-02 for Platform_Core's
`ai_core.service` (v0.12.0). M04 wrote it first; three callers then each read
it their own way and M05 had none at all. The rule changed on the way: with no
secret configured these routes used to be OPEN, with a warning. Now every
module on one machine shares a machine secret nobody has to configure, so a
fresh clone still works and the routes are never open. `M04_SERVICE_SECRET` in
`keys.txt` is still read — it is the platform's second name for the secret.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

KEY_FILES = ("keys.txt", ".env")

def _candidate_paths() -> list[Path]:
    """Backend/, this repo's root, and the directory the sibling repos live in.

    The third was M02's addition, and M06's: nineteen repositories should not
    mean nineteen copies of one secret. One `keys.txt` beside the repos serves
    them all, and on a fresh demo machine it is the only one there is — without
    this root, this module found no key and ran without its model while M02 and
    M06, reading the same file, had one (2026-10-03). `AI_KEYS_FILE` points
    elsewhere for a deployment that mounts its secret somewhere else.
    """
    here = Path(__file__).resolve()
    roots = [here.parents[1], here.parents[2], here.parents[3]]
    paths = [root / name for root in roots for name in KEY_FILES]
    override = os.getenv("AI_KEYS_FILE")
    if override:
        paths.insert(0, Path(override).expanduser().resolve())
    return paths


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
