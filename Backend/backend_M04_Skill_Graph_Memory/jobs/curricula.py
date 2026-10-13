"""Build a programme's curriculum from the college's own curriculum PDF.

    python -m backend_M04_Skill_Graph_Memory.jobs.curricula <curriculum.pdf> [...]
    python -m backend_M04_Skill_Graph_Memory.jobs.curricula <curriculum.pdf> --dry-run

Needs the `curricula` extra (PyMuPDF): `pip install -e ".[curricula]"`. It is
a build step run when the college publishes a curriculum, never a request
path, so the module does not depend on it.

What it writes, to `packages/knowledge/curricula/<id>.json`:

* every semester's courses, from the curriculum tables — code, title,
  category, L-T-P and credits, and the elective SLOTS ("Professional
  Elective I") a student fills from a basket;
* the professional-elective baskets;
* for every course, the ontology concepts its syllabus teaches, each with the
  alias that matched, so "why is Deadlocks under Operating Systems" is
  answered by a phrase from the college's own syllabus, not by us.

Why derived and not typed (2026-10-13). The student is asked their semester
and courses at sign-in so that practice can follow what they are studying. A
hand-typed course list is one curriculum revision behind and silently wrong
for a branch nobody typed; this one is re-run on the next PDF. Three
techniques, each where it is strong:

* **structure** for the tables: PyMuPDF reads the cells, and a row the PDF
  split in two (a title on one line, its code on the next) is merged back by
  which fields each half carries;
* **a second source** to check the first: every syllabus page opens with
  "<code> <TITLE> L-T-P-C", and each table title is compared with it. A
  disagreement is printed, never silently resolved — the layout text of the
  CSE PDF pairs 23CSE203 with the wrong title, and only the cells are right;
* **ontology lookup** for the concepts: the syllabus units are matched against
  the ontology's own alias index (`normalise_alias`), never a model's guess.
  A light plural fold ("deadlock" / "deadlocks") is the only stretch, applied
  to both sides. A single word counts only where the same syllabus teaches
  that domain by phrase (`concepts_for` says why), because "functions" in a
  calculus syllabus is not the programming concept.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from ai_core.concepts import normalise_alias

from ..curricula import default_dir
from ..ontology import Ontology, load

CODE = re.compile(r"^(\d{2}[A-Z]{3}\d{3})\**$")
SEMESTER = re.compile(r"^semester\s+([ivx]+|\d)$", re.I)
ROMAN = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7, "viii": 8}
#: Column headers, which some tables repeat as a row of their own.
HEADER_CELLS = frozenset(
    {
        "title",
        "subject",
        "course title",
        "code",
        "cat",
        "cat.",
        "credit",
        "credits",
        "cr",
        "evaluation pattern",
        "evaluation",
        "l t p",
        "l-t-p",
    }
)
LTP = re.compile(r"^\[?\d+\]?\s*[-\u2013\u2014 ]\s*\d+\s*[-\u2013\u2014 ]\s*\d+$")
CREDIT = re.compile(r"^(?:\d{1,2}|P/F|\[\d\])$")
EVALUATION = re.compile(r"^\d{2}:\d{2}$")
CATEGORY = re.compile(r"^(?:SCI|ENGG|CSE|HUM|PRJ|CSE\s*/\s*ENGG)$")
#: "23CSE101 COMPUTATIONAL PROBLEM SOLVING L-T-P-C: 3-0-2-4" — a syllabus page.
SYLLABUS_HEAD = re.compile(r"^\s*(\d{2}[A-Z]{3}\d{3})\b(.*?)\bL-T-P-C\b")
SYLLABUS_START = re.compile(r"^\s*syllabus\b", re.I)
#: The heading after the units: whole-line and capitalised for the book
#: headings, because a unit that wraps onto a line reading just "references"
#: (22AIE111: "...The concept of / references") is still the syllabus, and
#: stopping there lost three of its four units.
_BOOKS = r"(?:text\s*books?|text\s*book\(s\)|reference\s+books?|references?)"
SYLLABUS_END = re.compile(
    rf"^\s*(?:{_BOOKS}(?:\s*[/&,]\s*{_BOOKS})*\s*:?\s*$"
    r"|evaluation\s+(?:plan|pattern)\b|assessment\b.*\binternal\b)",
    re.I,
)


def _ends_syllabus(line: str) -> bool:
    return bool(SYLLABUS_END.match(line)) and line.strip()[:1].isupper()


# ── reading the PDF ──────────────────────────────────────────────────────────


def _clean(cell: str | None) -> str:
    # U+FFFD is the PDF's dash, lost in extraction ("Live-in \ufffdLabs I").
    text = (cell or "").replace("\ufffd", "-").replace("\n", " ")
    text = re.sub(r"\s+", " ", text).strip()
    # "Live-in -Labs I***": the footnote stars go, the stray space before a
    # hyphen goes; "Project - Phase II" keeps its spaced dash.
    text = re.sub(r"\*+$", "", text).strip()
    return re.sub(r"\s+-(?=\S)", "-", text)


def _lines(page) -> list[tuple[float, str]]:
    """The page's text as (y, line), words regrouped by baseline.

    PyMuPDF's own line order splits "23CSE101" from its title when the two are
    separate spans; regrouping by y gives the line a reader sees.
    """
    rows: list[tuple[float, list[tuple[float, str]]]] = []
    for x0, y0, _x1, y1, word, *_ in sorted(page.get_text("words"), key=lambda w: (w[1], w[0])):
        mid = (y0 + y1) / 2
        if rows and abs(rows[-1][0] - mid) <= 3:
            rows[-1][1].append((x0, word))
        else:
            rows.append((mid, [(x0, word)]))
    return [(y, " ".join(w for _, w in sorted(words))) for y, words in rows]


@dataclass
class Fragment:
    """One table row's fields. A course is one or two of these."""

    code: str | None = None
    title: str | None = None
    category: str | None = None
    ltp: str | None = None
    credits: str | None = None

    def fields(self) -> dict[str, str]:
        return {k: v for k, v in self.__dict__.items() if v}

    def compatible(self, other: Fragment) -> bool:
        mine, theirs = self.fields(), other.fields()
        return all(mine[k] == v for k, v in theirs.items() if k in mine)

    def absorb(self, other: Fragment) -> None:
        for key, value in other.fields().items():
            setattr(self, key, getattr(self, key) or value)


