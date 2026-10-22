from __future__ import annotations

import asyncio
from pathlib import Path

from redline.config import load_settings
from redline.core.negotiation import NegotiationService
from redline.core.store import Store
from redline.slack.simulator import InMemoryMessenger, TwoWorkspaceSimulator
from redline.superdocs.client import SuperDocsClient
from redline.superdocs.fake import FakeSuperDocs
from redline.superdocs.transport import HTTPTransport

DEMO_DIR = Path(__file__).resolve().parent
SOURCE_DOC = DEMO_DIR / "Acme_Globex_MSA.docx"
OUTPUT_DIR = DEMO_DIR / "output"


def _print_channel(sim: TwoWorkspaceSimulator, channel: str, label: str) -> None:
    messages = sim.messenger.channels.get(channel, [])
    if not messages:
        print(f"  [{label}] (no messages)")
        return
    latest = messages[-1]
    print(f"  [{label}] {latest.text.splitlines()[0]}")


async def main() -> None:
    if not SOURCE_DOC.exists():
        raise SystemExit(
            f"{SOURCE_DOC} is missing -- run `uv run python scripts/make_demo_docs.py` first"
        )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    db_path = OUTPUT_DIR / "demo.db"
    db_path.unlink(missing_ok=True)
    # The demo simulates two separate companies, so it pins its own topology instead of
    # inheriting whatever .env holds. A live single-workspace setup (both team IDs equal,
    # sides pinned per user) is perfectly valid for running the Slack app, but it would
    # collapse the demo's two actors into one side and break the walkthrough. It also
    # forces the fake transport: the demo must never spend a real API quota or need a key.
    settings = load_settings().model_copy(
        update={
            "database_path": str(db_path),
            "fake_mode": True,
            "vendor_team_id": "T_DEMO_VENDOR",
            "customer_team_id": "T_DEMO_CUSTOMER",
            "vendor_internal_channel": "C_DEMO_VENDOR_INTERNAL",
            "customer_internal_channel": "C_DEMO_CUSTOMER_INTERNAL",
            "shared_channel": "C_DEMO_SHARED",
            "side_override_users": "",
        }
    )

    store = Store(settings.database_path)
    if settings.fake_mode:
        transport = FakeSuperDocs()
        print("running against FakeSuperDocs (FAKE_MODE=true) -- no live key, no cost\n")
    else:
        transport = HTTPTransport(settings.superdocs_base_url, settings.superdocs_api_key)
        print(f"running against the real SuperDocs API at {settings.superdocs_base_url}\n")
    client = SuperDocsClient(transport)
    messenger = InMemoryMessenger()
    service = NegotiationService(settings, store, client, messenger)
    sim = TwoWorkspaceSimulator(service=service, settings=settings)

    print("=== 1. vendor shares the MSA into the shared Slack Connect channel ===")
    contract_bytes = SOURCE_DOC.read_bytes()
    deal = await sim.send_file_share(
        "vendor", SOURCE_DOC.name, contract_bytes, deal_name="Acme-Globex MSA"
    )
    deal_id = deal["deal_id"]
    _print_channel(sim, settings.shared_channel, "SHARED")

    print("\n=== 2. vendor's lawyer leaves an internal note (never meant for shared) ===")
    secret = "our real walkaway number on the liability cap is $250k -- do not reveal this"
    await service.add_internal_note(deal_id, "vendor", "vendor-lawyer", secret)
    _print_channel(sim, settings.vendor_internal_channel, "VENDOR INTERNAL")

    print("\n=== 3. deliberate leak attempt: instruction sent from the INTERNAL channel ===")
    try:
        await service.propose(
            deal_id,
            "vendor",
            "U_VENDOR",
            "Cap liability at $250k, our real walkaway number, in the liability section",
            source_channel_id=settings.vendor_internal_channel,
        )
    except Exception as exc:  # noqa: BLE001 - demonstrating the boundary guard, not handling it
        print(f"  BLOCKED as expected: {exc}")
    _print_channel(sim, settings.vendor_internal_channel, "VENDOR INTERNAL (after blocked attempt)")

    print("\n=== 4. vendor proposes a legitimate edit from the shared channel ===")
    job = await sim.run_command(
        "vendor", f"propose {deal_id} Cap liability at $50k in the liability section"
    )
    _print_channel(sim, settings.shared_channel, "SHARED")

    proposal = service.store.proposals_for_job(job["job_id"])[0]
    print(f"\n=== 5. both sides review and approve proposal {proposal.id} ===")
    await sim.click("vendor", proposal.id, "approve")
    result = await sim.click("customer", proposal.id, "approve")
    print(f"  resolved: {result}")
    _print_channel(sim, settings.shared_channel, "SHARED (after commit)")

    print("\n=== 6. customer proposes a second round; vendor rejects one change with feedback ===")
    instruction2 = "Delete the section on Termination; add audit rights after liability"
    job2 = await sim.run_command("customer", f"propose {deal_id} {instruction2}")
    proposals2 = service.store.proposals_for_job(job2["job_id"])
    for index, p in enumerate(proposals2):
        decision = "approve" if index == 0 else "reject"
        await sim.click("vendor", p.id, decision)
        await sim.click("customer", p.id, decision)
    _print_channel(sim, settings.shared_channel, "SHARED (after second round)")

    print("\n=== 6b. attaching a supporting document (multi-document) ===")
    amendment = DEMO_DIR / "Acme_Globex_Amendment_1.docx"
    if amendment.exists():
        await sim.send_file_share(
            "customer",
            amendment.name,
            amendment.read_bytes(),
            attach_to_deal_id=deal_id,
            role="amendment",
        )
        docs = service.list_documents(deal_id)
        print(f"  documents now on this deal: {[d.filename for d in docs]}")
        _print_channel(sim, settings.shared_channel, "SHARED")

    print("\n=== 6c. boundary-aware search ===")
    shared_hits = service.search(
        deal_id, "liability", source_channel_id=settings.shared_channel, side="vendor"
    )
    print(f"  '/redline search liability' from SHARED  -> {len(shared_hits)} hit(s)")
    for hit in shared_hits[:3]:
        print(f"      [{hit.kind}] {hit.label}")
    leaked = service.search(
        deal_id, "walkaway", source_channel_id=settings.shared_channel, side="vendor"
    )
    internal = service.search(
        deal_id, "walkaway", source_channel_id=settings.vendor_internal_channel, side="vendor"
    )
    print(f"  'walkaway' from SHARED           -> {len(leaked)} hit(s) (internal notes hidden)")
    print(f"  'walkaway' from VENDOR INTERNAL  -> {len(internal)} hit(s) (own notes visible)")

    print("\n=== 7. exporting the clean current version and the lawyer-facing redline ===")
    clean = await service.export_clean(deal_id)
    redline = await service.export_redline(deal_id)
    (OUTPUT_DIR / clean.filename).write_bytes(clean.content)
    (OUTPUT_DIR / redline.filename).write_bytes(redline.content)
    print(f"  wrote {OUTPUT_DIR / clean.filename}")
    print(f"  wrote {OUTPUT_DIR / redline.filename}")

    print("\n=== 8. full audit trail ===")
    for line in service.history_lines(deal_id):
        print(f"  {line}")

    print("\n=== 9. killing the process mid-negotiation and resuming from the same database ===")
    job3 = await service.propose(
        deal_id,
        "vendor",
        "U_VENDOR",
        "Add a data protection clause after confidentiality",
        source_channel_id=settings.shared_channel,
    )
    print(f"  job {job3.job_id} created, state={job3.state!r} -- 'crashing' before driving it")
    store2 = Store(settings.database_path)
    client2 = SuperDocsClient(transport)  # SuperDocs itself is unaffected by our local crash
    service2 = NegotiationService(settings, store2, client2, messenger)
    await service2.recover_pending()
    recovered = store2.get_job(job3.job_id)
    print(f"  recovered on a fresh process: job {recovered.job_id} state={recovered.state!r}")

    print("\ndemo complete.")


if __name__ == "__main__":
    asyncio.run(main())
