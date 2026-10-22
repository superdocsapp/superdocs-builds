import hashlib
import json
import logging
import re
import shutil
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import fitz
from pypdf import PdfReader, PdfWriter
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.domain.audit import AuditEvent, AuditEventType
from app.domain.bates import BatesAssignment
from app.domain.document import Document, ProcessingStatus
from app.domain.manifest import Manifest, ManifestEntry
from app.domain.packet import Packet
from app.domain.privilege import PrivilegeStatus
from app.domain.redaction import RedactionCandidate, RedactionStatus
from app.services.redaction import RedactionApplicationService
from app.services.storage import redacted_pdf_path_for, resolve_pdf_source
from app.services.superdocs_integration import SuperDocsIntegrationService, get_superdocs_service
from app.time import utc_now

settings = get_settings()
logger = logging.getLogger(__name__)


@dataclass
class BuildResult:
    final_packet_path: Path
    exhibits_dir: Path
    exhibit_index_path: Path
    privilege_log_path: Path
    manifest_path: Path
    manifest: Manifest


class PacketBuilderService:
    def __init__(self, superdocs: SuperDocsIntegrationService | None = None):
        settings.ensure_directories()
        self.superdocs = superdocs or get_superdocs_service()

    def _format_bates(self, prefix: str, number: int, padding: int) -> str:
        return f"{prefix}{str(number).zfill(padding)}"

    def _calculate_sha256(self, file_path: Path) -> str:
        sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        return sha256.hexdigest()

    def _create_text_pdf(
        self, title: str, lines: list[str], page_size: tuple = (612, 792)
    ) -> bytes:
        doc = fitz.open()
        page = doc.new_page(width=page_size[0], height=page_size[1])
        margin = 54
        y = margin + 10
        page.insert_text((margin, y), title, fontsize=16, fontname="helv", color=(0.1, 0.1, 0.15))
        y += 28

        for line in lines:
            if y > page_size[1] - margin:
                page = doc.new_page(width=page_size[0], height=page_size[1])
                y = margin + 10
            page.insert_text((margin, y), line, fontsize=9, fontname="helv", color=(0.2, 0.2, 0.25))
            y += 14

        data = doc.tobytes()
        doc.close()
        return data

    def _sanitize_description(
        self, description: str | None, redacted_texts: list[str]
    ) -> str | None:
        """Remove redacted terms from a description so the final deliverable
        never exposes content that was redacted (covers, index, manifest)."""
        if not description:
            return description
        safe = description
        for term in redacted_texts:
            if not term:
                continue
            safe = re.sub(re.escape(term), "[REDACTED]", safe, flags=re.IGNORECASE)
        return safe

    def _create_cover_sheet(
        self,
        packet: Packet,
        document: Document,
        bates_start: str,
        bates_end: str,
        exhibit_letter: str,
        description: str | None = None,
    ) -> bytes:
        lines = [
            f"Packet: {packet.name}",
            f"Generated: {utc_now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            f"Bates Range: {bates_start} - {bates_end}",
            f"Description: {description or document.description or 'No description available'}",
            f"Document: {document.original_filename}",
            f"Pages: {document.page_count}",
        ]
        privilege_status = (
            document.privilege_decisions[0].status.value
            if document.privilege_decisions
            else "pending"
        )
        lines.append(f"Privilege Status: {privilege_status}")
        return self._create_text_pdf(f"EXHIBIT {exhibit_letter}", lines)

    def _create_exhibit_index(
        self,
        packet: Packet,
        documents: list[Document],
        manifest_entries: list[ManifestEntry],
    ) -> bytes:
        lines = [
            f"Packet: {packet.name}",
            f"Bates Prefix: {packet.bates_prefix}",
            f"Total Documents: {len(documents)}",
            f"Total Pages: {sum(e.page_count for e in manifest_entries)}",
            "",
            "Exhibit | Bates Range | Description | Pages",
            "-" * 80,
        ]

        for i, (doc, entry) in enumerate(zip(documents, manifest_entries, strict=True)):
            exhibit_letter = chr(65 + i)
            lines.append(
                f"{exhibit_letter} | {entry.bates_start} - {entry.bates_end} | "
                f"{entry.description or doc.original_filename} | {entry.page_count}"
            )

        return self._create_text_pdf("EXHIBIT INDEX", lines)

    def _create_privilege_log(self, packet: Packet, documents: list[Document]) -> bytes:
        lines = [
            f"Packet: {packet.name}",
            f"Generated: {utc_now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "Document | Bates Range | Category | Reason",
            "-" * 80,
        ]

        for doc in documents:
            if (
                doc.privilege_decisions
                and doc.privilege_decisions[0].status == PrivilegeStatus.PRIVILEGED
            ):
                decision = doc.privilege_decisions[0]
                bates_assignments = list(doc.bates_assignments)
                bates_start = bates_assignments[0].bates_label if bates_assignments else "N/A"
                bates_end = bates_assignments[-1].bates_label if bates_assignments else "N/A"
                lines.append(
                    f"{doc.original_filename} | {bates_start} - {bates_end} | "
                    f"{decision.category.value if decision.category else 'other'} | "
                    f"{decision.reason or 'N/A'}"
                )

        return self._create_text_pdf("PRIVILEGE LOG", lines)

    def _stamp_pdf_file(self, input_path: Path, output_path: Path, bates_labels: list[str]) -> None:
        doc = fitz.open(input_path)
        for i, label in enumerate(bates_labels):
            if i >= len(doc):
                break
            page = doc[i]
            rect = page.rect
            x = rect.width - 160
            y = rect.height - 30
            page.insert_text(fitz.Point(x, y), label, fontsize=10, fontname="helv", color=(0, 0, 0))
        doc.save(output_path, garbage=4, deflate=True)
        doc.close()

    def _resolve_source_path(self, document: Document) -> Path | None:
        return resolve_pdf_source(document)

    def _run_validation(
        self,
        packet: Packet,
        documents: list[Document],
        bates_list: list[BatesAssignment],
    ) -> tuple[bool, list[str], list[str]]:
        errors = []
        warnings = []

        bates_list = sorted(bates_list, key=lambda ba: ba.bates_number)

        if not bates_list:
            errors.append("No Bates assignments found")

        bates_numbers = [ba.bates_number for ba in bates_list]
        if len(bates_numbers) != len(set(bates_numbers)):
            errors.append("Duplicate Bates numbers found")

        expected_numbers = list(
            range(packet.bates_start_number, packet.bates_start_number + len(bates_numbers))
        )
        if bates_numbers != expected_numbers:
            errors.append(
                f"Bates numbers have gaps. Expected {expected_numbers}, got {bates_numbers}"
            )

        source_page_count = sum(doc.page_count for doc in documents)
        if len(bates_list) != source_page_count:
            errors.append(
                f"Bates count ({len(bates_list)}) does not match page count ({source_page_count})"
            )

        for doc in documents:
            if doc.processing_status != ProcessingStatus.COMPLETED:
                warnings.append(f"Document {doc.original_filename} not fully processed")

            doc_bates = [ba for ba in bates_list if ba.document_id == doc.id]
            if len(doc_bates) != doc.page_count:
                warnings.append(
                    f"Document {doc.original_filename} has {len(doc_bates)} Bates "
                    f"but {doc.page_count} pages"
                )

        prev_end = None
        for doc in documents:
            doc_bates = sorted(
                (ba for ba in bates_list if ba.document_id == doc.id),
                key=lambda ba: ba.bates_number,
            )
            if not doc_bates:
                continue
            if prev_end is not None and doc_bates[0].bates_number != prev_end + 1:
                errors.append(
                    f"Bates numbers not contiguous across display order: "
                    f"document {doc.original_filename} starts at {doc_bates[0].bates_number}, "
                    f"expected {prev_end + 1}"
                )
            prev_end = doc_bates[-1].bates_number

        return len(errors) == 0, errors, warnings

    def _verify_applied_redactions(self, documents: list[Document]) -> None:
        """Refuse to build if any APPLIED redaction is not verified against its output file."""
        errors = []
        verifier = RedactionApplicationService()
        for document in documents:
            for candidate in document.redaction_candidates:
                if candidate.status != RedactionStatus.APPLIED:
                    continue
                redacted_path = redacted_pdf_path_for(document)
                if redacted_path.exists():
                    verification = verifier.verify_redactions(redacted_path, [candidate])
                    verified = verification.get(str(candidate.id), {}).get("verified", False)
                    if not verified:
                        errors.append(
                            f"Applied redaction '{candidate.matched_text}' on "
                            f"{document.original_filename} is still present in the redacted file"
                        )
                elif not (candidate.approval and candidate.approval.verification_passed):
                    errors.append(
                        f"Applied redaction '{candidate.matched_text}' on "
                        f"{document.original_filename} has no verified redacted file"
                    )
        if errors:
            raise ValueError("Cannot build packet: " + "; ".join(errors))

    async def build_packet(
        self,
        session,
        packet_id: str,
    ) -> BuildResult:
        packet_id = str(packet_id)
        packet = await session.get(Packet, packet_id)
        if not packet:
            raise ValueError(f"Packet {packet_id} not found")

        documents_result = await session.execute(
            select(Document)
            .where(Document.packet_id == packet_id)
            .order_by(Document.display_order)
            .options(
                selectinload(Document.redaction_candidates).selectinload(
                    RedactionCandidate.approval
                ),
                selectinload(Document.privilege_decisions),
                selectinload(Document.bates_assignments),
            )
        )
        documents = documents_result.scalars().all()

        if not documents:
            raise ValueError("Packet has no documents")

        for doc in documents:
            if doc.processing_status != ProcessingStatus.COMPLETED:
                raise ValueError(f"Document {doc.original_filename} is not fully processed")

        bates_assignments = await session.execute(
            select(BatesAssignment).where(BatesAssignment.packet_id == packet_id)
        )
        bates_list = bates_assignments.scalars().all()
        if not bates_list:
            raise ValueError("Bates numbers not assigned. Run Bates assignment first.")

        self._verify_applied_redactions(documents)

        final_dir = settings.final_path / packet_id
        if final_dir.exists():
            shutil.rmtree(final_dir)
        final_dir.mkdir(parents=True, exist_ok=True)
        exhibits_dir = final_dir / "exhibits"
        exhibits_dir.mkdir(parents=True, exist_ok=True)

        writer = PdfWriter()
        manifest_entries = []

        for i, document in enumerate(documents):
            exhibit_letter = chr(65 + i)

            bates_assignments_doc = await session.execute(
                select(BatesAssignment)
                .where(
                    BatesAssignment.packet_id == packet_id,
                    BatesAssignment.document_id == document.id,
                )
                .order_by(BatesAssignment.page_number)
            )
            doc_bates = bates_assignments_doc.scalars().all()
            bates_start = doc_bates[0].bates_label if doc_bates else "N/A"
            bates_end = doc_bates[-1].bates_label if doc_bates else "N/A"

            source_path = self._resolve_source_path(document)
            if source_path is None or not source_path.exists():
                raise ValueError(f"No PDF source available for {document.original_filename}")

            redacted_texts = [
                c.matched_text
                for c in document.redaction_candidates
                if c.status == RedactionStatus.APPLIED
            ]
            safe_description = self._sanitize_description(document.description, redacted_texts)

            cover_sheet_bytes = self._create_cover_sheet(
                packet, document, bates_start, bates_end, exhibit_letter, safe_description
            )

            doc_bates_list = [ba.bates_label for ba in doc_bates]
            stamped_path = settings.working_path / f"{document.sha256}_stamped.pdf"
            self._stamp_pdf_file(source_path, stamped_path, doc_bates_list)

            stamped_reader = PdfReader(stamped_path)
            cover_reader = PdfReader(BytesIO(cover_sheet_bytes))

            for page in cover_reader.pages:
                writer.add_page(page)
            for page in stamped_reader.pages:
                writer.add_page(page)

            stamped_writer = PdfWriter()
            for page in PdfReader(BytesIO(cover_sheet_bytes)).pages:
                stamped_writer.add_page(page)
            for page in PdfReader(stamped_path).pages:
                stamped_writer.add_page(page)

            stamped_exhibit_path = exhibits_dir / f"EX-{exhibit_letter}.pdf"
            stamped_writer.write(stamped_exhibit_path)

            applied_redactions = []
            for candidate in document.redaction_candidates:
                if candidate.status == RedactionStatus.APPLIED and candidate.approval:
                    applied_redactions.append(
                        {
                            "candidate_id": str(candidate.id),
                            "page": candidate.page_number,
                            "category": candidate.category.value,
                            "matched_text": candidate.matched_text,
                            "approver": candidate.approval.approver,
                            "approved_at": candidate.approval.approved_at.isoformat()
                            if candidate.approval.approved_at
                            else None,
                            "verified": candidate.approval.verification_passed,
                        }
                    )

            privilege_status = None
            privilege_category = None
            privilege_reason = None
            if document.privilege_decisions:
                pd = document.privilege_decisions[0]
                privilege_status = pd.status.value
                privilege_category = pd.category.value if pd.category else None
                privilege_reason = pd.reason

            manifest_entry = ManifestEntry(
                manifest_id=None,
                document_id=document.id,
                exhibit_identifier=f"EX-{exhibit_letter}",
                bates_start=bates_start,
                bates_end=bates_end,
                page_count=document.page_count + 1,
                original_sha256=document.original_sha256,
                processed_sha256=document.processed_sha256,
                final_sha256=self._calculate_sha256(stamped_exhibit_path),
                description=safe_description or document.original_filename,
                privilege_status=privilege_status,
                privilege_category=privilege_category,
                privilege_reason=privilege_reason,
                applied_redactions=applied_redactions,
                final_file_path=str(stamped_exhibit_path.relative_to(settings.final_path)),
            )
            manifest_entries.append(manifest_entry)

        final_packet_path = final_dir / "final_packet.pdf"
        writer.write(final_packet_path)

        exhibit_index_path = final_dir / "exhibit_index.pdf"
        with open(exhibit_index_path, "wb") as f:
            f.write(self._create_exhibit_index(packet, documents, manifest_entries))

        privilege_log_path = final_dir / "privilege_log.pdf"
        with open(privilege_log_path, "wb") as f:
            f.write(self._create_privilege_log(packet, documents))

        valid, errors, warnings = self._run_validation(packet, documents, bates_list)

        existing_manifest_result = await session.execute(
            select(Manifest).where(Manifest.packet_id == packet.id)
        )
        existing_manifest = existing_manifest_result.scalars().first()
        if existing_manifest:
            await session.delete(existing_manifest)
            await session.flush()

        manifest = Manifest(
            packet_id=packet.id,
            total_pages=sum(e.page_count for e in manifest_entries),
            total_documents=len(documents),
            bates_start=manifest_entries[0].bates_start if manifest_entries else None,
            bates_end=manifest_entries[-1].bates_end if manifest_entries else None,
            validation_passed=valid,
            validation_details={"errors": errors, "warnings": warnings},
            final_packet_sha256=self._calculate_sha256(final_packet_path),
            final_packet_path=str(final_packet_path.relative_to(settings.final_path)),
        )
        session.add(manifest)
        await session.flush()

        for entry in manifest_entries:
            entry.manifest_id = manifest.id
            session.add(entry)

        await session.commit()
        await session.refresh(manifest)

        manifest_path = final_dir / "manifest.json"
        manifest_data = {
            "packet_id": str(packet.id),
            "packet_name": packet.name,
            "generated_at": manifest.generated_at.isoformat()
            if manifest.generated_at
            else utc_now().isoformat(),
            "total_pages": manifest.total_pages,
            "total_documents": manifest.total_documents,
            "bates_start": manifest.bates_start,
            "bates_end": manifest.bates_end,
            "validation_passed": manifest.validation_passed,
            "validation_details": manifest.validation_details,
            "final_packet": {
                "path": str(final_packet_path.relative_to(settings.final_path)),
                "sha256": manifest.final_packet_sha256,
            },
            "entries": [
                {
                    "exhibit_identifier": e.exhibit_identifier,
                    "document_id": str(e.document_id),
                    "bates_start": e.bates_start,
                    "bates_end": e.bates_end,
                    "page_count": e.page_count,
                    "original_sha256": e.original_sha256,
                    "processed_sha256": e.processed_sha256,
                    "final_sha256": e.final_sha256,
                    "description": e.description,
                    "privilege_status": e.privilege_status,
                    "privilege_category": e.privilege_category,
                    "privilege_reason": e.privilege_reason,
                    "applied_redactions": [
                        {
                            **redaction,
                            "matched_text": "***",
                        }
                        for redaction in (e.applied_redactions or [])
                    ],
                    "final_file_path": e.final_file_path,
                }
                for e in manifest_entries
            ],
        }
        with open(manifest_path, "w") as f:
            json.dump(manifest_data, f, indent=2, default=str)

        audit_event = AuditEvent(
            packet_id=packet.id,
            event_type=AuditEventType.PACKET_BUILT,
            user_id="system",
            event_metadata={
                "final_packet": str(final_packet_path),
                "total_documents": len(documents),
                "total_pages": manifest.total_pages,
                "validation_passed": valid,
            },
        )
        session.add(audit_event)
        await session.commit()

        return BuildResult(
            final_packet_path=final_packet_path,
            exhibits_dir=exhibits_dir,
            exhibit_index_path=exhibit_index_path,
            privilege_log_path=privilege_log_path,
            manifest_path=manifest_path,
            manifest=manifest,
        )

    async def validate_packet(
        self,
        session,
        packet_id: str,
    ) -> dict:
        packet_id = str(packet_id)
        packet = await session.get(Packet, packet_id)
        if not packet:
            return {"valid": False, "errors": ["Packet not found"]}

        documents_result = await session.execute(
            select(Document).where(Document.packet_id == packet_id).order_by(Document.display_order)
        )
        documents = documents_result.scalars().all()

        bates_assignments = await session.execute(
            select(BatesAssignment).where(BatesAssignment.packet_id == packet_id)
        )
        bates_list = bates_assignments.scalars().all()
        bates_list = sorted(bates_list, key=lambda ba: ba.bates_number)

        valid, errors, warnings = self._run_validation(packet, documents, bates_list)

        manifest = await session.execute(select(Manifest).where(Manifest.packet_id == packet_id))
        manifest = manifest.scalars().first()

        if manifest and manifest.final_packet_sha256:
            final_packet_path = settings.final_path / manifest.final_packet_path
            if final_packet_path.exists():
                actual_sha256 = self._calculate_sha256(final_packet_path)
                if actual_sha256 != manifest.final_packet_sha256:
                    errors.append("Final packet checksum mismatch")
                    valid = False

        total_pages = sum(doc.page_count for doc in documents) + len(documents)

        return {
            "valid": valid and len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "total_documents": len(documents),
            "total_pages": total_pages,
            "bates_range": f"{bates_list[0].bates_label} - {bates_list[-1].bates_label}"
            if bates_list
            else None,
        }


async def get_packet_builder() -> PacketBuilderService:
    return PacketBuilderService()
