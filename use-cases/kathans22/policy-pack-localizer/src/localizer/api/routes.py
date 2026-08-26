"""Thin HTTP routes over service.py / config.py.

No route computes anything the CLI (__main__.py) or a script could not
already get from the same underlying functions. A route's job is to load
config, call service.py, and shape the response as JSON.
"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from .. import config as config_module
from .. import corelock
from .. import packs
from .. import service
from . import runs as runs_module

router = APIRouter()


class RolloutRequest(BaseModel):
    countries: list[str]
    limit: int | None = None


class AmendmentRequest(BaseModel):
    countries: list[str]


def _generated_country_codes() -> list[str]:
    """Country codes with a complete exported pack on disk, per packs.OUT_DIR.

    A pack "exists" only if every file packs._EXPORT_FILES lists is present
    — the same completeness check packs.generate_pack itself uses before
    treating a pack as already produced (idempotency), so this list never
    reports a half-written pack as generated.
    """
    codes = []
    for code in sorted(config_module.load_all_countries()):
        pack_dir = packs.OUT_DIR / code
        if all((pack_dir / filename).exists() for _, filename in packs._EXPORT_FILES):
            codes.append(code)
    return codes


@router.get("/countries")
def list_countries() -> list[dict]:
    """Every configured country — a data change (a new YAML file) is all it
    takes for one to appear here, per CLAUDE.md rule 5. `annex_summary` is
    counted straight from that country's own YAML, not asserted, so two
    countries with genuinely different annex content show genuinely
    different numbers here."""
    countries = config_module.load_all_countries()
    return [
        {
            "code": country["code"],
            "country": country["country"],
            "language": country["language"],
            "office": country["office"],
            "safeguarding_lead": country["safeguarding_lead"],
            "annex_summary": {
                "legal_instruments": len(country["legal"]),
                "external_reporting_channels": len(country["reporting"]["external"]),
                "escalation_tier_1": country["escalation"]["tier_1"],
            },
        }
        for country in countries.values()
    ]


@router.get("/packs")
def list_packs() -> list[dict]:
    """Every configured country, with whether its pack has actually been
    generated (files present in out/) — not just requested. A generated
    pack carries its own core_hash (recomputed from its export, same as
    /packs/{code}) and links to its exported files under /exports.

    A file existing in out/ does not guarantee it can be safely parsed —
    sections.parse_sections rejects a document a SuperDocs export call
    duplicated (see its docstring), which is a real, observed failure mode,
    not hypothetical. That must surface as one bad row here, never as a
    500 that hides every other country's genuinely fine pack behind it.
    """
    countries = config_module.load_all_countries()
    manifest = config_module.load_manifest()
    generated = set(_generated_country_codes())

    entries = []
    for code, country in countries.items():
        entry = {
            "code": code,
            "country": country["country"],
            "language": country["language"],
            "generated": code in generated,
        }
        if code in generated:
            try:
                verification = service.verify(code, manifest=manifest)
                entry["core_hash"] = corelock.lock(
                    verification["exported_core_sections"], manifest["core_version"], country["language"]
                )["core_hash"]
                entry["exports"] = {fmt: f"/exports/{code}/{filename}" for fmt, filename in packs._EXPORT_FILES}
            except ValueError as exc:
                entry["error"] = str(exc)
        entries.append(entry)
    return entries


@router.get("/packs/{code}")
def get_pack(code: str) -> dict:
    """Re-verify one country's already-generated pack against its locked
    core — the same check packs.verify_pack runs after generation, run
    again here on demand rather than trusting a cached result.

    `core_hash` is recomputed from the pack's own exported core sections,
    through corelock.lock() — the same function lock time and integrity_report
    both use — never a second hashing path."""
    countries = config_module.load_all_countries()
    if code not in countries:
        raise HTTPException(status_code=404, detail=f"No configured country {code!r}.")
    if code not in _generated_country_codes():
        raise HTTPException(status_code=404, detail=f"No generated pack for {code!r} yet.")

    manifest = config_module.load_manifest()
    try:
        verification = service.verify(code, manifest=manifest)
    except ValueError as exc:
        # The file exists but can't be safely parsed as one policy pack —
        # e.g. a SuperDocs export call duplicated it (sections.parse_sections
        # detects this). A named, actionable 422 beats an opaque 500.
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    language = countries[code]["language"]
    core_hash = corelock.lock(
        verification["exported_core_sections"], manifest["core_version"], language
    )["core_hash"]

    return {
        "code": code,
        "passed": verification["passed"],
        "core": verification["core"],
        "unlocalised_annex_sections": verification["unlocalised_annex_sections"],
        "core_hash": core_hash,
    }


@router.get("/integrity")
def integrity_report(countries: str | None = None) -> dict:
    """The core-identity + annex-divergence report: proof, not assertion,
    that protected core text is identical across every generated pack in a
    language and that annexes genuinely diverge per country.

    `countries` is an optional comma-separated filter (e.g. `IN,KE`);
    defaults to every country with a generated pack on disk.
    """
    if countries:
        codes = [code.strip() for code in countries.split(",") if code.strip()]
        missing = [code for code in codes if code not in _generated_country_codes()]
        if missing:
            raise HTTPException(status_code=404, detail=f"No generated pack for {missing!r} yet.")
    else:
        codes = _generated_country_codes()
    if not codes:
        raise HTTPException(status_code=404, detail="No generated packs yet — run a rollout first.")
    return service.integrity_report(codes)


def _reject_unknown_countries(codes: list[str]) -> None:
    unknown = [code for code in codes if code not in config_module.load_all_countries()]
    if unknown:
        label = "country" if len(unknown) == 1 else "countries"
        raise HTTPException(status_code=404, detail=f"Unknown {label}: {unknown!r}")


@router.post("/runs/rollout", status_code=202)
def start_rollout(request: RolloutRequest, background_tasks: BackgroundTasks) -> dict:
    """Kick off core-lock + pack generation for the given countries in the
    background and return immediately with a run id to poll — a rollout can
    legitimately take minutes per country (CLAUDE.md: no aggressive
    timeouts), so the request must not wait on it."""
    _reject_unknown_countries(request.countries)
    run = runs_module.create_run("rollout")
    background_tasks.add_task(runs_module.execute_rollout, run.run_id, request.countries, request.limit)
    return run.to_summary()


@router.post("/runs/amendment", status_code=202)
def start_amendment(request: AmendmentRequest, background_tasks: BackgroundTasks) -> dict:
    """Kick off core re-lock + per-country change-notice generation in the
    background and return immediately with a run id to poll. Zero packs are
    reissued by this — see service.run_amendment."""
    _reject_unknown_countries(request.countries)
    run = runs_module.create_run("amendment")
    background_tasks.add_task(runs_module.execute_amendment, run.run_id, request.countries)
    return run.to_summary()


@router.get("/runs/{run_id}")
def get_run_status(run_id: str) -> dict:
    """Poll a run's status without blocking — a run still `running` is not
    a failed run (CLAUDE.md: SuperDocs calls legitimately take 30s to
    several minutes with no visible progress; that is processing, not a
    crash). `result` is populated once `status` is `done`; `error` once
    `status` is `error`."""
    run = runs_module.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"No run {run_id!r}.")
    return {**run.to_summary(), "result": run.result, "error": run.error}


@router.get("/runs/{run_id}/ledger")
def get_run_ledger(run_id: str) -> dict:
    """The operations this specific run has actually spent so far, step by
    step — not the whole account's cumulative ledger, and not a snapshot
    frozen at the end. `run.ledger` is the same Ledger instance the
    background coroutine is still writing to while the run is `running`,
    sliced from the entry count at the moment this run started (so two
    runs never double-report each other's cost) — polling this while a
    rollout or amendment is still in progress shows entries landing as
    each country's operation actually completes."""
    run = runs_module.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"No run {run_id!r}.")
    entries = run.ledger_entries()
    total_operations = sum(entry["operations"] for entry in entries)
    return {"run_id": run_id, "status": run.status, "entries": entries, "total_operations": total_operations}
