from __future__ import annotations

import hashlib
import json
import time
from typing import TYPE_CHECKING, Any

import httpx
from starlette.requests import Request
from starlette.responses import Response

if TYPE_CHECKING:
    from gateway.audit import AuditLog
    from gateway.policy import Policy, TeamPolicy

from gateway.audit import AuditWriteError
from gateway.quota import QuotaStore
from gateway.scanner import BASE64_SCAN_FIELDS, TEXT_SCAN_FIELDS, Scanner, extract_text_from_base64

_SKIP_REQUEST_HEADERS = frozenset(
    {
        "host",
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "transfer-encoding",
        "upgrade",
        "content-length",
    }
)

_SKIP_RESPONSE_HEADERS = frozenset(
    {
        "connection",
        "keep-alive",
        "transfer-encoding",
        "content-length",
        "content-encoding",
    }
)


# Deliberately explicit: this string is what an operator sees in a client's
# error report, and it has to route them to the platform team without a
# debugging session.
_AUDIT_UNAVAILABLE = (
    "gateway storage fault — the audit log cannot be written, so this call was "
    "refused rather than served unrecorded. This is a fault on the gateway host, "
    "not a problem with your request. Report it to your platform team"
)


def _blocked(hits: set[str]) -> str:
    return f"content blocked by scan rules: {', '.join(sorted(hits))}"


