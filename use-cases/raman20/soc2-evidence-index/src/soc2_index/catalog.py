from __future__ import annotations

from pathlib import Path

import yaml

from soc2_index.models import Catalog, CatalogControl
from soc2_index.paths import default_catalog_path, sample_catalog_path
from soc2_index.runstore import sha256_file


def load_catalog(path: Path | None = None) -> Catalog:
    p = path or default_catalog_path()
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    controls = [CatalogControl(id=c["id"], name=c["name"]) for c in data["controls"]]
    ids = [c.id for c in controls]
    if len(ids) != len(set(ids)):
        raise ValueError(f"duplicate control ids in {p}")
    return Catalog(
        id=data["id"],
        name=data.get("name") or data["id"],
        controls=controls,
        sha256=sha256_file(p),
    )


def load_sample_catalog() -> Catalog:
    return load_catalog(sample_catalog_path())
