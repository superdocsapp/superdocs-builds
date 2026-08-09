#!/usr/bin/env python3
"""Serves this folder over HTTPS on localhost:3001 -- no Node/npm required.

Word refuses to load an add-in's taskpane over plain HTTP, even on
localhost, so sideloading needs *some* local HTTPS server. Rather than
pulling in the conventional `office-addin-dev-certs` + webpack-dev-server
toolchain (which needs Node), this generates a one-off self-signed
certificate with `openssl` (ships with Git for Windows / any Mac or Linux
shell) and serves the folder with Python's standard library.

Usage:
    python serve.py

Then in Word: Insert > Add-ins > My Add-ins > Upload My Add-in > manifest.xml
Your browser and Word will both warn about the self-signed certificate the
first time; that's expected for local development, not a bug.
"""
from __future__ import annotations

import http.server
import ssl
import subprocess
import sys
from pathlib import Path

PORT = 3001
HERE = Path(__file__).resolve().parent
CERT_DIR = HERE / ".certs"
CERT_FILE = CERT_DIR / "cert.pem"
KEY_FILE = CERT_DIR / "key.pem"


def ensure_cert() -> None:
    if CERT_FILE.exists() and KEY_FILE.exists():
        return
    CERT_DIR.mkdir(exist_ok=True)
    print("No local dev certificate found -- generating one with openssl...")
    try:
        subprocess.run(
            [
                "openssl", "req", "-x509", "-newkey", "rsa:2048",
                "-keyout", str(KEY_FILE), "-out", str(CERT_FILE),
                "-days", "365", "-nodes",
                "-subj", "/CN=localhost",
                "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1",
            ],
            check=True,
        )
    except FileNotFoundError:
        print(
            "openssl was not found on PATH. On Windows, run this from Git Bash "
            "(it ships with Git for Windows); on macOS/Linux it's normally "
            "preinstalled. Alternatively, generate cert.pem/key.pem yourself "
            f"and place them at {CERT_DIR}.",
            file=sys.stderr,
        )
        sys.exit(1)


class Handler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        # Not required for sideloading, but avoids stale-cache surprises
        # while iterating on the taskpane during development.
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


def main() -> None:
    ensure_cert()
    httpd = http.server.HTTPServer(("localhost", PORT), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile=str(CERT_FILE), keyfile=str(KEY_FILE))
    httpd.socket = context.wrap_socket(httpd.socket, server_side=True)
    print(f"Serving {HERE} at https://localhost:{PORT}/taskpane.html")
    print("Press Ctrl+C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    import os

    os.chdir(HERE)
    main()
