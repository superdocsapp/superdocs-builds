"""Per-document folder organizer and ZIP packaging engine for M&A closing binders."""

import json
import os
import re
import shutil
from typing import Dict, List, Optional

from core.models import ClosingChecklist, DocumentMetadata, MatchResult


class PerDocumentExporter:
    """Exports structured per-document directories and deliverables."""

    def export_folder(
        self,
        checklist: ClosingChecklist,
        matches: List[MatchResult],
        documents_map: Dict[str, DocumentMetadata],
        output_dir: str,
        create_zip: bool = True,
    ) -> Dict[str, str]:
        """Creates clean per-document folder hierarchy and ZIP archive."""
        os.makedirs(output_dir, exist_ok=True)
        manifest_items = []

        for match in matches:
            item = next((it for it in checklist.items if it.item_id == match.checklist_item_id), None)
            if not item:
                continue

            doc_meta = documents_map.get(match.doc_id) if match.doc_id else None
            
            cat_folder_name = self._sanitize_folder_name(item.category.value)
            cat_dir = os.path.join(output_dir, cat_folder_name)
            os.makedirs(cat_dir, exist_ok=True)

            clean_title = self._sanitize_filename(item.title)
            ext = doc_meta.file_type if doc_meta else "txt"
            target_filename = f"{item.tab_label.replace(' ', '_')}_{clean_title}.{ext}"
            target_path = os.path.join(cat_dir, target_filename)

            if doc_meta and doc_meta.file_path and os.path.exists(doc_meta.file_path):
                shutil.copy2(doc_meta.file_path, target_path)
            else:
                with open(target_path, "w", encoding="utf-8") as f:
                    f.write(
                        f"MISSING DELIVERABLE AT CLOSING\n"
                        f"================================\n\n"
                        f"Checklist Item: {item.tab_label} - {item.title}\n"
                        f"Category: {item.category.value}\n"
                        f"Responsible Counsel: {item.responsible_counsel}\n"
                        f"Status: PENDING EXECUTION / DELIVERY\n"
                    )

            manifest_items.append({
                "tab_number": item.tab_number,
                "tab_label": item.tab_label,
                "title": item.title,
                "category": item.category.value,
                "relative_path": os.path.relpath(target_path, output_dir),
                "execution_status": match.execution_status.value,
                "original_source_file": doc_meta.original_filename if doc_meta else None,
            })

        manifest_path = os.path.join(output_dir, "MANIFEST.json")
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump({
                "deal_name": checklist.deal_name,
                "closing_date": checklist.closing_date,
                "buyer": checklist.buyer_entity,
                "target": checklist.target_entity,
                "total_items": len(manifest_items),
                "documents": manifest_items,
            }, f, indent=2)

        index_md_path = os.path.join(output_dir, "INDEX.md")
        self._write_index_markdown(index_md_path, checklist, manifest_items)

        zip_path = None
        if create_zip:
            zip_base = output_dir.rstrip("/\\")
            zip_path = shutil.make_archive(zip_base, "zip", output_dir)

        return {
            "folder_path": os.path.abspath(output_dir),
            "manifest_path": os.path.abspath(manifest_path),
            "index_path": os.path.abspath(index_md_path),
            "zip_path": os.path.abspath(zip_path) if zip_path else None,
        }

    def _write_index_markdown(self, path: str, checklist: ClosingChecklist, items: List[Dict]):
        lines = [
            f"# {checklist.deal_name}",
            f"**Closing Binder - Per-Document Folder Index**",
            f"",
            f"- **Buyer:** {checklist.buyer_entity}",
            f"- **Target:** {checklist.target_entity}",
            f"- **Closing Date:** {checklist.closing_date}",
            f"- **Total Documents:** {len(items)}",
            f"",
            f"| Tab | Title | Category | Status | File Path |",
            f"| :--- | :--- | :--- | :--- | :--- |",
        ]
        for it in items:
            lines.append(f"| {it['tab_label']} | {it['title']} | {it['category']} | `{it['execution_status']}` | `{it['relative_path']}` |")

        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

    def _sanitize_folder_name(self, name: str) -> str:
        clean = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_")
        return clean[:50]

    def _sanitize_filename(self, name: str) -> str:
        clean = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_")
        return clean[:60]
