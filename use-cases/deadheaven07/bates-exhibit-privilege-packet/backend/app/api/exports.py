from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from uuid import UUID

from app.database import get_session
from app.domain.packet import Packet
from app.domain.manifest import Manifest, ManifestEntry
from app.domain.audit import AuditEvent, AuditEventType
from app.services.packet_builder import PacketBuilderService, get_packet_builder

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
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Packet build failed: {str(e)}")

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
        raise HTTPException(status_code=500, detail=f"Validation failed: {str(e)}")

    session.add(AuditEvent(
        packet_id=packet_id,
        event_type=AuditEventType.PACKET_VALIDATED,
        user_id="system",
        event_metadata={
            "valid": validation.get("valid"),
            "errors": validation.get("errors"),
            "warnings": validation.get("warnings"),
        },
    ))
    await session.commit()

    return validation


@router.get("/{packet_id}/manifest")
async def get_manifest(packet_id: UUID, session: AsyncSession = Depends(get_session)):
    packet = await session.get(Packet, packet_id)
    if not packet:
        raise HTTPException(status_code=404, detail="Packet not found")

    manifest = await session.execute(
        select(Manifest).where(Manifest.packet_id == packet_id)
    )
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

    manifest = await session.execute(
        select(Manifest).where(Manifest.packet_id == packet_id)
    )
    manifest = manifest.scalars().first()

    if not manifest or not manifest.final_packet_path:
        raise HTTPException(status_code=404, detail="Final packet not built yet")

    from app.config import get_settings
    settings = get_settings()
    file_path = settings.final_path / manifest.final_packet_path

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Final packet file not found")

    session.add(AuditEvent(
        packet_id=packet_id,
        event_type=AuditEventType.PACKET_EXPORTED,
        user_id="system",
        event_metadata={"filename": file_path.name},
    ))
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

    manifest = await session.execute(
        select(Manifest).where(Manifest.packet_id == packet_id)
    )
    manifest = manifest.scalars().first()

    if not manifest:
        raise HTTPException(status_code=404, detail="Packet not built yet")

    from app.config import get_settings
    settings = get_settings()

    file_map = {
        "exhibit_index": manifest.final_packet_path.replace("final_packet.pdf", "exhibit_index.pdf"),
        "privilege_log": manifest.final_packet_path.replace("final_packet.pdf", "privilege_log.pdf"),
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

    manifest = await session.execute(
        select(Manifest).where(Manifest.packet_id == packet_id)
    )
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
        exhibits.append({
            "exhibit_identifier": entry.exhibit_identifier,
            "bates_range": f"{entry.bates_start} - {entry.bates_end}",
            "page_count": entry.page_count,
            "description": entry.description,
            "file_exists": file_path.exists(),
            "file_path": str(file_path.relative_to(settings.final_path)),
            "sha256": entry.final_sha256,
        })

    return {"exhibits": exhibits}