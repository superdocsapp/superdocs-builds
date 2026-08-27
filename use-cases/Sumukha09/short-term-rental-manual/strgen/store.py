"""Tiny atomic JSON persistence — no servers, no ORMs, just files."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .errors import AlreadyExists, NotFound
from .models import Property, SharedBlock


class Store:
    """Filesystem-backed store.

    Layout:
        <root>/blocks.json          {block_id: block_dict}
        <root>/properties/<id>.json property_dict
    """

    def __init__(self, root: str | Path = "data"):
        self.root = Path(root)
        self.blocks_file = self.root / "blocks.json"
        self.properties_dir = self.root / "properties"

    # -- low-level ----------------------------------------------------------

    def _ensure_dirs(self) -> None:
        self.properties_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _read_json(path: Path) -> Any:
        if not path.exists():
            return None
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)

    @staticmethod
    def _write_json(path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2, ensure_ascii=False, sort_keys=True)
            os.replace(tmp_name, path)  # atomic on POSIX and Windows
        finally:
            if os.path.exists(tmp_name):
                try:
                    os.remove(tmp_name)
                except OSError:
                    pass

    # -- shared blocks -------------------------------------------------------

    def load_blocks(self) -> dict[str, SharedBlock]:
        raw = self._read_json(self.blocks_file) or {}
        return {bid: SharedBlock.from_dict(d) for bid, d in raw.items()}

    def save_block(self, block: SharedBlock) -> None:
        raw = self._read_json(self.blocks_file) or {}
        raw[block.id] = block.to_dict()
        self._write_json(self.blocks_file, raw)

    def get_block(self, block_id: str) -> SharedBlock:
        blocks = self.load_blocks()
        if block_id not in blocks:
            raise NotFound(f"Shared block '{block_id}' not found.")
        return blocks[block_id]

    def delete_block(self, block_id: str) -> None:
        raw = self._read_json(self.blocks_file) or {}
        if block_id not in raw:
            raise NotFound(f"Shared block '{block_id}' not found.")
        del raw[block_id]
        self._write_json(self.blocks_file, raw)

    def find_blocks(self, kind: str | None = None) -> list[SharedBlock]:
        blocks = sorted(self.load_blocks().values(), key=lambda b: (b.kind, b.name))
        if kind:
            blocks = [b for b in blocks if b.kind == kind]
        return blocks

    # -- properties -----------------------------------------------------------

    def _prop_path(self, property_id: str) -> Path:
        return self.properties_dir / f"{property_id}.json"

    def save_property(self, prop: Property) -> None:
        self._ensure_dirs()
        self._write_json(self._prop_path(prop.id), prop.to_dict())

    def load_properties(self) -> dict[str, Property]:
        self._ensure_dirs()
        props: dict[str, Property] = {}
        for path in sorted(self.properties_dir.glob("*.json")):
            data = self._read_json(path)
            if data:
                prop = Property.from_dict(data)
                props[prop.id] = prop
        return props

    def get_property(self, property_id: str) -> Property:
        path = self._prop_path(property_id)
        data = self._read_json(path)
        if not data:
            raise NotFound(f"Property '{property_id}' not found.")
        return Property.from_dict(data)

    def create_property(self, prop: Property, *, allow_existing: bool = False) -> None:
        self._ensure_dirs()
        if self._prop_path(prop.id).exists() and not allow_existing:
            raise AlreadyExists(f"Property '{prop.id}' already exists.")
        self.save_property(prop)

    def delete_property(self, property_id: str) -> None:
        path = self._prop_path(property_id)
        if not path.exists():
            raise NotFound(f"Property '{property_id}' not found.")
        path.unlink()

    def properties_using_block(self, block_id: str) -> list[Property]:
        return [p for p in self.load_properties().values()
                if block_id in p.links.values()]