def _fragment(cells: list[str]) -> Fragment | None:
    """A row's cells by what they look like, not by column index: the same
    table puts a code in column 3 on one row and column 4 on the next."""
    frag = Fragment()
    for cell in cells:
        if not cell:
            continue
        if m := CODE.match(cell):
            frag.code = frag.code or m.group(1)
        elif CATEGORY.match(cell):
            frag.category = frag.category or cell.replace(" ", "")
        elif LTP.match(cell):
            frag.ltp = frag.ltp or re.sub(r"\s*[-\u2013\u2014 ]\s*", "-", cell)
        elif CREDIT.match(cell):
            frag.credits = frag.credits or cell
        elif EVALUATION.match(cell):
            continue
        elif re.search(r"[A-Za-z]{3}", cell):
            # The longest wordy cell is the title; a header row is dropped below.
            if frag.title is None or len(cell) > len(frag.title):
                frag.title = cell
    if not frag.fields():
        return None
    title = (frag.title or "").casefold()
    if title in HEADER_CELLS or title.startswith(("total", "cat ")):
        # A header row ("Cat PRJ" is the header of a one-course table).
        frag.title = None
        return frag if frag.code else None
    if frag.title and (frag.title[0] in "*@" or len(frag.title.split()) > 12):
        # A footnote the table detector swept into the last row.
        return None
    return frag


