#!/usr/bin/env python3
"""
Serve the badge under camo's exact response headers, so the browser applies the
real policy to it.

`verify_badge.py` reads the file and reasons about it. This does the opposite:
it hands the file to a browser under the same Content-Security-Policy,
Content-Type and nosniff that camo.githubusercontent.com returns, inside an
<img> — the element GitHub actually uses — and lets the browser be the judge.
Static analysis says "nothing in here should violate the policy"; this says
"the policy was applied and the image still rendered."

It is not the real test. The real test is a badge in a README on github.com,
which needs a published URL. This is the strongest test available before
publishing, and the difference is worth stating rather than glossing.

Headers copied verbatim from a live camo response, 2026-08-16.

Usage:  python3 camo_sim.py            # serve on :8731 until interrupted
        python3 camo_sim.py --check    # serve, render in headless Chrome, report
"""

from __future__ import annotations

import argparse
import http.server
import json
import subprocess
import sys
import tempfile
import threading
from functools import partial
from pathlib import Path

HERE = Path(__file__).resolve().parent
BADGE = HERE / "badge.svg"
PORT = 8731

# Verbatim from camo.githubusercontent.com on a live proxied badge.
CAMO_HEADERS = {
    "Content-Type": "image/svg+xml;charset=utf-8",
    "Content-Security-Policy": "default-src 'none'; img-src data:; style-src 'unsafe-inline'",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "deny",
    "Cache-Control": "max-age=120, s-maxage=120",
}

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

# A README-shaped page: the badge in an <img>, exactly as GitHub renders it.
PAGE = """<!doctype html><meta charset="utf-8">
<body style="margin:0;background:#fff">
<img id="b" src="http://127.0.0.1:{port}/badge.svg" alt="built with SuperDocs">
<script>
window.addEventListener('load', () => {{
  const b = document.getElementById('b');
  document.title = JSON.stringify({{
    complete: b.complete,
    naturalWidth: b.naturalWidth,
    naturalHeight: b.naturalHeight,
  }});
}});
</script>
"""


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/badge.svg":
            self.send_error(404)
            return
        body = BADGE.read_bytes()
        self.send_response(200)
        for k, v in CAMO_HEADERS.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def serve() -> http.server.HTTPServer:
    httpd = http.server.HTTPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def check() -> int:
    httpd = serve()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            page = Path(tmp) / "readme.html"
            page.write_text(PAGE.format(port=PORT), encoding="utf-8")
            out = subprocess.run(
                [CHROME, "--headless", "--disable-gpu", "--dump-dom",
                 "--virtual-time-budget=4000", str(page)],
                capture_output=True, text=True, timeout=90,
            ).stdout

        title = ""
        if "<title>" in out:
            title = out.split("<title>", 1)[1].split("</title>", 1)[0]
        try:
            state = json.loads(title.replace("&quot;", '"'))
        except json.JSONDecodeError:
            print("could not read the image state back from the page")
            print(title[:200])
            return 1

        w, h = state.get("naturalWidth"), state.get("naturalHeight")
        print(f"\nServed under camo's headers:")
        for k, v in CAMO_HEADERS.items():
            print(f"  {k}: {v}")
        print(f"\nBrowser decoded the image: {state}")

        ok = bool(state.get("complete")) and w == 133 and h == 20
        print(f"\n{'PASS' if ok else 'FAIL'} — the policy was applied and the badge "
              f"{'rendered at its declared size' if ok else 'did not render as declared'}.")
        if not ok:
            print("A naturalWidth of 0 means the browser refused the resource, not "
                  "that the drawing is wrong.")
        print("\nStill unproven here: GitHub's own markdown pipeline, and camo's "
              "fetch of the origin. Both need a published URL.")
        return 0 if ok else 1
    finally:
        httpd.shutdown()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    if args.check:
        return check()
    serve()
    print(f"badge at http://127.0.0.1:{PORT}/badge.svg under camo headers — ctrl-c to stop")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
