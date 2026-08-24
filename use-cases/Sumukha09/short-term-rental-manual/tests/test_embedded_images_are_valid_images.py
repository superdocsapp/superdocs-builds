import base64
import re
from io import BytesIO
from PIL import Image
from pathlib import Path
from document_generator import generate_manual_html
from content_generator import get_property_canonical_content
from mock_data import load_mock_catalog

def test_embedded_images_are_valid_images():
    catalog = load_mock_catalog()
    content = get_property_canonical_content(catalog, "green")
    html = generate_manual_html(content)
    
    uris = re.findall(r'data:image/([a-zA-Z]+);base64,([^&\"\'\)\s<>]+)', html)
    assert len(uris) == 7, f"Expected 7 images, found {len(uris)}"
    
    for ext, b64 in uris:
        raw = base64.b64decode(b64, validate=True)
        img = Image.open(BytesIO(raw))
        img.verify()
        assert img.format.lower() == ext.lower() or (img.format.lower() == 'jpeg' and ext.lower() == 'jpeg')
        # Reject 1x1 placeholder images standing in for real photos or the map.
        assert Image.open(BytesIO(raw)).size > (1, 1), "Embedded image is a 1x1 placeholder"