def _json_error(rpc_id: int | str | None, code: int, message: str, http_status: int) -> Response:
    body = {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": code, "message": message}}
    return Response(
        content=json.dumps(body).encode(),
        status_code=http_status,
        media_type="application/json",
    )


class Proxy:
    """Forwards MCP requests to an upstream server, optionally enforcing policy gates."""

    def __init__(
        self,
        upstream_url: str,
        *,
        client: httpx.AsyncClient | None = None,
        policy: Policy | None = None,
        quota_store: QuotaStore | None = None,
        audit_log: AuditLog | None = None,
    ) -> None:
        self._upstream = upstream_url
        self._client = client
        self._owns_client = client is None
        self._policy = policy
        self._quota = quota_store
        self._audit = audit_log

    async def start(self) -> None:
        if self._owns_client:
            self._client = httpx.AsyncClient(timeout=60.0)
        # Refuse to boot into a state where every request would 503. A
        # container that dies on startup with a clear reason is far easier to
        # diagnose than one that comes up healthy and rejects all traffic.
        if self._audit is not None:
            self._audit.preflight()

    async def stop(self) -> None:
        if self._owns_client and self._client:
            await self._client.aclose()

    async def forward(self, request: Request) -> Response:
        assert self._client is not None
        body = await request.body()

        if not self._policy:
            return await self._passthrough(request, body)

        return await self._forward_with_policy(request, body)

    # ── Passthrough (no policy) ──────────────────────────────────────────

    async def _passthrough(self, request: Request, body: bytes) -> Response:
        headers = {
            k: v for k, v in request.headers.items() if k.lower() not in _SKIP_REQUEST_HEADERS
        }
        return await self._send_and_respond(body, headers)

    # ── Policy-enforced forwarding ───────────────────────────────────────

    async def _forward_with_policy(self, request: Request, body: bytes) -> Response:
        """Run the gate chain, then record what happened.

        The audit entry is built as the request descends the chain, so a request
        rejected at gate ④ is logged with the same shape as one that reached
        upstream. A gateway that only logs the calls it allowed cannot answer
        the question people actually ask it — *what did we stop?*
        """
        started = time.perf_counter()

        # Fail closed, and say WHY. A gateway that cannot record a call refuses
        # to serve it — but the caller is not at fault and cannot fix it, so the
        # error names storage explicitly rather than returning a generic 503
        # that gets misread as "SuperDocs is down" and never reaches the team
        # who can actually clear the disk.
        if self._audit is not None:
            try:
                self._audit.preflight()
            except AuditWriteError as exc:
                return _json_error(None, -32000, f"{_AUDIT_UNAVAILABLE}: {exc}", 503)

        rec: dict[str, Any] = {
            "team": None,
            "method": None,
            "tool": None,
            "decision": "error",
            "reason": None,
            "req_bytes": len(body),
            # The hash, never the body. See gateway/audit.py.
            "payload_sha256": hashlib.sha256(body).hexdigest(),
            "auth_stripped": False,
            "arg_rewrites": [],
            "scan_hits": [],
            "billed": 0,
            "upstream_status": None,
            "resp_bytes": 0,
        }

        response = await self._run_gates(request, body, rec)

        rec["latency_ms"] = round((time.perf_counter() - started) * 1000, 2)
        rec["resp_bytes"] = len(response.body)

        if self._audit is not None:
            try:
                self._audit.append(rec)
            except AuditWriteError as exc:
                # The narrow window preflight cannot close: the disk filled
                # between the check and the write. The upstream call may have
                # completed, so the message says so rather than implying the
                # operation did not happen.
                return _json_error(
                    None,
                    -32000,
                    f"{_AUDIT_UNAVAILABLE}: {exc}. The upstream call may have "
                    f"completed — check SuperDocs before retrying.",
                    503,
                )
        return response

    async def _run_gates(self, request: Request, body: bytes, rec: dict[str, Any]) -> Response:
        assert self._policy is not None

        # Gate ① — Identity
        team = self._identify(request)
        if team is None:
            rec["decision"] = "unauthorized"
            rec["reason"] = "no matching team token"
            return _json_error(None, -32000, "unauthorized", 401)
        rec["team"] = team.name

        # Gate ② — Envelope
        rpc, err = self._parse_envelope(body)
        if err is not None:
            rec["decision"] = "invalid_envelope"
            rec["reason"] = "malformed JSON-RPC request"
            return err

        method = rpc.get("method", "")
        rpc_id = rpc.get("id")
        rec["method"] = method

        # Gate ③ — Strip arguments.authorization
        #
        # Recorded rather than merely done: an agent passing its own credential
        # is either misconfigured or probing, and both are worth alerting on.
        modified = self._strip_auth_arg(rpc)
        rec["auth_stripped"] = modified

        is_call = method == "tools/call"
        tool_name = rpc.get("params", {}).get("name", "") if is_call else ""
        if is_call:
            rec["tool"] = tool_name

        # Gate ④ — Tool allowlist
        if is_call:
            denial = self._check_allowlist(tool_name, team)
            if denial is not None:
                rec["decision"] = "denied_tool"
                rec["reason"] = denial
                return _json_error(rpc_id, -32602, denial, 403)

        # Gate ⑤ — Argument policy
        if is_call:
            denial, rewrites = self._apply_arg_policy(rpc, team)
            rec["arg_rewrites"] = rewrites
            if denial is not None:
                rec["decision"] = "denied_argument"
                rec["reason"] = denial
                return _json_error(rpc_id, -32602, denial, 403)
            modified = modified or bool(rewrites)

        # Gate ⑥ — Content scan
        if is_call:
            denial, changed, hits = self._scan_content(rpc, team)
            # Rule names only. The matched text is exactly what must not be here.
            rec["scan_hits"] = hits
            if denial is not None:
                rec["decision"] = "blocked_content"
                rec["reason"] = denial
                return _json_error(rpc_id, -32602, denial, 403)
            modified = modified or changed

        if modified:
            body = json.dumps(rpc).encode()

        # Gate ⑦ — Quota reserve
        reserved = self._quota_reserve(team, tool_name)
        if reserved is False:
            rec["decision"] = "quota_exhausted"
            rec["reason"] = f"monthly_edits exhausted for team={team.name}"
            return _json_error(rpc_id, -32000, f"quota exhausted for team={team.name}", 429)

        # Swap auth and forward
        headers = self._upstream_headers(request)
        resp = await self._send(body, headers)
        if resp is None:
            self._quota_release(team, tool_name)
            rec["decision"] = "upstream_unavailable"
            rec["reason"] = "transport failure reaching upstream"
            return _json_error(rpc_id, -32000, "upstream unavailable", 502)

        rec["upstream_status"] = resp.status_code

        # Settle or release quota based on response. A failed call bills 0
        # upstream, so the audit's `billed` must agree with the real invoice.
        if resp.status_code >= 400:
            self._quota_release(team, tool_name)
            rec["decision"] = "upstream_error"
            rec["reason"] = f"upstream returned {resp.status_code}"
        else:
            self._quota_settle(team, tool_name)
            rec["decision"] = "allowed"
            if self._quota is not None and self._quota.is_billable(tool_name):
                rec["billed"] = 1

        # Gate ⑧ (partial) — Filter tools/list response
        if method == "tools/list":
            return self._filter_tools_response(resp, team)

        return self._build_response(resp)

    # ── Gate ① helpers ───────────────────────────────────────────────────

    def _identify(self, request: Request) -> TeamPolicy | None:
        assert self._policy is not None
        auth = request.headers.get("authorization", "")
        if not auth.lower().startswith("bearer "):
            return None
        token = auth[7:]
        if not token:
            return None
        return self._policy.identify(token)

    # ── Gate ② helpers ───────────────────────────────────────────────────

    @staticmethod
    def _parse_envelope(body: bytes) -> tuple[dict, Response | None]:
        try:
            rpc = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}, _json_error(None, -32700, "parse error", 400)

        if not isinstance(rpc, dict):
            return {}, _json_error(None, -32600, "invalid request", 400)

        rpc_id = rpc.get("id")
        if rpc.get("jsonrpc") != "2.0":
            return {}, _json_error(rpc_id, -32600, "invalid request", 400)
        if "method" not in rpc or not isinstance(rpc["method"], str):
            return {}, _json_error(rpc_id, -32600, "invalid request", 400)

        return rpc, None

    # ── Gate ③ helpers ───────────────────────────────────────────────────

    @staticmethod
    def _strip_auth_arg(rpc: dict) -> bool:
        if rpc.get("method") != "tools/call":
            return False
        args = rpc.get("params", {}).get("arguments")
        if isinstance(args, dict) and "authorization" in args:
            del args["authorization"]
            return True
        return False

    # ── Gate ④ helpers ───────────────────────────────────────────────────

    def _check_allowlist(self, tool_name: str, team: TeamPolicy) -> str | None:
        """Returns a denial reason, or None if the tool is permitted."""
        assert self._policy is not None
        if self._policy.is_tool_allowed(team, tool_name):
            return None

        msg = f"tool '{tool_name}' is not permitted for team={team.name}"
        if "*" not in team.allow_tools:
            alt = sorted(team.allow_tools - {tool_name})
            if alt:
                msg += f". permitted alternatives: {', '.join(alt)}"
        return msg

    # ── Gate ⑤ helpers ───────────────────────────────────────────────────

    def _apply_arg_policy(self, rpc: dict, team: TeamPolicy) -> tuple[str | None, list[str]]:
        """Returns (denial reason or None, list of rewrites applied)."""
        assert self._policy is not None
        args = rpc.get("params", {}).get("arguments")
        if not isinstance(args, dict):
            return None, []
        tool_name = rpc.get("params", {}).get("name", "")
        rewrites, error = self._policy.apply_arg_rules(team, tool_name, args)
        if error:
            return error, []
        return None, rewrites

    # ── Gate ⑥ helpers ───────────────────────────────────────────────────

    def _scan_content(self, rpc: dict, team: TeamPolicy) -> tuple[str | None, bool, list[str]]:
        """Returns (denial reason or None, body was rewritten, rule names hit).

        The hits list is returned even when the scan does not block — a `mask`
        or `warn` team still wants the match visible in the audit trail.
        """
        assert self._policy is not None
        scan_cfg = self._policy.get_scan_config(team)
        if scan_cfg is None:
            return None, False, []

        tool_name = rpc.get("params", {}).get("name", "")
        args = rpc.get("params", {}).get("arguments", {})
        if not isinstance(args, dict):
            return None, False, []

        scanner = Scanner(scan_cfg.rules)
        modified = False
        hits: set[str] = set()

        for field_name in TEXT_SCAN_FIELDS.get(tool_name, ()):
            value = args.get(field_name)
            if not isinstance(value, str) or not value:
                continue
            result = scanner.scan_text(value, field_name)
            if not result.matches:
                continue
            hits.update(m.rule for m in result.matches)
            action = scan_cfg.on_match
            if action == "block":
                return _blocked(hits), False, sorted(hits)
            if action == "mask":
                args[field_name] = scanner.mask_text(value, result.matches)
                modified = True

        for field_name in BASE64_SCAN_FIELDS.get(tool_name, ()):
            value = args.get(field_name)
            if not isinstance(value, str) or not value:
                continue
            text = extract_text_from_base64(value)
            if not text:
                continue
            result = scanner.scan_text(text, field_name)
            if not result.matches:
                continue
            hits.update(m.rule for m in result.matches)
            # `mask` falls back to blocking here: rewriting text inside a .docx
            # means rebuilding the ZIP, which v1 does not attempt. Passing the
            # upload through unmasked would be the dishonest option.
            if scan_cfg.on_match in ("block", "mask"):
                return _blocked(hits), False, sorted(hits)

        return None, modified, sorted(hits)

    # ── Gate ⑦ helpers ───────────────────────────────────────────────────

    def _quota_reserve(self, team: TeamPolicy, tool_name: str) -> bool | None:
        if self._quota is None or not self._quota.is_billable(tool_name):
            return None
        tq = self._quota.get(team.name)
        if tq is None:
            return None
        return tq.reserve()

    def _quota_settle(self, team: TeamPolicy, tool_name: str) -> None:
        if self._quota is None or not self._quota.is_billable(tool_name):
            return
        tq = self._quota.get(team.name)
        if tq is not None:
            tq.settle()

    def _quota_release(self, team: TeamPolicy, tool_name: str) -> None:
        if self._quota is None or not self._quota.is_billable(tool_name):
            return
        tq = self._quota.get(team.name)
        if tq is not None:
            tq.release()

    # ── Upstream communication ───────────────────────────────────────────

    def _upstream_headers(self, request: Request) -> dict[str, str]:
        assert self._policy is not None
        headers = {
            k: v for k, v in request.headers.items() if k.lower() not in _SKIP_REQUEST_HEADERS
        }
        headers["authorization"] = f"Bearer {self._policy.upstream_key}"
        return headers

    async def _send(self, body: bytes, headers: dict[str, str]) -> httpx.Response | None:
        assert self._client is not None
        try:
            return await self._client.post(self._upstream, content=body, headers=headers)
        except httpx.HTTPError:
            return None

    async def _send_and_respond(self, body: bytes, headers: dict[str, str]) -> Response:
        resp = await self._send(body, headers)
        if resp is None:
            return _json_error(None, -32000, "upstream unavailable", 502)
        return self._build_response(resp)

    # ── Response building ────────────────────────────────────────────────

    @staticmethod
    def _build_response(resp: httpx.Response) -> Response:
        headers = {k: v for k, v in resp.headers.items() if k.lower() not in _SKIP_RESPONSE_HEADERS}
        return Response(content=resp.content, status_code=resp.status_code, headers=headers)

    def _filter_tools_response(self, resp: httpx.Response, team: TeamPolicy) -> Response:
        assert self._policy is not None
        if resp.status_code != 200:
            return self._build_response(resp)
        try:
            data = json.loads(resp.content)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return self._build_response(resp)

        tools = data.get("result", {}).get("tools", [])
        data["result"]["tools"] = [
            t for t in tools if self._policy.is_tool_allowed(team, t.get("name", ""))
        ]
        return Response(
            content=json.dumps(data).encode(),
            status_code=200,
            media_type="application/json",
        )
