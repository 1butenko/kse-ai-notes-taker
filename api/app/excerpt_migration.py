"""One-off migration: excerpts become references to their proposal instead of PDF files.

Approving a proposal used to cut its pages into `<course>/excerpts/<session>/<name>.pdf`. An
excerpt is now `<course>/excerpts/<proposal id>` and is cut from its book when viewed (see
`excerpt_ref`). For every course this renames the excerpts in plan.json and in the runs that
froze the plan, so their resume check and "readings changed" fingerprint stay valid, then
deletes the cut files.

Stop the API and worker first, then run it from api/ (or in the api container):

    uv run python -m app.excerpt_migration [--uploads DIR] [--dry-run]

Running it again changes nothing.
"""

import argparse
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError

from app.notes import load_run, notes_dir
from app.plan import (
    Plan,
    excerpt_ref,
    load_plan,
    materials_fingerprint,
    save_plan,
    session_fingerprint,
)
from app.routers.course_info import generating
from app.worker.artifacts import RunStore
from app.worker.notes import GenerationProvenance, input_fingerprint

COURSE = re.compile(r"^(local|\d+)$")


class Busy(Exception):
    pass


@dataclass
class Report:
    course: str
    renamed: int = 0
    runs: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    freed: int = 0
    # Files under excerpts/ that a session uses with no proposal to describe their pages.
    kept: list[str] = field(default_factory=list)


def rename(plan: Plan, course: str) -> dict[str, str]:
    """Give every excerpt of the plan its reference. Returns old path -> reference."""
    renames = {}
    for proposal in plan.proposals:
        ref = excerpt_ref(course, proposal.id)
        if proposal.excerpt and proposal.excerpt != ref:
            renames[proposal.excerpt] = ref
            proposal.excerpt = ref
    for session in plan.sessions:
        session.files = [renames.get(f, f) for f in session.files]
    plan.unassigned = [renames.get(f, f) for f in plan.unassigned]
    return renames


def run_materials(plan: Plan, session_id: str | None) -> str | None:
    """The fingerprint a run records at admission (see `open_run`)."""
    try:
        return session_fingerprint(plan, session_id) if session_id else materials_fingerprint(plan)
    except StopIteration:
        return None


def migrate_run(course_dir: Path, course: str, directory: Path, dry_run: bool) -> bool:
    """Rename the excerpts of a run's frozen plan and recompute what was hashed from it.

    A fingerprint is only recomputed when it still matched before, so a run that could not be
    resumed (its book changed) stays that way. run.json goes first: if the migration stops in
    between, the next pass still finds the old provenance and finishes the run.
    """
    try:
        run = load_run(course_dir, directory.name)
    except (OSError, ValidationError):
        return False
    if run is None:
        return False
    store = RunStore(directory, run)
    provenance = store.read("provenance.json", GenerationProvenance)
    if provenance is None:
        return False
    old = provenance.plan.model_copy(deep=True)
    if not rename(provenance.plan, course):
        return False
    if dry_run:
        return True
    if run.materials is not None and run.materials == run_materials(old, run.session_id):
        run.materials = run_materials(provenance.plan, run.session_id)
        store.write("run.json", run)
    transcript = provenance.transcript
    if provenance.fingerprint == input_fingerprint(course_dir, old, transcript):
        provenance.fingerprint = input_fingerprint(course_dir, provenance.plan, transcript)
    store.write("provenance.json", provenance)
    return True


def remove_files(course_dir: Path, plan: Plan, report: Report, dry_run: bool) -> None:
    excerpts = course_dir / "excerpts"
    if not excerpts.is_dir():
        return
    used = {f for s in plan.sessions for f in s.files} | set(plan.unassigned)
    for file in sorted(p for p in excerpts.rglob("*") if p.is_file()):
        path = file.relative_to(course_dir.parent).as_posix()
        if path in used:
            report.kept.append(path)
            continue
        report.deleted.append(path)
        report.freed += file.stat().st_size
        if not dry_run:
            file.unlink()
    if dry_run:
        return
    for directory in sorted(excerpts.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if directory.is_dir() and not any(directory.iterdir()):
            directory.rmdir()
    if not any(excerpts.iterdir()):
        excerpts.rmdir()


def migrate_course(course_dir: Path, dry_run: bool) -> Report:
    course = course_dir.name
    report = Report(course)
    runs = notes_dir(course_dir)
    for directory in sorted(runs.iterdir()) if runs.is_dir() else []:
        if directory.is_dir() and migrate_run(course_dir, course, directory, dry_run):
            report.runs.append(directory.name)
    plan = load_plan(course_dir)
    report.renamed = len(rename(plan, course))
    if report.renamed and not dry_run:
        save_plan(course_dir, plan)
    remove_files(course_dir, plan, report, dry_run)
    return report


def migrate(uploads_dir: Path, dry_run: bool = False) -> list[Report]:
    courses = [d for d in sorted(uploads_dir.iterdir()) if d.is_dir() and COURSE.match(d.name)]
    busy = [d.name for d in courses if generating(d)]
    if busy:
        raise Busy(f"Notes are generating for {', '.join(busy)}; stop or wait for them first")
    return [migrate_course(d, dry_run) for d in courses]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Replace cut excerpt PDFs with references.")
    parser.add_argument(
        "--uploads", type=Path, default=Path(os.environ.get("UPLOADS_DIR", "uploads"))
    )
    parser.add_argument("--dry-run", action="store_true", help="report, change nothing")
    args = parser.parse_args(argv)
    if not args.uploads.is_dir():
        print(f"No uploads directory at {args.uploads}", file=sys.stderr)
        return 1
    try:
        reports = migrate(args.uploads, args.dry_run)
    except Busy as error:
        print(error, file=sys.stderr)
        return 1
    verb = "Would delete" if args.dry_run else "Deleted"
    for r in reports:
        if not (r.renamed or r.runs or r.deleted or r.kept):
            continue
        print(
            f"{r.course}: {r.renamed} excerpts renamed, {len(r.runs)} runs updated; "
            f"{verb.lower()} {len(r.deleted)} files ({r.freed / 1e6:.1f} MB)"
        )
        for path in r.kept:
            print(f"  kept {path}: attached with no proposal describing its pages")
    total = sum(r.freed for r in reports)
    print(f"{verb} {sum(len(r.deleted) for r in reports)} excerpt files, {total / 1e6:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
