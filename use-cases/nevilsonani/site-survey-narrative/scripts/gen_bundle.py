"""Generate the synthetic survey bundle: 12 annotated photo stand-ins (PNG),
a measurements sheet, and three voice-note transcripts, for a fictional
client. Run once; outputs are committed.

    uv run python scripts/gen_bundle.py

The 'photos' are deliberately synthetic: each PNG depicts the scene as a
labeled diagram with the observation burned into the image itself, so the
document AI reads evidence from the attachment, not from any caption we
type into a prompt. A real deployment would upload the surveyor's actual
JPEGs through exactly the same path.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent / "bundle"
PHOTOS = ROOT / "photos"

SHOTS: list[tuple[str, str, list[str], str]] = [
    ("IMG_01_roof_overview_south.png", "SOUTH ROOF PLANE - OVERVIEW",
     ["Flat RCC roof, clear area approx 9.2 m x 6.4 m",
      "Surface: cement screed, broadly even",
      "Orientation: long edge faces south (azimuth ~182 deg)"], "#8a9bb0"),
    ("IMG_02_roof_surface_cracks.png", "ROOF SURFACE - NE CORNER",
     ["Hairline cracks in screed near NE corner",
      "No spalling or exposed rebar visible",
      "Ponding stain ring approx 1 m across"], "#9aa77f"),
    ("IMG_03_parapet_wall.png", "PARAPET WALL - SOUTH EDGE",
     ["Parapet height approx 0.9 m along south edge",
      "Brick + plaster, sound condition",
      "Provides wind shielding for low-tilt arrays"], "#b0917a"),
    ("IMG_04_water_tank.png", "OVERHEAD WATER TANK - NW CORNER",
     ["1000 L tank on RCC frame, frame height approx 2.1 m",
      "Casts shadow toward SE in late afternoon",
      "Frame condition: fair, minor surface rust on brackets"], "#7f96a8"),
    ("IMG_05_neighbor_tree.png", "EAST BOUNDARY - NEIGHBOUR'S TREE",
     ["Neem tree approx 8 m tall on east boundary",
      "Morning shade falls on east half of roof",
      "Canopy overhang approx 1.5 m over parapet"], "#6f9a6f"),
    ("IMG_06_meter_board.png", "SERVICE METER - GROUND FLOOR",
     ["Single-phase meter, 63 A service",
      "Meter board on external wall near gate",
      "Meter room dry, lockable"], "#a08fa8"),
    ("IMG_07_main_db.png", "MAIN DISTRIBUTION BOARD",
     ["Main DB inside ground-floor utility room",
      "One 32 A spare way available",
      "Earth wiring present; cover NOT fully opened during visit"], "#a8988f"),
    ("IMG_08_cable_route.png", "PROPOSED CABLE ROUTE - WEST WALL",
     ["External wall chase possible, roof to meter room",
      "Route length approx 12 m, two 90-degree bends",
      "No existing conduit; new conduit required"], "#8f9ea8"),
    ("IMG_09_staircase_access.png", "ROOF ACCESS - STAIRCASE + HATCH",
     ["Internal staircase to first floor",
      "Steel ladder + roof hatch, opening 0.6 m x 0.6 m",
      "Panel carry-up will need rope lift over parapet"], "#a89f7f"),
    ("IMG_10_antenna_mast.png", "OLD ANTENNA MAST - CENTRE ROOF",
     ["Disused TV antenna mast, guy wires slack",
      "Base plate bolted to roof; removable",
      "Owner confirmed mast can be removed"], "#96a3ab"),
    ("IMG_11_roof_drain.png", "ROOF DRAINS - NORTH EDGE",
     ["Two rainwater outlets on north edge",
      "Clear of debris at time of visit",
      "Array layout must keep 300 mm drainage margin"], "#7fa0a0"),
    ("IMG_12_earth_pit.png", "EARTH PIT - NEAR GATE",
     ["Existing earth pit chamber near gate",
      "Cover rusted shut; could not open during visit",
      "Earth resistance NOT measured"], "#a08484"),
]

MEASUREMENTS = """item,value,unit,method
roof_clear_length,9.2,m,tape
roof_clear_width,6.4,m,tape
parapet_height,0.9,m,tape
roof_azimuth_long_edge,182,deg,compass app
roof_tilt,0,deg,flat RCC slab
tank_frame_height,2.1,m,tape
tree_height_estimate,8,m,visual estimate
cable_route_length,12,m,tape along wall
service_phase,single,-,meter nameplate
service_rating,63,A,meter nameplate
spare_way_rating,32,A,DB inspection
"""

VOICE_NOTES = {
    "vn_01.txt": (
        "Voice note 1 - roof condition. Transcript: The screed cracks on the "
        "north-east corner look superficial, but there is an old ponding ring, "
        "so I would recommend the client gets a waterproofing check done before "
        "we penetrate anything. Ballasted mounting would avoid penetrations "
        "entirely on this roof."
    ),
    "vn_02.txt": (
        "Voice note 2 - client conversation. Transcript: The client mentioned "
        "they are planning a first-floor extension on the west side sometime "
        "next year. Nothing is designed yet, but keep the west third of the "
        "roof out of the array layout until that is confirmed."
    ),
    "vn_03.txt": (
        "Voice note 3 - open items. Transcript: I did not open the DB cover "
        "fully, so RCD status is unverified - we need a second visit with the "
        "electrician. Also the earth pit cover was rusted shut, no resistance "
        "reading. And the water tank frame should get a structural sign-off "
        "before we hang anything off it."
    ),
}

MANIFEST = """# Synthetic survey bundle - fictional client, fabricated data (as the task expects)
client: Malhotra Residence (fictional)
address: Satellite, Ahmedabad, Gujarat (fictional)
surveyor: R. Patel, Sunbeam Solar Services (fictional)
survey_date: 2026-08-05
photos_dir: photos
measurements: measurements.csv
voice_notes: [vn_01.txt, vn_02.txt, vn_03.txt]
photo_count: 12
note: >
  Photo files are annotated stand-ins generated by scripts/gen_bundle.py.
  The pipeline treats them exactly like real survey JPEGs: they are uploaded
  as SuperDocs attachments and every observation in the narrative must cite
  one of them (or the measurements sheet / a voice note) as evidence.
