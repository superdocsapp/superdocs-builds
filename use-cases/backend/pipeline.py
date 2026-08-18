import argparse
import hashlib
import json
from pathlib import Path

from backend.asset_validator import validate_assets_exist
from backend.fact_loader import load_game_facts
from backend.fact_validator import validate_press_kit
from backend.html_renderer import render_press_kit_html
from backend.localizer import localize_press_kit, validate_localization
from backend.press_kit_generator import generate_press_kit


def _fingerprint(input_path: Path, language: str) -> str:
    return hashlib.sha256(input_path.read_bytes() + language.encode("utf-8")).hexdigest()


def _save_state(path: Path, state: dict) -> None:
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def run_local(input_path: str, output_dir: str, asset_dir: str, language: str = "Spanish") -> dict:
    """Run deterministic stages with a persistent checkpoint/resume state."""
    source_path = Path(input_path)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    stem = source_path.stem
    state_path = output / "pipeline_state.json"
    fingerprint = _fingerprint(source_path, language)

    state = {"fingerprint": fingerprint, "completed_stages": []}
    if state_path.exists():
        existing = json.loads(state_path.read_text(encoding="utf-8"))
        if existing.get("fingerprint") == fingerprint:
            state = existing

    def checkpoint(stage: str) -> None:
        if stage not in state["completed_stages"]:
            state["completed_stages"].append(stage)
        _save_state(state_path, state)

    print("[1/5] Loading and validating source facts")
    facts = load_game_facts(str(source_path))
    missing = validate_assets_exist(facts, asset_dir)
    if missing:
        raise RuntimeError(f"Declared assets are missing: {missing}")
    checkpoint("source_validated")

    json_path = output / f"{stem}_press_kit.json"
    print("[2/5] Generating grounded press kit")
    if "press_kit_generated" in state["completed_stages"] and json_path.exists():
        press_kit = json.loads(json_path.read_text(encoding="utf-8"))
    else:
        press_kit = generate_press_kit(facts)
        validation = validate_press_kit(facts, press_kit)
        if not validation.valid:
            raise RuntimeError("Generated press kit failed validation: " + str(validation.issues))
        json_path.write_text(json.dumps(press_kit, indent=2, ensure_ascii=False), encoding="utf-8")
        checkpoint("press_kit_generated")

    html_path = output / f"{stem}_press_kit.html"
    print("[3/5] Rendering HTML checkpoint")
    if "html_rendered" not in state["completed_stages"] or not html_path.exists():
        html_path.write_text(render_press_kit_html(press_kit), encoding="utf-8")
        checkpoint("html_rendered")

    localized_path = output / f"{stem}_press_kit_es.json"
    print("[4/5] Localizing and validating invariants")
    if "localized" in state["completed_stages"] and localized_path.exists():
        localized = json.loads(localized_path.read_text(encoding="utf-8"))
    else:
        localized = localize_press_kit(press_kit, language)
        errors = validate_localization(press_kit, localized)
        if errors:
            raise RuntimeError("Localization validation failed: " + "; ".join(errors))
        localized_path.write_text(json.dumps(localized, indent=2, ensure_ascii=False), encoding="utf-8")
        checkpoint("localized")

    print("[5/5] Checkpoint saved; SuperDocs review is an optional live stage")
    checkpoint("local_pipeline_complete")
    return {"json": json_path, "html": html_path, "localized": localized_path, "state": state_path}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run deterministic Game Press Kit Builder stages.")
    parser.add_argument("--input", default="sample-data/emberfall.json")
    parser.add_argument("--output-dir", default="output")
    parser.add_argument("--asset-dir", default="sample-data/assets")
    parser.add_argument("--language", default="Spanish")
    args = parser.parse_args()
    for name, path in run_local(args.input, args.output_dir, args.asset_dir, args.language).items():
        print(f"{name}: {path}")


if __name__ == "__main__":
    main()