@dataclass
class Context:
    kind: str  # "semester" | "basket" | "skip"
    name: str
    number: int | None = None
    rows: list[Fragment] = field(default_factory=list)
    pending: list[Fragment] = field(default_factory=list)

    def add(self, frag: Fragment) -> None:
        prev = self.rows[-1] if self.rows else None
        continues = (
            prev is not None
            and not self.pending
            and prev.compatible(frag)
            and (
                (frag.code and not frag.title and not prev.code)
                or (frag.title and not frag.code and not prev.title)
                or (not frag.code and not frag.title)
            )
        )
        if continues:
            prev.absorb(frag)
        elif not frag.code and not frag.title:
            self.pending.append(frag)
        else:
            for early in self.pending:
                frag.absorb(early)
            self.pending = []
            self.rows.append(frag)


def _heading(text: str) -> Context | None:
    """A semester or elective-basket heading, or None."""
    text = _clean(text)
    if m := SEMESTER.match(text):
        token = m.group(1).casefold()
        number = ROMAN.get(token) or int(token)
        return Context("semester", f"Semester {number}", number)
    lowered = text.casefold()
    if len(text.split()) > 9 or text.startswith("*") or CODE.match(text.split(" ")[0] or ""):
        return None
    if "other branches" in lowered:
        return Context("skip", text)
    if "free elective" in lowered or "value programme" in lowered:
        # They fill free and value slots, which do not change an interview;
        # their tables are also the ones the PDF misaligns.
        return Context("skip", text)
    if "elective" in lowered:
        return Context("basket", text)
    return None


def _first_syllabus_page(doc) -> int:
    for number, page in enumerate(doc):
        if any(SYLLABUS_HEAD.match(line) for _, line in _lines(page)):
            return number
    return doc.page_count


def read_tables(doc) -> list[Context]:
    """Every course row, in reading order, under the heading above it."""
    contexts: list[Context] = []
    current: Context | None = None
    for number in range(_first_syllabus_page(doc)):
        page = doc[number]
        tables = page.find_tables().tables
        boxes = [t.bbox for t in tables]
        items: list[tuple[float, str, object]] = []
        for y, line in _lines(page):
            inside = any(b[1] - 1 <= y <= b[3] + 1 for b in boxes)
            if not inside:
                items.append((y, "line", line))
        for table in tables:
            for row, cells in zip(table.rows, table.extract(), strict=False):
                items.append((row.bbox[1], "row", [_clean(c) for c in cells]))
        for _y, kind, payload in sorted(items, key=lambda i: i[0]):
            if kind == "line":
                heading = _heading(payload)  # type: ignore[arg-type]
                if heading:
                    current = heading
                    contexts.append(current)
                continue
            cells: list[str] = payload  # type: ignore[assignment]
            first = next((c for c in cells if c), "")
            heading = _heading(first) if first and sum(bool(c) for c in cells) == 1 else None
            if heading:
                current = heading
                contexts.append(current)
                continue
            if current is None or current.kind == "skip":
                continue
            frag = _fragment(cells)
            if frag:
                current.add(frag)
    return contexts


def read_syllabi(doc) -> dict[str, dict[str, str]]:
    """code -> {"heading": the syllabus page's own title, "units": the units' text}."""
    lines: list[str] = []
    for number in range(_first_syllabus_page(doc), doc.page_count):
        lines += [line for _, line in _lines(doc[number])]
    found: dict[str, dict[str, str]] = {}
    starts = [(i, m) for i, line in enumerate(lines) if (m := SYLLABUS_HEAD.match(line))]
    for n, (i, match) in enumerate(starts):
        end = starts[n + 1][0] if n + 1 < len(starts) else len(lines)
        body = lines[i + 1 : end]
        begin = next((k for k, line in enumerate(body) if SYLLABUS_START.match(line)), None)
        if begin is None:
            units = body
        else:
            stop = next(
                (k for k, line in enumerate(body[begin + 1 :], begin + 1) if _ends_syllabus(line)),
                len(body),
            )
            units = body[begin + 1 : stop]
        code = match.group(1)
        # A course can have two syllabus pages (a lab and its theory); keep both.
        entry = found.setdefault(code, {"heading": _clean(match.group(2)), "units": ""})
        entry["units"] += "\n" + "\n".join(units)
    return found


