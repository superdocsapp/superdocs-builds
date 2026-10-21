"""Drives a real LTI 1.3 launch through Moodle via raw HTTP - login, JWT launch, Deep
Linking, and (with the review flow + AGS complete done separately, see README) a real
gradebook score.

Written because no browser automation was available in the environment this was built in;
kept and shipped because it's the actual mechanism this whole tool's "what strong looks
like" bar was verified against - a stranger can rerun it against their own local Moodle
and see the same three things checked for real: JWT signature verification against
Moodle's live JWKS, an actual Deep Linking placement, and (combined with the review API,
see README) a real AGS score write.

Usage (after moodle-dev/register_tool.php and create_test_fixtures.php have run, and
app.py is running on :9001):

    pip install requests beautifulsoup4
    python verify_launch.py deep-link dpa            # places the assignment, admin login
    python verify_launch.py launch <cmid> student1    # opens it, prints a launch_id to
                                                        # drive the review API against
"""

from __future__ import annotations

import json
import pathlib
import re
import socket
import sys

import requests
from bs4 import BeautifulSoup

MOODLE = "http://localhost:8085"
TOOL = "http://localhost:9001"

# host.docker.internal only resolves from inside a container; Moodle's rendered forms
# target it for the server-to-server hops (see register_tool.php's comment on this), but
# this script runs on the host, where it should just mean "127.0.0.1".
_real_getaddrinfo = socket.getaddrinfo


def _patched_getaddrinfo(host, *args, **kwargs):
    if host == "host.docker.internal":
        host = "127.0.0.1"
    return _real_getaddrinfo(host, *args, **kwargs)


socket.getaddrinfo = _patched_getaddrinfo


def login_moodle(session: requests.Session, username: str, password: str) -> requests.Response:
    r = session.get(f"{MOODLE}/login/index.php")
    soup = BeautifulSoup(r.text, "html.parser")
    token = soup.find("input", {"name": "logintoken"})["value"]
    r = session.post(
        f"{MOODLE}/login/index.php",
        data={"username": username, "password": password, "logintoken": token},
    )
    if "loginerrors" in r.text or "Invalid login" in r.text:
        raise RuntimeError("Moodle login failed")
    return r


def follow_auto_submit(
    session: requests.Session, html: str, label: str, request_url: str | None = None
) -> requests.Response:
    """Handles both hop shapes this flow produces: Moodle and pylti1p3 sometimes render a
    real auto-submitting <form> (POST); pylti1p3's OIDC login endpoint instead renders a
    same-page cookie-availability check that JS-redirects (GET) to itself with the OIDC
    params appended as a query string - no <form> at all in that case."""
    soup = BeautifulSoup(html, "html.parser")
    form = soup.find("form")
    if form:
        action = form.get("action")
        fields = {i.get("name"): i.get("value", "") for i in form.find_all("input") if i.get("name")}
        print(f"[{label}] POST -> {action}")
        return session.post(action, data=fields, allow_redirects=True)

    m = re.search(r"var urlParams = (\{.*?\});", html)
    if m:
        # The JSON blob itself parses as-is; &quot; only needs unescaping *inside*
        # individual string values afterward (mirrors the page's own
        # unescapeHtmlEntities()) - unescaping the raw blob first corrupts its own
        # delimiting quotes.
        params = json.loads(m.group(1))
        params = {k: v.replace("&quot;", '"') if isinstance(v, str) else v for k, v in params.items()}
        print(f"[{label}] GET (js redirect) -> {request_url} params={list(params)}")
        return session.get(request_url, params=params, allow_redirects=True)

    raise RuntimeError("no auto-submit form or JS redirect found:\n" + html[:2000])


