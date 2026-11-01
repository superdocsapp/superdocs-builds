from pathlib import Path


def project_root() -> Path:
    here = Path(__file__).resolve()
    for cand in (here.parent, *here.parents):
        if (cand / "pyproject.toml").is_file() and (cand / "config").is_dir():
            return cand
    raise RuntimeError("cannot locate soc2-evidence-index project root")


def config_dir() -> Path:
    return project_root() / "config"


def templates_dir() -> Path:
    return project_root() / "templates"


def default_catalog_path() -> Path:
    return config_dir() / "catalogs" / "tsc-cc.yaml"


def sample_catalog_path() -> Path:
    return config_dir() / "catalogs" / "tsc-cc6-cc7.yaml"


def mapping_rules_path() -> Path:
    return config_dir() / "mapping_rules.yaml"


def injection_patterns_path() -> Path:
    return config_dir() / "injection_patterns.yaml"


def skeleton_template_path() -> Path:
    return templates_dir() / "soc2_evidence_index.html"
