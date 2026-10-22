"""Compile Task 2.1 demo frames into an optimized animated GIF."""

import os
import sys
from pathlib import Path
from PIL import Image

FRAMES_DIR = Path("/tmp/task21_demo_frames")
OUTPUT_PATH = Path(__file__).resolve().parent.parent / "docs" / "task-2-1-demo.gif"

# Per-frame duration in milliseconds tailored for readability
DURATION_MAP = {
    "01_dashboard": 1400,
    "02_create_packet_modal": 1200,
    "03_packet_in_list": 1000,
    "04_empty_workspace": 1000,
    "05_exhibits_uploaded": 1800,
    "06_processing_active": 1200,
    "07_processing_completed": 1200,
    "08_bates_assigned": 2200,
    "09_ocr_drawer_open": 2200,
    "10_drawer_closed": 600,
    "11_privilege_decision_filled": 1500,
    "12_privilege_saved": 1400,
    "13_pii_candidates_surfaced": 2400,
    "14_candidate_approved": 1800,
    "15_redactions_applied_verified": 2200,
    "16_audit_trail": 1600,
    "17_preflight_modal": 1800,
    "18_packet_built_overview": 1600,
    "19_packet_verified_banner": 2800,
    "20_export_ready": 2200,
}

DEFAULT_DURATION = 1500


def compile_gif():
    if not FRAMES_DIR.exists():
        print(f"Error: Frames directory {FRAMES_DIR} does not exist. Run Playwright recording first.", file=sys.stderr)
        sys.exit(1)

    frame_files = sorted([f for f in FRAMES_DIR.iterdir() if f.suffix.lower() == ".png"])
    if not frame_files:
        print(f"Error: No PNG frames found in {FRAMES_DIR}", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(frame_files)} frames in {FRAMES_DIR}")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    images = []
    durations = []
    target_width = 1100  # High readability & compact size

    for frame_file in frame_files:
        img = Image.open(frame_file).convert("RGB")
        if img.width != target_width:
            aspect = img.height / img.width
            target_height = int(target_width * aspect)
            img = img.resize((target_width, target_height), Image.Resampling.LANCZOS)

        # Quantize with adaptive palette and no dither for razor-sharp legal UI text
        quantized = img.quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
        images.append(quantized)

        # Determine duration
        dur = DEFAULT_DURATION
        for key, val in DURATION_MAP.items():
            if key in frame_file.stem:
                dur = val
                break
        durations.append(dur)

    total_duration_ms = sum(durations)
    total_seconds = total_duration_ms / 1000.0

    print(f"Compiling animated GIF ({len(images)} frames, total duration: {total_seconds:.1f}s)...")

    images[0].save(
        OUTPUT_PATH,
        save_all=True,
        append_images=images[1:],
        duration=durations,
        loop=0,
        optimize=True,
    )

    file_size_mb = OUTPUT_PATH.stat().st_size / (1024 * 1024)
    print(f"Successfully generated: {OUTPUT_PATH}")
    print(f"  File size: {file_size_mb:.2f} MB")
    print(f"  Total Duration: {total_seconds:.1f}s ({len(images)} frames)")
    print(f"  Dimensions: {images[0].width}x{images[0].height} px")


if __name__ == "__main__":
    compile_gif()
