from pathlib import Path

import yaml


def load_library(path: str | Path) -> list[dict]:
    raw = yaml.safe_load(Path(path).read_text())
    clauses = []
    for entry in raw["clauses"]:
        clause = {
            "id": str(entry["id"]),
            "title": entry["title"],
            "expectation": entry.get("expectation", ""),
            "level": int(entry.get("level", 2)),
            "linkable": bool(entry.get("linkable", True)),
        }
        clauses.append(clause)
    ids = [c["id"] for c in clauses]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate clause ids in library")
    return clauses


def sample_ids(path: str | Path) -> list[str]:
    raw = yaml.safe_load(Path(path).read_text())
    return [str(i) for i in raw.get("demo_sample", [])]


def subset(clauses: list[dict], n: int | None) -> list[dict]:
    if not n:
        return [c for c in clauses if c["linkable"]]
    order = sample_ids(LIBRARY_PATH)
    chosen = [c for cid in order for c in clauses if c["id"] == cid]
    for c in clauses:
        if len(chosen) >= n:
            break
        if c["linkable"] and c not in chosen:
            chosen.append(c)
    return chosen[:n]


LIBRARY_PATH = Path(__file__).resolve().parent.parent / "clauses" / "iso9001_2015.yaml"
