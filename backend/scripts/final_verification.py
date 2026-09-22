"""Final-verification helper (Phase 10). READ-ONLY.

Run from ``backend/`` with the venv active::

    python scripts/final_verification.py            # human-readable
    python scripts/final_verification.py --json     # machine-readable

It checks what can be checked automatically and *looks for evidence* of the
verifications that must be performed for real. It never runs a scan, a
browser, a model, a correlation, a recommendation or a retest, never writes
to MongoDB and never edits a file. It cannot mark a real-world verification
as done: it only reports whether the database contains a record that such a
run happened, and records produced by the test-suite fakes (labelled
``fake``) never count.

The AI items are judged against whichever provider ``AI_PROVIDER`` selects,
read from configuration. They report one of:

``NOT CONFIGURED``  the provider is unsupported, or its key/model is unset,
                    so the platform could not call it at all;
``CONFIGURED``      it could be called, but no completed run is stored;
``REAL VERIFIED``   a stored record for *that* provider proves a real call;
``FAIL``            every stored attempt for that provider failed.

A record counts only when its own ``provider`` field matches the configured
one, so a Gemini run never passes as an OpenAI verification, or the reverse.

Exit code 1 when an automated check fails; "not verified" items do not
change the exit code - they are the to-do list for the final pass.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib
import json
import pkgutil
import subprocess
import sys
from pathlib import Path
from typing import Any

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from pymongo import AsyncMongoClient  # noqa: E402
from pymongo.errors import PyMongoError  # noqa: E402

import app.models as models_pkg  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.engines.reporting.redaction import find_leaks, known_secrets  # noqa: E402
from app.engines.reporting.traceability import audit  # noqa: E402
from app.services.report_service import ReportService  # noqa: E402

EXPECTED_COLLECTIONS = {
    "targets", "qa_runs", "security_runs", "assessments", "evidence", "ai_analysis_logs",
    "correlation_groups", "issues", "recommendations", "retests", "reports",
}
MINI_ECOMMERCE = Path(r"C:\Users\RSS\Desktop\mini-ecommerce-demo")
MINI_ECOMMERCE_HEAD = "c736eca75fd381faa4c2a70d76bbe621aaa5c35c"

PASS, FAIL, NOT_VERIFIED, MANUAL, FOUND = "PASS", "FAIL", "NOT VERIFIED", "MANUAL", "EVIDENCE FOUND"
#: AI-specific outcomes. "CONFIGURED" means the platform could call the
#: provider but no real completed run is stored yet; "REAL VERIFIED" means a
#: stored record proves one happened; "FAILED" means every stored attempt for
#: the configured provider failed. This script never calls a provider - doing
#: so would verify the script, not the platform.
CONFIGURED, REAL_VERIFIED, NOT_CONFIGURED = "CONFIGURED", "REAL VERIFIED", "NOT CONFIGURED"

#: The provider names ``app.api.dependencies.get_ai_provider`` accepts. Any
#: other value resolves to ``UnconfiguredProvider`` at runtime, so this script
#: must report it as NOT CONFIGURED rather than assuming a default.
SUPPORTED_AI_PROVIDERS = ("openai", "gemini")


def ai_provider_configuration(settings) -> tuple[str, bool, str]:
    """(provider name, is it callable, why not).

    Read from configuration only. A provider needs both a key and a model:
    either one missing makes analysis fail with a configuration error, which
    is a different thing from "configured but never run".
    """
    name = (settings.ai_provider or "").strip().lower()
    if name not in SUPPORTED_AI_PROVIDERS:
        return name or "(unset)", False, (
            f"AI_PROVIDER={settings.ai_provider!r} is not one of {', '.join(SUPPORTED_AI_PROVIDERS)}"
        )
    key = getattr(settings, f"{name}_api_key", "") or ""
    model = getattr(settings, f"{name}_model", "") or ""
    missing = [label for label, value in ((f"{name.upper()}_API_KEY", key), (f"{name.upper()}_MODEL", model)) if not value.strip()]
    if missing:
        return name, False, f"{' and '.join(missing)} not set"
    return name, True, f"model {model}"


def expected_indexes() -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for info in pkgutil.iter_modules(models_pkg.__path__):
        module = importlib.import_module(f"app.models.{info.name}")
        name = getattr(module, "COLLECTION_NAME", None)
        if name:
            result[name] = {v for k, v in vars(module).items() if k.endswith("INDEX_NAME") and isinstance(v, str)}
    return result


def git(*args: str, cwd: Path) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False).stdout.strip()


async def run() -> list[dict[str, Any]]:
    settings = get_settings()
    client = AsyncMongoClient(settings.mongodb_uri, serverSelectionTimeoutMS=settings.mongodb_timeout_ms, tz_aware=False)
    db = client[settings.mongodb_database]
    items: list[dict[str, Any]] = []

    def add(number: int, name: str, status: str, detail: str) -> None:
        items.append({"item": number, "check": name, "status": status, "detail": detail})

    add(1, "Full pytest regression", MANUAL, "Run: python -m pytest -q --junitxml=%TEMP%\\final.xml (all tests).")

    # Evidence of real runs: fake-labelled records never count.
    real_qa = await db["qa_runs"].count_documents({"metadata.browser": {"$ne": "fake"}, "scope.purpose": {"$exists": False}})
    real_sec = await db["security_runs"].count_documents({"engine_metadata.engine_version": {"$ne": "fake"}, "scope.purpose": {"$exists": False}})
    completed = await db["assessments"].count_documents({"status": "completed"})
    add(2, "Real end-to-end assessment", FOUND if completed and real_qa and real_sec else NOT_VERIFIED,
        f"{completed} completed assessment(s); {real_qa} non-fake QA run(s), {real_sec} non-fake security run(s). "
        "Confirm in the final pass that one assessment ran against the running Mini E-Commerce with ZAP up.")

    # --- AI: judged against the provider this installation is configured to
    # use, not against one hardcoded vendor. A record only counts when its
    # own "provider" field matches, so a Gemini run never passes as an
    # OpenAI verification, or the other way round.
    provider, callable_now, provider_detail = ai_provider_configuration(settings)
    per_provider = {
        name: {
            "completed": await db["ai_analysis_logs"].count_documents({"provider": name, "status": "completed"}),
            "attempts": await db["ai_analysis_logs"].count_documents({"provider": name}),
        }
        for name in SUPPORTED_AI_PROVIDERS
    }
    others = "; ".join(
        f"{name}: {counts['completed']}/{counts['attempts']} completed"
        for name, counts in per_provider.items()
        if name != provider and counts["attempts"]
    )
    configured_completed = per_provider.get(provider, {}).get("completed", 0)
    configured_attempts = per_provider.get(provider, {}).get("attempts", 0)
    last_ai = await db["ai_analysis_logs"].find_one({"provider": provider}, sort=[("created_at", -1)])
    last_detail = (
        f"; latest {provider} attempt: {last_ai.get('status')} "
        f"({(last_ai.get('error') or {}).get('category', '-')})" if last_ai else ""
    )

    if not callable_now:
        ai_status = NOT_CONFIGURED
    elif configured_completed:
        ai_status = REAL_VERIFIED
    elif configured_attempts:
        ai_status = FAIL          # every stored attempt for this provider failed
    else:
        ai_status = CONFIGURED
    add(3, f"Real AI analysis (AI_PROVIDER={provider})", ai_status,
        f"{provider_detail}; {configured_completed} completed of {configured_attempts} attempt(s) for {provider}"
        + last_detail
        + (f". Other providers on record - {others}" if others else "")
        + (". Configured but no real analysis is stored yet." if ai_status == CONFIGURED else ""))

    issue_count = await db["issues"].count_documents({})
    real_corr = await db["assessments"].count_documents({"correlation.status": "completed", "correlation.ai_analysis_id": {"$ne": None}})
    add(4, "Real correlation", FOUND if issue_count else NOT_VERIFIED,
        f"{issue_count} issue(s) stored; {real_corr} correlation(s) used an AI analysis. "
        "Only counts as real when that analysis is a real one for the configured provider (item 3).")

    real_recs = await db["recommendations"].count_documents({})
    analysis_ids = [
        x["analysis_id"]
        async for x in db["ai_analysis_logs"].find({"provider": provider, "status": "completed"}, {"analysis_id": 1})
    ]
    real_rec = await db["recommendations"].count_documents({"ai_analysis_id": {"$in": analysis_ids}}) if analysis_ids else 0
    if not callable_now:
        rec_status = NOT_CONFIGURED
    elif real_rec:
        rec_status = REAL_VERIFIED
    else:
        rec_status = CONFIGURED if configured_completed or not real_recs else NOT_VERIFIED
    add(5, "Real recommendation generation", rec_status,
        f"{real_recs} recommendation(s) stored, {real_rec} generated from a completed {provider} analysis.")

    for number, engine, field, fake in ((6, "qa", "metadata.browser", "fake"), (7, "security", "engine_metadata.engine_version", "fake")):
        collection = db[f"{engine}_runs"]
        real_runs = [str(x["_id"]) async for x in collection.find({"scope.purpose": "retest", field: {"$ne": fake}}, {"_id": 1})]
        real_retests = await db["retests"].count_documents({"status": "completed", "source_run_ids": {"$in": real_runs}}) if real_runs else 0
        add(number, f"Real {engine.upper()} retest", FOUND if real_retests else NOT_VERIFIED,
            f"{real_retests} completed retest(s) whose raw {engine} run is not fake-labelled.")

    # Reports: ownership, artifacts, secrets.
    root = Path(settings.reports_root).resolve()
    secrets = known_secrets(settings)
    problems: list[str] = []
    reports = [r async for r in db["reports"].find({})]
    for r in reports:
        if not await db["assessments"].find_one({"_id": __import__("bson").ObjectId(r["assessment_id"])}):
            problems.append(f"{r['report_id']}: assessment {r['assessment_id']} missing")
        for fmt, art in (r.get("artifacts") or {}).items():
            path = (root / art.get("path", "")).resolve()
            if not path.is_file():
                problems.append(f"{r['report_id']}.{fmt}: file missing")
                continue
            data = path.read_bytes()
            if hashlib.sha256(data).hexdigest() != art.get("sha256"):
                problems.append(f"{r['report_id']}.{fmt}: SHA-256 mismatch")
            leaks = find_leaks(data.decode("utf-8" if fmt == "html" else "latin-1", "replace"), secrets)
            if leaks:
                problems.append(f"{r['report_id']}.{fmt}: secret patterns {leaks}")
    completed_reports = sum(1 for r in reports if r.get("status") == "completed")
    add(8, "Report generation", (FAIL if problems else (PASS if completed_reports else NOT_VERIFIED)),
        f"{completed_reports} completed report(s); " + ("; ".join(problems[:10]) or "files present, hashes match, no secret patterns"))

    add(9, "Real browser audit", MANUAL, "Open every page (Dashboard, Targets, QA, Security, Assessments, Assessment Detail) "
        "in a real browser against the real backend and check each section, including Reports / HTML / PDF.")

    names = set(await db.list_collection_names())
    extra, missing = sorted(names - EXPECTED_COLLECTIONS), sorted(EXPECTED_COLLECTIONS - names)
    # Name the server this URI actually reached. "localhost" resolves to both
    # ::1 and 127.0.0.1, so on a machine where a second MongoDB publishes the
    # IPv6 address the two are different servers and the client's resolver,
    # not this configuration, decides which one is used. Recording the
    # version and host makes that visible instead of silent.
    try:
        build = await client.admin.command("buildInfo")
        status = await client.admin.command("serverStatus")
        reached = f"reached mongod {build.get('version')} on host {status.get('host')} via {settings.mongodb_uri}"
    except PyMongoError as exc:  # noqa: BLE001 - reported, never raised
        reached = f"could not identify the server behind {settings.mongodb_uri}: {type(exc).__name__}"
    add(10, "Independent MongoDB audit (collections)", FAIL if extra else PASS,
        f"{reached}; database {settings.mongodb_database}; "
        f"unexpected: {extra or 'none'}; not yet created: {missing or 'none'}")

    index_problems = []
    for collection, wanted in expected_indexes().items():
        present = set((await db[collection].index_information()).keys()) if collection in names else set()
        if collection in names and wanted - present:
            index_problems.append(f"{collection}: missing {sorted(wanted - present)}")
    add(11, "Index verification", FAIL if index_problems else PASS, "; ".join(index_problems) or "all declared indexes present")

    service = ReportService(db=db, settings=settings)
    broken: list[str] = []
    checked = 0
    async for assessment in db["assessments"].find({"status": "completed"}):
        result = audit(await service._load(assessment))  # read-only loader shared with ReportService
        checked += 1
        if not result.ok:
            broken.append(f"{assessment['_id']}: " + "; ".join(f"{e.relationship} {e.source}->{e.reference}" for e in result.errors[:3]))
    add(12, "Traceability audit", FAIL if broken else PASS, f"{checked} completed assessment(s) audited; " + (" | ".join(broken) or "no broken references"))

    # Tracked files plus untracked-but-not-ignored ones (most work is not committed yet).
    tracked = git("ls-files", cwd=BACKEND.parent).splitlines() + git("ls-files", "--others", "--exclude-standard", cwd=BACKEND.parent).splitlines()
    leaked, synthetic = [], []
    for rel in tracked:
        path = BACKEND.parent / rel
        if path.suffix.lower() in {".png", ".jpg", ".pdf", ".ico", ".woff", ".woff2"} or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        hits = [h for h in find_leaks(text, secrets) if h in ("openai_key", "jwt", "configured_secret", "url_credentials")]
        # Redaction tests deliberately contain synthetic secret-shaped strings; there only
        # a *configured* (real) secret value counts as a leak.
        if rel.startswith("backend/tests/") and "configured_secret" not in hits:
            if hits:
                synthetic.append(rel)
            continue
        if hits:
            leaked.append(f"{rel}: {hits}")
    add(13, "Security / secret scan (repo files not git-ignored + report files)", FAIL if leaked else PASS,
        f"{len(tracked)} file(s) scanned; " + ("; ".join(leaked[:10]) or "no high-confidence secret patterns and no configured secret values")
        + (f" ({len(synthetic)} test file(s) hold synthetic secret-shaped fixtures, checked for real values only)" if synthetic else ""))

    status = git("status", "--porcelain", cwd=MINI_ECOMMERCE)
    head = git("rev-parse", "HEAD", cwd=MINI_ECOMMERCE)
    add(14, "Mini E-Commerce immutability", PASS if (not status and head == MINI_ECOMMERCE_HEAD) else FAIL,
        f"HEAD {head or '?'}; working tree {'clean' if not status else 'CHANGED: ' + status[:200]}")
    await client.close()
    return items


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    items = asyncio.run(run())
    if args.json:
        print(json.dumps(items, indent=2))
    else:
        for item in items:
            print(f"{item['item']:>2}. [{item['status']:<14}] {item['check']}\n      {item['detail']}")
    return 1 if any(i["status"] == FAIL for i in items) else 0


if __name__ == "__main__":
    raise SystemExit(main())