"""


def _font(size: int):
    for name in ("arial.ttf", "DejaVuSans.ttf", "segoeui.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def make_photo(filename: str, title: str, lines: list[str], color: str) -> None:
    img = Image.new("RGB", (900, 640), color)
    d = ImageDraw.Draw(img)
    d.rectangle([20, 20, 880, 620], outline="#222222", width=3)
    d.rectangle([20, 20, 880, 110], fill="#1d232b")
    d.text((40, 42), title, fill="#f2f2f2", font=_font(34))
    y = 170
    for line in lines:
        d.ellipse([48, y + 10, 64, y + 26], fill="#1d232b")
        d.text((84, y), line, fill="#101318", font=_font(27))
        y += 62
    d.rectangle([20, 560, 880, 620], fill="#e8e4d8")
    d.text((40, 574), f"SITE SURVEY PHOTO  |  {filename}  |  05-Aug-2026",
           fill="#333333", font=_font(22))
    (PHOTOS / filename).parent.mkdir(parents=True, exist_ok=True)
    img.save(PHOTOS / filename)


def build_photo_log(photo_paths: list[Path], out_pdf: Path) -> None:
    """Compile photos into the surveyor's photo-log PDF: one photo per page
    with a large PHOTO ID caption strip, so the document AI can tie every
    page back to its filename. (The attachments API accepts documents, not
    raw image files - see the README's bug note.)"""
    pages = []
    for p in photo_paths:
        photo = Image.open(p).convert("RGB")
        page = Image.new("RGB", (photo.width, photo.height + 90), "#ffffff")
        page.paste(photo, (0, 0))
        d = ImageDraw.Draw(page)
        d.text((30, photo.height + 22), f"PHOTO ID: {p.name}",
               fill="#111111", font=_font(36))
        pages.append(page)
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    pages[0].save(out_pdf, save_all=True, append_images=pages[1:])


def main() -> None:
    PHOTOS.mkdir(parents=True, exist_ok=True)
    for filename, title, lines, color in SHOTS:
        make_photo(filename, title, lines, color)
    (ROOT / "measurements.csv").write_text(MEASUREMENTS, encoding="utf-8")
    notes = ROOT / "voice_notes"
    notes.mkdir(exist_ok=True)
    for name, text in VOICE_NOTES.items():
        (notes / name).write_text(text, encoding="utf-8")
    (ROOT / "manifest.yaml").write_text(MANIFEST, encoding="utf-8")
    build_photo_log(sorted(PHOTOS.glob("*.png")), ROOT / "photo_log.pdf")
    print(f"bundle written to {ROOT} ({len(SHOTS)} photos + photo_log.pdf)")


if __name__ == "__main__":
    main()
