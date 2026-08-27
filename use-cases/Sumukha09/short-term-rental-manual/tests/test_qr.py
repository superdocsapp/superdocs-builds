import unittest

from strgen import qr


PAYLOADS = [
    b"A",
    b"HELLO-WORLD",
    b"WIFI:T:WPA;S:Haveli-Jaipur-Guest;P:Strawberry~Fields!39;;",
    bytes(range(256)),                      # forces multi-block versions
    ("caf\u00e9 \u2603 snowman-\u00fcmlaut " * 8).encode(),  # ~200B -> v9/v10 M/L
]


class QRRoundTrip(unittest.TestCase):
    def test_roundtrip_all_levels(self):
        for payload in PAYLOADS:
            for level in ("L", "M"):
                matrix = qr.make(payload, ec_level=level)
                qr.verify_matrix(matrix, payload)  # raises on any defect

    def test_svg_shape(self):
        matrix = qr.make(b"https://example.com")
        art = qr.svg(matrix)
        self.assertTrue(art.startswith("<svg"))
        self.assertIn('viewBox', art)

    def test_png_signature_and_size(self):
        matrix = qr.make(b"https://example.com")
        raw = qr.png_bytes(matrix, scale=4)
        self.assertTrue(raw.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertGreater(len(raw), 100)

    def test_wifi_payload_escaping(self):
        out = qr.wifi_payload('My;Net,name', 'pass\\"word')
        self.assertEqual(out, "WIFI:T:WPA;S:My\\;Net\\,name;P:pass\\\\\\\"word;;")

    def test_too_long_raises(self):
        with self.assertRaises(qr.QRError):
            qr.make(b"x" * 300)


if __name__ == "__main__":
    unittest.main()
