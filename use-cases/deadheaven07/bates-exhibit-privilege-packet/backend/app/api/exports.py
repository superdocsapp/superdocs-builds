from uuid import UUID

import fitz
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.database import get_session
from app.domain.audit import AuditEvent, AuditEventType
from app.domain.bates import BatesAssignment
from app.domain.document import Document
from app.domain.manifest import Manifest, ManifestEntry
from app.domain.packet import Packet
from app.domain.redaction import RedactionStatus
from app.services.packet_builder import PacketBuilderService, get_packet_builder
from app.services.reconciliation import verify_reconciliation

router = APIRouter()


@router.post("/{packet_id}/build")
async def build_packet(
    packet_id: UUID,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    builder: PacketBuilderService = Depends(get_packet_builder),
):
    packet = await session.get(Packet, packet_id)
    if not packet:
        raise HTTPException(status_code=404, detail="Packet not found")

    try:
        result = await builder.build_packet(session, packet_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Packet build failed: {str(e)}") from e

    return {
        "message": "Packet built successfully",
        "final_packet": str(result.final_packet_path),
        "exhibits_dir": str(result.exhibits_dir),
        "exhibit_index": str(result.exhibit_index_path),
        "privilege_log": str(result.privilege_log_path),
        "manifest": str(result.manifest_path),
        "total_pages": result.manifest.total_pages,
        "total_documents": result.manifest.total_documents,
    }


@router.post("/{packet_id}/validate")
async def validate_packet(
    packet_id: UUID,
    session: AsyncSession = Depends(get_session),
    builder: PacketBuilderService = Depends(get_packet_builder),
):
    packet = await session.get(Packet, packet_id)
    if not packet:
        raise HTTPException(status_code=404, detail="Packet not found")

    try:
        validation = await builder.validate_packet(session, packet_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Validation failed: {str(e)}") from e

    session.add(
        AuditEvent(
            packet_id=packet_id,
            event_type=AuditEventType.PACKET_VALIDATED,
            user_id="system",
            event_metadata={
                "valid": validation.get("valid"),
                "errors": validation.get("errors"),
                "warnings": validation.get("warnings"),
            },
        )
    )
    await session.commit()

    return validation


@router.get("/{packet_id}/manifest")
async def get_manifest(packet_id: UUID, session: AsyncSession = Depends(get_session)):
    packet = await session.get(Packet, packet_id)
    if not packet:
        raise HTTPException(status_code=404, detail="Packet not found")

    manifest = await session.execute(select(Manifest).where(Manifest.packet_id == packet_id))
    manifest = manifest.scalars().first()

    if not manifest:
        raise HTTPException(status_code=404, detail="Manifest not found")

    entries_result = await session.execute(
        select(ManifestEntry).where(ManifestEntry.manifest_id == manifest.id)
    )
    entries = entries_result.scalars().all()

    return {
        "id": str(manifest.id),
        "packet_id": str(manifest.packet_id),
        "total_pages": manifest.total_pages,
        "total_documents": manifest.total_documents,
        "bates_start": manifest.bates_start,
        "bates_end": manifest.bates_end,
        "generated_at": manifest.generated_at.isoformat() if manifest.generated_at else None,
        "validation_passed": manifest.validation_passed,
        "validation_details": manifest.validation_details,
        "final_packet_sha256": manifest.final_packet_sha256,
        "final_packet_path": manifest.final_packet_path,
        "entries": [
            {
                "id": str(entry.id),
                "document_id": str(entry.document_id),
                "exhibit_identifier": entry.exhibit_identifier,
                "bates_start": entry.bates_start,
                "bates_end": entry.bates_end,
                "page_count": entry.page_count,
                "original_sha256": entry.original_sha256,
                "processed_sha256": entry.processed_sha256,
                "final_sha256": entry.final_sha256,
                "description": entry.description,
                "privilege_status": entry.privilege_status,
                "privilege_category": entry.privilege_category,
                "privilege_reason": entry.privilege_reason,
                "applied_redactions": entry.applied_redactions,
                "final_file_path": entry.final_file_path,
            }
            for entry in entries
        ],
    }


@router.get("/{packet_id}/download")
async def download_final_packet(packet_id: UUID, session: AsyncSession = Depends(get_session)):
    packet = await session.get(Packet, packet_id)
    if not packet:
        raise HTTPException(status_code=404, detail="Packet not found")

    manifest = await session.execute(select(Manifest).where(Manifest.packet_id == packet_id))
    manifest = manifest.scalars().first()

    if not manifest or not manifest.final_packet_path:
        raise HTTPException(status_code=404, detail="Final packet not built yet")

    from app.config import get_settings

    settings = get_settings()
    file_path = settings.final_path / manifest.final_packet_path

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Final packet file not found")

    session.add(
        AuditEvent(
            packet_id=packet_id,
            event_type=AuditEventType.PACKET_EXPORTED,
            user_id="system",
            event_metadata={"filename": file_path.name},
        )
    )
    await session.commit()

    return FileResponse(
        path=file_path,
        filename=f"{packet.name.replace(' ', '_')}_packet.pdf",
        media_type="application/pdf",
    )


@router.get("/{packet_id}/download/{file_type}")
async def download_packet_component(
    packet_id: UUID,
    file_type: str,
    session: AsyncSession = Depends(get_session),
):
    packet = await session.get(Packet, packet_id)
    if not packet:
        raise HTTPException(status_code=404, detail="Packet not found")

    manifest = await session.execute(select(Manifest).where(Manifest.packet_id == packet_id))
    manifest = manifest.scalars().first()

    if not manifest:
        raise HTTPException(status_code=404, detail="Packet not built yet")

    from app.config import get_settings

    settings = get_settings()

    file_map = {
        "exhibit_index": manifest.final_packet_path.replace(
            "final_packet.pdf", "exhibit_index.pdf"
        ),
        "privilege_log": manifest.final_packet_path.replace(
            "final_packet.pdf", "privilege_log.pdf"
        ),
    }

    if file_type not in file_map:
        raise HTTPException(status_code=400, detail=f"Unknown file type: {file_type}")

    file_path = settings.final_path / file_map[file_type]

    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"{file_type} not found")

    return FileResponse(
        path=file_path,
        filename=file_path.name,
        media_type="application/pdf",
    )


@router.get("/{packet_id}/exhibits")
async def list_exhibits(packet_id: UUID, session: AsyncSession = Depends(get_session)):
    packet = await session.get(Packet, packet_id)
    if not packet:
        raise HTTPException(status_code=404, detail="Packet not found")

    manifest = await session.execute(select(Manifest).where(Manifest.packet_id == packet_id))
    manifest = manifest.scalars().first()

    if not manifest:
        raise HTTPException(status_code=404, detail="Packet not built yet")

    entries_result = await session.execute(
        select(ManifestEntry).where(ManifestEntry.manifest_id == manifest.id)
    )
    entries = entries_result.scalars().all()

    from app.config import get_settings

    settings = get_settings()

    exhibits = []
    for entry in entries:
        file_path = settings.final_path / entry.final_file_path
        exhibits.append(
            {
                "exhibit_identifier": entry.exhibit_identifier,
                "bates_range": f"{entry.bates_start} - {entry.bates_end}",
                "page_count": entry.page_count,
                "description": entry.description,
                "file_exists": file_path.exists(),
                "file_path": str(file_path.relative_to(settings.final_path)),
                "sha256": entry.final_sha256,
            }
        )

    return {"exhibits": exhibits}


@router.post("/{packet_id}/verify")
async def verify_packet(
    packet_id: UUID,
    session: AsyncSession = Depends(get_session),
):
    settings = get_settings()
    checks: list[dict] = []

    def add_check(name: str, passed: bool, detail: str = "") -> None:
        checks.append({"name": name, "passed": passed, "detail": detail})

    packet = await session.get(Packet, packet_id)
    if not packet:
        raise HTTPException(status_code=404, detail="Packet not found")

    manifest_result = await session.execute(
        select(Manifest)
        .where(Manifest.packet_id == packet_id)
        .options(selectinload(Manifest.entries))
    )
    manifest = manifest_result.scalars().first()
    if not manifest:
        return {
            "status": "NOT_BUILT",
            "checks": [{"name": "manifest_exists", "passed": False, "detail": "No manifest found"}],
        }

    bates_result = await session.execute(
        select(BatesAssignment)
        .where(BatesAssignment.packet_id == packet_id)
        .order_by(BatesAssignment.bates_number)
    )
    bates_list = list(bates_result.scalars().all())

    docs_result = await session.execute(
        select(Document)
        .where(Document.packet_id == packet_id)
        .order_by(Document.display_order)
    )
    documents = list(docs_result.scalars().all())

    final_packet_path = settings.final_path / manifest.final_packet_path if manifest.final_packet_path else None

    add_check(
        "manifest_exists",
        True,
        f"Manifest with {len(manifest.entries)} entries",
    )

    all_artifacts_exist = True
    if final_packet_path and final_packet_path.exists():
        add_check("final_packet_exists", True, str(final_packet_path))
    else:
        add_check("final_packet_exists", False, "final_packet.pdf missing")
        all_artifacts_exist = False

    exhibits_dir = settings.final_path / str(packet_id) / "exhibits"
    for entry in manifest.entries:
        exhibit_path = settings.final_path / entry.final_file_path if entry.final_file_path else None
        if exhibit_path and exhibit_path.exists():
            add_check(f"exhibit_{entry.exhibit_identifier}_exists", True)
        else:
            add_check(f"exhibit_{entry.exhibit_identifier}_exists", False, "file missing")
            all_artifacts_exist = False

    index_path = settings.final_path / str(packet_id) / "exhibit_index.pdf"
    add_check("exhibit_index_exists", index_path.exists())
    log_path = settings.final_path / str(packet_id) / "privilege_log.pdf"
    add_check("privilege_log_exists", log_path.exists())
    manifest_json_path = settings.final_path / str(packet_id) / "manifest.json"
    add_check("manifest_json_exists", manifest_json_path.exists())

    if bates_list:
        numbers = [ba.bates_number for ba in bates_list]
        expected = list(range(packet.bates_start_number, packet.bates_start_number + len(numbers)))
        add_check(
            "bates_contiguous",
            numbers == expected,
            f"Expected {expected[:3]}...{expected[-3:]}, got {numbers[:3]}...{numbers[-3:]}" if len(expected) > 6 else f"Expected {expected}, got {numbers}",
        )
        add_check(
            "bates_no_duplicates",
            len(numbers) == len(set(numbers)),
            f"{len(numbers)} assignments, {len(set(numbers))} unique",
        )
    else:
        add_check("bates_contiguous", False, "No Bates assignments")
        add_check("bates_no_duplicates", False, "No Bates assignments")

    if manifest.final_packet_sha256 and final_packet_path and final_packet_path.exists():
        import hashlib

        sha256 = hashlib.sha256()
        with open(final_packet_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        actual_hash = sha256.hexdigest()
        add_check(
            "final_packet_hash",
            actual_hash == manifest.final_packet_sha256,
            f"expected {manifest.final_packet_sha256[:16]}..., got {actual_hash[:16]}...",
        )
    elif final_packet_path and final_packet_path.exists():
        add_check("final_packet_hash", True, "No hash recorded; file exists")

    if manifest.entries:
        entry_errors = []
        for entry in manifest.entries:
            if not entry.final_file_path:
                entry_errors.append(f"{entry.exhibit_identifier}: no file path")
                continue
            exhibit_path = settings.final_path / entry.final_file_path
            if not exhibit_path.exists():
                entry_errors.append(f"{entry.exhibit_identifier}: file missing")
                continue
            try:
                doc = fitz.open(exhibit_path)
                actual_pages = len(doc)
                doc.close()
            except Exception:
                entry_errors.append(f"{entry.exhibit_identifier}: cannot read PDF")
                continue
            if actual_pages != entry.page_count:
                entry_errors.append(
                    f"{entry.exhibit_identifier}: expected {entry.page_count} pages, got {actual_pages}"
                )
        add_check(
            "page_counts_match",
            len(entry_errors) == 0,
            "; ".join(entry_errors) if entry_errors else "All exhibits verified",
        )
    else:
        add_check("page_counts_match", False, "No manifest entries")

    if manifest.entries:
        recon = verify_reconciliation(
            manifest_entries=[
                {
                    "exhibit_identifier": e.exhibit_identifier,
                    "bates_start": e.bates_start,
                    "bates_end": e.bates_end,
                    "page_count": e.page_count,
                }
                for e in manifest.entries
            ],
            total_packet_pages=manifest.total_pages,
            packet_prefix=packet.bates_prefix,
        )
        add_check(
            "reconciliation",
            recon.is_valid,
            f"total={manifest.total_pages}, bates_pages={recon.sum_bates_pages}",
        )
    else:
        add_check("reconciliation", False, "No entries to reconcile")

    all_passed = all(c["passed"] for c in checks)
    status = "VERIFIED" if all_passed else "FAILED"

    session.add(
        AuditEvent(
            packet_id=packet_id,
            event_type=AuditEventType.PACKET_VALIDATED,
            user_id="system",
            event_metadata={
                "verification_result": status,
                "checks_passed": sum(1 for c in checks if c["passed"]),
                "checks_failed": sum(1 for c in checks if not c["passed"]),
            },
        )
    )
    await session.commit()

    return {
        "status": status,
        "packet_id": str(packet_id),
        "page_count": manifest.total_pages,
        "bates_start": manifest.bates_start,
        "bates_end": manifest.bates_end,
        "exhibits": len(manifest.entries),
        "checks": checks,
    }
