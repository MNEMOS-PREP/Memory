"""M04 — Skill Graph & MNEMOS Memory · standalone application.

Runs this module ALONE on its reserved port, for focused development without
the other 18 in the way:

    uvicorn backend_M04_Skill_Graph_Memory.app:app --reload --port 8104

The same router is also mounted into the gateway on :8000, which is what the
frontend talks to. Identical behaviour either way. Ports: PORTS.txt.

`/health` is not boilerplate here: `module.json` in every dependent repo probes
`health_path: "/health"`, and M15 ships that probe today. Without it, M04 reads
as permanently down to every module that degrades gracefully around it, and
every student sees "Your preparation — needs M04, which isn't running."
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from ai_core.db import create_all, engine, get_session
from ai_core.schema_repair import ensure_schema
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .keys import load_keys, service_secret
from .ontology import OntologyError, load
from .router import router
from .service import sync_ontology

log = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    load_keys()

    # create_all() creates missing TABLES and ignores tables that already
    # exist, so a model that gained a field leaves an older dev.db one column
    # short and the next query 500s. ensure_schema() adds those columns.
    # Additive only — see ai_core.schema_repair.
    create_all()
    for change in ensure_schema(engine):
        log.info("schema: added missing column %s", change)

    try:
        graph = load()
    except OntologyError as exc:
        # There is no serving without a graph: every write validates against
        # it. Fail loudly at startup, where a human is watching, rather than
        # 500ing on the first observation an hour later.
        log.error("FATAL: %s", exc)
        raise

    session = next(get_session())
    try:
        sync_ontology(session, graph)
    finally:
        session.close()

    if not graph.reviewed:
        log.warning(
            "ontology v%s has NOT been reviewed by a faculty member — AC-4.9 gates "
            "Phase-1 exit on that walk, and every prerequisite edge is load-bearing",
            graph.version,
        )
    if service_secret() is None:
        log.warning(
            "%s is not set: service endpoints are OPEN. Fine on a laptop, never in a "
            "pilot — this module holds every belief the platform has about a student",
            "M04_SERVICE_SECRET",
        )
    yield


app = FastAPI(title="M04 — Skill Graph & MNEMOS Memory", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    graph = load()
    return {"status": "ok", "module": "M04", "ontology_version": graph.version}