# ── the concepts each syllabus teaches ────────────────────────────────────────


def _fold(words: str) -> str:
    """Symmetric plural fold, for matching only: "deadlocks" ~ "deadlock"."""
    return " ".join(
        w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w
        for w in words.split()
    )


def concepts_for(units: str, graph: Ontology) -> list[dict]:
    text = f" {_fold(normalise_alias(units))} "
    hits: dict[str, dict[str, int]] = {}
    for alias, concept_id in graph.alias_index.items():
        if len(alias) < 3 or alias.startswith("concept "):
            continue
        count = text.count(f" {_fold(alias)} ")
        if count:
            hits.setdefault(concept_id, {})[alias] = count
    # A phrase ("virtual memory", "k means") is a topic. A single word is a
    # topic only where the syllabus already teaches that DOMAIN by phrase:
    # "graphs" counts in a discrete-maths syllabus that also says "recurrence
    # relations", not in a calculus one; "acid" never reaches a chemistry
    # course, "rest" never reaches a meditation one. Measured on both PDFs
    # (2026-10-13): the generic words were "functions", "methods",
    # "process", "variables", "solid", "acid", "segmentation".
    phrased = {cid for cid, matched in hits.items() if any(" " in alias for alias in matched)}
    taught = {graph.get(cid).domain for cid in phrased}
    kept: dict[str, dict[str, int]] = {}
    for concept_id, matched in hits.items():
        concept = graph.get(concept_id)
        if concept_id not in phrased and (
            concept.domain not in taught
            # The floor's words are the generic ones ("functions", "methods",
            # "variables", "loops"): every algorithms syllabus says them, and
            # the floor is never practised on its own (M16 §6.4a).
            or concept.foundational_floor
        ):
            continue
        kept[concept_id] = matched
    total = {cid: sum(m.values()) for cid, m in kept.items()}
    if sum(total.values()) < 2:
        # One phrase once is a mention, not a course's subject: "transfer
        # learning" in a project's description, "trade-offs" in an AR/VR one.
        return []
    weight: dict[str, int] = {}
    for cid, n in total.items():
        weight[graph.get(cid).domain] = weight.get(graph.get(cid).domain, 0) + n
    dominant = max(weight, key=weight.get)
    out = [
        {"id": cid, "hits": total[cid], "matched": sorted(matched)}
        for cid, matched in kept.items()
        # Outside the course's own domain, once is a stray: "message passing"
        # in a graph-learning syllabus is not inter-process communication.
        if graph.get(cid).domain == dominant or total[cid] >= 2
    ]
    return sorted(out, key=lambda c: (-c["hits"], c["id"]))


# ── assembling a programme ───────────────────────────────────────────────────


def _slot(title: str) -> str | None:
    lowered = title.casefold()
    if "professional elective" in lowered:
        return "professional"
    if "free elective" in lowered:
        return "free"
    if "value" in lowered and "program" in lowered:
        return "value"
    return None


def _norm_title(title: str) -> str:
    return normalise_alias(title.replace("&", " and ")).replace(" and ", " ")


def _programme_name(doc) -> tuple[str, int | None]:
    text = " ".join(line for page in list(doc)[:2] for _, line in _lines(page))
    name_match = re.search(
        r"B\.?\s?TECH\.?\s*[-\u2013]?\s*([A-Za-z ()&-]+?)(?=\s+\(?BTC|\s+CURRICULUM|$)", text, re.I
    )
    year_match = re.search(r"CURRICULUM[^0-9]{0,30}(20\d\d)", text, re.I)
    raw = name_match.group(1).strip() if name_match else "Unknown programme"
    words = [
        w if w.isupper() and len(w) <= 4 and w != "AND" else w.capitalize() for w in raw.split()
    ]
    name = " ".join("and" if w.casefold() == "and" else w for w in words)
    name = re.sub(r"\((\w)", lambda m: "(" + m.group(1).upper(), name)
    return f"B.Tech {name}", int(year_match.group(1)) if year_match else None