def run_deep_link(session: requests.Session, tool_id: int, course_id: int, doc_id: str) -> requests.Response:
    print("=== Deep Linking: placing the assignment ===")
    r = session.get(f"{MOODLE}/mod/lti/contentitem.php", params={"id": tool_id, "course": course_id})
    print("[contentitem.php] status", r.status_code)
    r = follow_auto_submit(session, r.text, "oidc-init -> tool /login/", request_url=r.url)
    r = follow_auto_submit(session, r.text, "platform auth -> tool /login/ redirect", request_url=r.url)
    if "id_token" in r.text and "<form" in r.text:
        r = follow_auto_submit(session, r.text, "platform id_token -> tool /launch/ (deep link)")
    print("[tool /launch/ deep-link] status", r.status_code)
    if "Place a document review" not in r.text:
        raise RuntimeError("did not land on the deep-link picker page:\n" + r.text[:1000])
    print("landed on deep-link picker page correctly - JWT verified against Moodle's live JWKS")

    m = re.search(r'/configure/([^/"]+)/', r.text)
    launch_id = m.group(1)
    print("launch_id:", launch_id)

    r = session.post(f"{TOOL}/configure/{launch_id}/{doc_id}/")
    print("[tool /configure/] status", r.status_code)

    # The deep-link response form (rendered by pylti1p3's DeepLink.output_response_form)
    # carries the signed response as a hidden input named "JWT" - save it before following
    # the auto-submit, since finalize_deeplink_headless.php needs this exact JWT (it's what
    # a browser's cross-window JS handshake would have handed to Moodle's own "add
    # activity" form - see that script's docstring).
    jwt_soup = BeautifulSoup(r.text, "html.parser")
    jwt_input = jwt_soup.find("input", {"name": "JWT"})
    if jwt_input:
        jwt_path = pathlib.Path(__file__).parent / "deeplink_jwt.txt"
        jwt_path.write_text(jwt_input["value"])
        print(f"deep-link response JWT saved to {jwt_path}")
        print(
            "Finalize it into a real course module (run from moodle-dev/):\n"
            f"  docker cp {jwt_path} $(docker compose ps -q moodle):/tmp/deeplink_jwt.txt\n"
            "  docker compose exec moodle php /tmp/finalize_deeplink_headless.php"
        )

    r = follow_auto_submit(session, r.text, "deep-link response -> contentitem_return.php")
    print("[contentitem_return.php] status", r.status_code, r.url)
    return r


def run_resource_link_launch(session: requests.Session, cmid: str) -> str:
    print("=== Resource-link launch: opening the placed assignment ===")
    # The course page (view.php) embeds the actual launch as an iframe pointed at
    # launch.php - that iframe's src is the real trigger, not view.php itself.
    r = session.get(f"{MOODLE}/mod/lti/launch.php", params={"id": cmid, "triggerview": 0})
    print("[launch.php] status", r.status_code)
    r = follow_auto_submit(session, r.text, "oidc-init -> tool /login/", request_url=r.url)
    r = follow_auto_submit(session, r.text, "platform auth -> tool /login/ redirect", request_url=r.url)
    if "id_token" in r.text and "<form" in r.text:
        r = follow_auto_submit(session, r.text, "platform id_token -> tool /launch/ (resource link)")
    print("[tool /launch/ resource-link] status", r.status_code)
    m = re.search(r'const launchId = "([^"]+)"', r.text)
    if not m:
        raise RuntimeError("did not land on the review page:\n" + r.text[:2000])
    launch_id = m.group(1)
    print("landed on review page - JWT verified against Moodle's live JWKS. launch_id:", launch_id)
    return launch_id


if __name__ == "__main__":
    action = sys.argv[1]
    username = sys.argv[3] if len(sys.argv) > 3 else "admin"
    password = "Sup3rD0csTest!"
    s = requests.Session()
    login_moodle(s, username, password)
    print(f"logged in as {username}")

    if action == "deep-link":
        run_deep_link(s, tool_id=1, course_id=2, doc_id=sys.argv[2] if len(sys.argv) > 2 else "dpa")
    elif action == "launch":
        cmid = sys.argv[2]
        launch_id = run_resource_link_launch(s, cmid)
        print("LAUNCH_ID=" + launch_id)
    else:
        print("usage: verify_launch.py {deep-link <doc_id>|launch <cmid> [username]}")
        raise SystemExit(1)
