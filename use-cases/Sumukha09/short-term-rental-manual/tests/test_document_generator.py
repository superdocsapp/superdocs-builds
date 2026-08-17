from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1]))

from content_generator import get_property_canonical_content
from document_generator import generate_manual_html
from listing_generator import LISTING_MAX_CHARS, generate_listing_description
from mock_data import load_mock_catalog
from welcome_card_generator import generate_welcome_card_html
from workflow import build_preview


def test_manual_embeds_required_sections_images_and_map():
    manual = generate_manual_html(get_property_canonical_content(load_mock_catalog(), "green"))
    for marker in ("GreenGuest", "Appliances", "House Rules", "Local Recommendations", "Emergency Information"):
        assert marker in manual
    
    # Strictly verify that 5 photographs and 1 map are embedded via data URIs (plus the cover image which is a duplicate of the first photo)
    jpeg_count = manual.count("data:image/jpeg;base64,")
    png_count = manual.count("data:image/png;base64,")
    assert jpeg_count + png_count == 7
    # Verify there are no local file references such as .jpg or .png inside img src
    assert "src=\"assets/" not in manual
    assert "src=\"../assets/" not in manual


def test_listing_respects_character_limit():
    listing = generate_listing_description(get_property_canonical_content(load_mock_catalog(), "green"))
    assert "Green Residency" in listing
    assert len(listing) <= LISTING_MAX_CHARS


def test_welcome_card_contains_essential_information():
    card = generate_welcome_card_html(get_property_canonical_content(load_mock_catalog(), "green"))
    for marker in ("GreenGuest", "TEST-NEW-PASSWORD", "2 PM", "11 AM", "112"):
        assert marker in card


def test_preview_is_local_and_produces_every_artifact():
    artifacts = build_preview(load_mock_catalog(), "green")
    assert set(artifacts) == {"manual.html", "listing.txt", "welcome_card.html"}