def build(pdf: Path, graph: Ontology, institution: str) -> tuple[dict, list[str]]:
    import pymupdf  # the `curricula` extra; a build step, not a module dependency

    doc = pymupdf.open(pdf)
    warnings: list[str] = []
    contexts = read_tables(doc)
    syllabi = read_syllabi(doc)
    name, year = _programme_name(doc)

    def course(frag: Fragment) -> dict:
        record = {
            "code": frag.code,
            "title": frag.title,
            "category": frag.category,
            "ltp": frag.ltp,
            "credits": frag.credits,
        }
        syllabus = syllabi.get(frag.code or "")
        if syllabus is None:
            warnings.append(f"{frag.code} {frag.title}: no syllabus page")
            record["concepts"] = []
            return record
        heading = syllabus["heading"]
        if heading and _norm_title(heading) != _norm_title(frag.title or ""):
            warnings.append(f"{frag.code}: table says {frag.title!r}, syllabus says {heading!r}")
        record["concepts"] = concepts_for(syllabus["units"], graph)
        return record

    semesters: dict[int, dict] = {}
    baskets: list[dict] = []
    for ctx in contexts:
        if ctx.kind == "semester" and ctx.number:
            sem = semesters.setdefault(
                ctx.number, {"number": ctx.number, "courses": [], "slots": []}
            )
            for frag in ctx.rows:
                if frag.code and frag.title:
                    sem["courses"].append(course(frag))
                elif frag.title and (kind := _slot(frag.title)):
                    sem["slots"].append(
                        {"kind": kind, "title": frag.title, "credits": frag.credits}
                    )
                else:
                    warnings.append(f"semester {ctx.number}: unplaced row {frag.fields()}")
        elif ctx.kind == "basket":
            rows = [course(f) for f in ctx.rows if f.code and f.title]
            if rows:
                baskets.append({"name": ctx.name, "kind": "professional", "courses": rows})

    # The department's own code prefix is the one most core courses carry.
    prefixes = [c["code"][2:5] for s in semesters.values() for c in s["courses"]]
    short = max(set(prefixes), key=prefixes.count) if prefixes else "GEN"
    slug = re.sub(r"[^a-z0-9]+", "-", institution.casefold()).strip("-").split("-")[0]
    programme = {
        "id": f"{slug}-btech-{short.casefold()}-{year or 'undated'}",
        "institution": institution,
        "name": name,
        "short": short,
        "curriculum_year": year,
        "source": {
            "file": pdf.name,
            "sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(),
            "pages": doc.page_count,
        },
        "ontology_version": graph.version,
        "semesters": [semesters[n] for n in sorted(semesters)],
        "electives": baskets,
    }
    if sorted(semesters) != list(range(1, 9)):
        warnings.append(f"semesters found: {sorted(semesters)} (expected 1-8)")
    return programme, warnings


def main() -> int:
    parser = argparse.ArgumentParser(description="Build curricula from curriculum PDFs")
    parser.add_argument("pdfs", nargs="+", type=Path)
    parser.add_argument("--institution", default="Amrita Vishwa Vidyapeetham")
    parser.add_argument("--dry-run", action="store_true", help="print, write nothing")
    args = parser.parse_args()

    graph = load()
    out_dir = default_dir()
    for pdf in args.pdfs:
        programme, warnings = build(pdf, graph, args.institution)
        courses = [c for s in programme["semesters"] for c in s["courses"]]
        electives = [c for b in programme["electives"] for c in b["courses"]]
        mapped = [c for c in courses + electives if c["concepts"]]
        print(
            f"{programme['id']}: {programme['name']} — {len(programme['semesters'])} semesters, "
            f"{len(courses)} courses, {len(electives)} electives in "
            f"{len(programme['electives'])} baskets; {len(mapped)} map to concepts"
        )
        for warning in warnings:
            print(f"  ! {warning}")
        if not args.dry_run:
            out_dir.mkdir(parents=True, exist_ok=True)
            target = out_dir / f"{programme['id']}.json"
            target.write_text(
                json.dumps(programme, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            print(f"  -> {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
