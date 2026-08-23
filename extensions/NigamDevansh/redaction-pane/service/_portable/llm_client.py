# ─────────────────────────────────────────────────────────────────────
# COPIED FILE — do not edit here.
# Source: packages/core/src/doctask_core/portable/llm_client.py
# Refresh: uv run python scripts/sync_portable.py
# This app is standalone by design and imports nothing outside itself.
# ─────────────────────────────────────────────────────────────────────
"""LLM access behind one protocol, three provider implementations.

PORTABLE: zero internal imports.
Source of truth. Copies live in each extension's `_portable/`.

`structured` is a correctness feature: it stops the model inventing a
`field_key` outside the taxonomy and forces the party-picker to choose GLiNER
spans by index. Three things this file insists on: we validate the schema
ourselves (`jsonschema` means the same for all three providers); every attempt
is counted, including failed retries; and provider SDKs import lazily, so an
extension using one provider need not install the others.

See docs/CORE_INTERNALS.md § "portable/llm_client.py".
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol


class LLMError(Exception):
    """Base — declared inline so this file stays copyable."""


class LLMSchemaViolation(LLMError):
    """Output did not match the schema after the bounded retries."""


class LLMTransportError(LLMError):
    """Provider unreachable, or refusing for a reason that may pass."""


class LLMQuotaExhausted(LLMTransportError):
    """Out of credit or over a hard limit. Not retried — distinct from a rate
    limit, which shares the 429 status and is worth waiting for. A subclass of
    `LLMTransportError` so "the provider did not answer" still catches it."""


@dataclass(frozen=True, slots=True)
class Usage:
    """Normalised across providers, so telemetry never branches on vendor."""

    model: str
    input_tokens: int
    output_tokens: int
    attempts: int = 1
    """Counts failures too. A retry that succeeded on attempt three still cost
    tokens, and a cost report that hides that is lying."""


class LLMClient(Protocol):
    def complete(self, *, system: str, user: str, max_tokens: int) -> tuple[str, Usage]: ...

    def structured(
        self, *, system: str, user: str, schema: dict[str, Any], max_tokens: int
    ) -> tuple[dict[str, Any], Usage]: ...


# ── schema enforcement ────────────────────────────────────────────────────


def check_schema(schema: dict[str, Any]) -> None:
    """Raise if the schema itself is malformed. Called BEFORE any request — a
    schema we wrote wrong is our bug, and discovering it from a response means it
    was already sent, retried and billed. Checking first costs nothing."""
    import jsonschema

    try:
        jsonschema.Draft202012Validator.check_schema(schema)
    except jsonschema.SchemaError as exc:
        raise LLMError(f"the schema itself is invalid: {exc.message}") from exc


def schema_error(payload: Any, schema: dict[str, Any]) -> str | None:
    """Return why `payload` fails `schema`, or None. A message, not a bool,
    because it is handed to the model on the repair attempt: "invalid" tells it
    nothing; "'currency' is not one of ['USD','EUR']" tells it what to change."""
    import jsonschema

    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError as exc:
        location = "/".join(str(p) for p in exc.absolute_path) or "(root)"
        return f"at {location}: {exc.message}"
    except jsonschema.SchemaError as exc:
        # Ours, not the model's. Retrying cannot fix a schema we wrote wrong.
        raise LLMError(f"the schema itself is invalid: {exc.message}") from exc
    return None


REPAIR_PREFIX = "Your previous reply did not satisfy the required JSON schema"
"""Recognisable in `FakeLLM.calls`, so a test can assert a repair happened
without matching on the whole sentence."""


def repair_instruction(error: str) -> str:
    """The retry note, appended to the SYSTEM prompt, never the user turn. The
    user turn carries document text, and instructions are ours, not concatenated
    from a document — so a retry cannot change what "the document said"."""
    return f"\n\n{REPAIR_PREFIX}: {error}\nReply with corrected JSON only."


# ── shared retry and accounting ───────────────────────────────────────────


PERMANENT_QUOTA_MARKERS = (
    "no credits remaining",
    "insufficient_quota",
    "credit_balance_exhausted",
    "billing",
)
"""Substrings that mean waiting will not help. Matching message text is crude and
the only portable option — naming `openai.RateLimitError` would drag the SDK into
every copy. Narrow on purpose: an unmatched message just retries normally."""

_RETRY_AFTER = re.compile(r"retry(?:Delay|.{0,12}?in)\D{0,4}?(\d+(?:\.\d+)?)\s*s", re.IGNORECASE)
MAX_BACKOFF_S = 60.0


def retry_delay(message: str, attempt: int, base: float) -> float:
    """How long to wait before attempt `attempt + 1`. Providers that rate-limit
    usually say how long (Gemini returns `retryDelay: '13s'`); honouring it beats
    three attempts failing in four seconds. Exponential backoff is the fallback,
    capped so a hostile value can't park a run for an hour."""
    stated = _RETRY_AFTER.search(message)
    if stated:
        return min(float(stated.group(1)), MAX_BACKOFF_S)
    return min(base * (2**attempt), MAX_BACKOFF_S)


class _RetryingClient:
    """Retry bookkeeping shared by the three providers. Subclasses implement two
    hooks and nothing else, so retry policy, token accounting and the schema gate
    cannot drift between vendors."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        max_retries: int = 3,
        backoff_s: float = 1.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not api_key:
            raise LLMError(f"{type(self).__name__}: an API key is required")
        self._api_key = api_key
        self.model = model
        self.max_retries = max(1, max_retries)
        self.backoff_s = backoff_s
        self._sleep = sleep
        """Injected rather than patched, the same way lease TTLs are. Tests pass
        a no-op and run in milliseconds without a clock library."""
        self._sdk: Any = None

    # ── hooks ─────────────────────────────────────────────────────────────
    def _client(self) -> Any:
        """Build the vendor SDK client. Called once, on first use."""
        raise NotImplementedError

    def _call(
        self, *, system: str, user: str, max_tokens: int, schema: dict[str, Any] | None
    ) -> tuple[str, int, int]:
        """One request. Returns (text, input_tokens, output_tokens)."""
        raise NotImplementedError

    # ── shared ────────────────────────────────────────────────────────────
    def sdk(self) -> Any:
        if self._sdk is None:
            self._sdk = self._client()
        return self._sdk

    def _attempt(
        self, *, system: str, user: str, max_tokens: int, schema: dict[str, Any] | None
    ) -> tuple[str, int, int]:
        try:
            return self._call(system=system, user=user, max_tokens=max_tokens, schema=schema)
        except LLMError:
            raise
        except Exception as exc:  # noqa: BLE001 — every vendor raises its own tree
            detail = f"{self.model}: {type(exc).__name__}: {exc}"
            if any(marker in str(exc).lower() for marker in PERMANENT_QUOTA_MARKERS):
                raise LLMQuotaExhausted(detail) from exc
            raise LLMTransportError(detail) from exc

    def _wait(self, message: str, attempt: int) -> None:
        """Sleep only when another attempt remains. A stated delay is honoured,
        so waiting after the last failure would hold a run for a `retryDelay: 60s`
        purely to return an error it already had."""
        if attempt + 1 >= self.max_retries:
            return
        self._sleep(retry_delay(message, attempt, self.backoff_s))

    def complete(self, *, system: str, user: str, max_tokens: int) -> tuple[str, Usage]:
        totals = _Totals()
        last: Exception | None = None
        for attempt in range(self.max_retries):
            totals.attempts += 1
            try:
                text, sent, got = self._attempt(
                    system=system, user=user, max_tokens=max_tokens, schema=None
                )
            except LLMQuotaExhausted:
                raise
            except LLMTransportError as exc:
                last = exc
                self._wait(str(exc), attempt)
                continue
            totals.add(sent, got)
            return text, totals.usage(self.model)
        raise LLMTransportError(
            f"{self.model}: failed after {totals.attempts} attempt(s) — {last}"
        ) from last

    def structured(
        self, *, system: str, user: str, schema: dict[str, Any], max_tokens: int
    ) -> tuple[dict[str, Any], Usage]:
        # Before spending anything. A malformed schema is ours to fix, and the
        # policy that it must not be retried is only true if we never send it.
        check_schema(schema)

        totals = _Totals()
        system_now = system
        last = "no attempt completed"
        transport: Exception | None = None
        answered = False
        """Whether ANY attempt came back with a reply to judge. Without it the
        failure modes collapse: three rate-limited calls would raise
        `LLMSchemaViolation`, sending a log reader to debug a taxonomy when the
        provider simply never answered."""

        for attempt in range(self.max_retries):
            totals.attempts += 1
            try:
                text, sent, got = self._attempt(
                    system=system_now, user=user, max_tokens=max_tokens, schema=schema
                )
            except LLMQuotaExhausted:
                raise
            except LLMTransportError as exc:
                transport = exc
                last = str(exc)
                self._wait(last, attempt)
                continue
            answered = True
            totals.add(sent, got)

            try:
                payload = json.loads(text)
            except json.JSONDecodeError as exc:
                last = f"reply was not JSON: {exc}"
                system_now = system + repair_instruction(last)
                continue

            problem = schema_error(payload, schema)
            if problem is None:
                if not isinstance(payload, dict):
                    # A schema permitting a bare array or scalar is legal JSON
                    # Schema but breaks this method's return type. Ours to fix.
                    raise LLMError(f"{self.model}: schema allows a non-object top level")
                return payload, totals.usage(self.model)

            last = problem
            system_now = system + repair_instruction(problem)

        if not answered:
            raise LLMTransportError(
                f"{self.model}: no reply in {totals.attempts} attempt(s) — {last}"
            ) from transport
        raise LLMSchemaViolation(
            f"{self.model}: no valid reply in {totals.attempts} attempt(s) — {last}"
        )


@dataclass
class _Totals:
    attempts: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    def add(self, sent: int, got: int) -> None:
        self.input_tokens += sent
        self.output_tokens += got

    def usage(self, model: str) -> Usage:
        return Usage(
            model=model,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            attempts=self.attempts,
        )


# ── providers ─────────────────────────────────────────────────────────────


class GeminiClient(_RetryingClient):
    """Structured output via `response_json_schema`. The default provider."""

    def _client(self) -> Any:
        from google import genai

        return genai.Client(api_key=self._api_key)

    def _call(
        self, *, system: str, user: str, max_tokens: int, schema: dict[str, Any] | None
    ) -> tuple[str, int, int]:
        from google.genai import types

        config: dict[str, Any] = {
            "system_instruction": system,
            "max_output_tokens": max_tokens,
        }
        if schema is not None:
            config["response_mime_type"] = "application/json"
            config["response_json_schema"] = schema

        response = self.sdk().models.generate_content(
            model=self.model,
            contents=user,
            config=types.GenerateContentConfig(**config),
        )
        meta = response.usage_metadata
        # Thinking tokens are billed as output. Leaving them out would
        # under-report the cost of exactly the calls that cost most.
        out = (getattr(meta, "candidates_token_count", 0) or 0) + (
            getattr(meta, "thoughts_token_count", 0) or 0
        )
        return response.text or "", getattr(meta, "prompt_token_count", 0) or 0, out


class AnthropicClient(_RetryingClient):
    """Structured output via a forced tool with `input_schema`. Anthropic returns
    the object already parsed; it is re-encoded to JSON here so all three
    providers hand the retry loop the same thing — one decode, one schema gate."""

    TOOL_NAME = "record_result"

    def _client(self) -> Any:
        import anthropic

        return anthropic.Anthropic(api_key=self._api_key)

    def _call(
        self, *, system: str, user: str, max_tokens: int, schema: dict[str, Any] | None
    ) -> tuple[str, int, int]:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        if schema is not None:
            kwargs["tools"] = [
                {
                    "name": self.TOOL_NAME,
                    "description": "Record the result in the required shape.",
                    "input_schema": schema,
                }
            ]
            kwargs["tool_choice"] = {"type": "tool", "name": self.TOOL_NAME}

        response = self.sdk().messages.create(**kwargs)
        usage = response.usage
        sent = getattr(usage, "input_tokens", 0) or 0
        got = getattr(usage, "output_tokens", 0) or 0

        for block in response.content:
            if schema is not None and getattr(block, "type", "") == "tool_use":
                return json.dumps(block.input), sent, got
            if schema is None and getattr(block, "type", "") == "text":
                return block.text, sent, got
        return "", sent, got


class OpenAIClient(_RetryingClient):
    """Structured output via `response_format` with `strict: true`."""

    SCHEMA_NAME = "result"

    def _client(self) -> Any:
        import openai

        return openai.OpenAI(api_key=self._api_key)

    @classmethod
    def strict_schema(cls, schema: dict[str, Any]) -> dict[str, Any]:
        """The same schema, in the dialect `strict: true` accepts.

        OpenAI's strict mode requires every `properties` key to appear in
        `required`. Our optional properties (`confidence`) would 400 unchanged, so
        optional becomes NULLABLE, not mandatory — "may omit" and "send this or
        null" are the same to a caller using `.get()`, where forcing it required
        would make a model invent a confidence. A copy is returned, so the OpenAI
        dialect doesn't leak into the schema every provider shares.
        """
        if not isinstance(schema, dict):
            return schema

        out: dict[str, Any] = {}
        for key, value in schema.items():
            if isinstance(value, dict):
                out[key] = cls.strict_schema(value)
            elif isinstance(value, list):
                out[key] = [
                    cls.strict_schema(item) if isinstance(item, dict) else item for item in value
                ]
            else:
                out[key] = value

        properties = out.get("properties")
        if isinstance(properties, dict):
            required = [k for k in out.get("required", []) if k in properties]
            optional = [k for k in properties if k not in required]
            for key in optional:
                properties[key] = cls._nullable(properties[key])
            out["required"] = [*required, *optional]
            out.setdefault("additionalProperties", False)
        return out

    @staticmethod
    def _nullable(prop: Any) -> Any:
        """Widen a property so it can be answered with null. `enum` is widened
        too — an enum missing `null` while the type allows it is rejected by the
        same validator we are trying to satisfy."""
        if not isinstance(prop, dict):
            return prop
        kind = prop.get("type")
        if isinstance(kind, str):
            if kind != "null":
                prop["type"] = [kind, "null"]
        elif isinstance(kind, list) and "null" not in kind:
            prop["type"] = [*kind, "null"]
        values = prop.get("enum")
        if isinstance(values, list) and None not in values:
            prop["enum"] = [*values, None]
        return prop

    def _call(
        self, *, system: str, user: str, max_tokens: int, schema: dict[str, Any] | None
    ) -> tuple[str, int, int]:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_completion_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if schema is not None:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": self.SCHEMA_NAME,
                    "schema": self.strict_schema(schema),
                    "strict": True,
                },
            }

        response = self.sdk().chat.completions.create(**kwargs)
        usage = response.usage
        content = response.choices[0].message.content or ""
        if schema is not None:
            content = self._drop_optional_nulls(content, schema)
        return (
            content,
            getattr(usage, "prompt_tokens", 0) or 0,
            getattr(usage, "completion_tokens", 0) or 0,
        )

    @classmethod
    def _drop_optional_nulls(cls, content: str, schema: dict[str, Any]) -> str:
        """Undo `strict_schema`, so the payload matches the schema we published.

        `strict_schema` widens an optional property to accept null on the way
        out; this turns that null back into an absent key on the way in. Without
        the return leg the two halves disagree and the shared schema gate — which
        checks against the ORIGINAL schema, as it should — rejects a reply that
        is perfectly well formed: observed as `at evidence_quote: None is not of
        type 'string'` on an adjudication the model answered correctly by
        declining to quote anything.

        Unparseable content is passed through untouched. Repairing JSON is the
        retry path's job, and doing it here would hide a malformed reply behind
        a second-guess.
        """
        try:
            payload = json.loads(content)
        except (TypeError, ValueError):
            return content
        return json.dumps(cls._prune(payload, schema))

    @classmethod
    def _prune(cls, node: Any, schema: Any) -> Any:
        if not isinstance(schema, dict):
            return node
        if isinstance(node, list):
            return [cls._prune(item, schema.get("items")) for item in node]
        if not isinstance(node, dict):
            return node

        properties = schema.get("properties")
        if not isinstance(properties, dict):
            return node
        required = set(schema.get("required", []))
        return {
            key: cls._prune(value, properties.get(key))
            for key, value in node.items()
            if not (value is None and key not in required)
        }


PROVIDERS: dict[str, type[_RetryingClient]] = {
    "gemini": GeminiClient,
    "anthropic": AnthropicClient,
    "openai": OpenAIClient,
}


def build_client(
    *, provider: str, api_key: str, model: str, max_retries: int = 3, **kwargs: Any
) -> _RetryingClient:
    """Maps a provider name to a class. Callers pass a name from configuration,
    so an unknown one is a configuration error naming the valid names, not an
    AttributeError several frames away."""
    try:
        cls = PROVIDERS[provider]
    except KeyError:
        raise LLMError(
            f"unknown LLM provider {provider!r} — expected one of {sorted(PROVIDERS)}"
        ) from None
    return cls(api_key=api_key, model=model, max_retries=max_retries, **kwargs)


# ── the test double ───────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class RecordedCall:
    """What a caller asked for. Assertions are made against these."""

    system: str
    user: str
    max_tokens: int
    schema: dict[str, Any] | None = None


class FakeLLM:
    """Canned structured output, and a record of what it was asked.

    In the portable file, not a `conftest.py`: an extension copying this zone must
    test its own LLM path standalone, without our fixtures. The recorded calls
    make the injection invariants testable without a model — that the extractor
    gets no tools, and that instructions are ours, not concatenated from document
    text.

        fake = FakeLLM(responses=[{"facts": [...]}])
        fake.calls[0].schema      # did the taxonomy actually constrain it?
        fake.calls[0].user        # did document text enter an instruction?
    """

    def __init__(
        self,
        *,
        responses: list[Any] | None = None,
        text_responses: list[str] | None = None,
        model: str = "fake-1",
        enforce_schema: bool = True,
    ) -> None:
        self._responses = list(responses or [])
        self._text = list(text_responses or [])
        self.model = model
        self.enforce_schema = enforce_schema
        """On by default: a fake returning output its caller's schema rejects
        would let a test pass against a shape production refuses."""
        self.calls: list[RecordedCall] = []

    def complete(self, *, system: str, user: str, max_tokens: int) -> tuple[str, Usage]:
        self.calls.append(RecordedCall(system=system, user=user, max_tokens=max_tokens))
        if not self._text:
            raise LLMError("FakeLLM: complete() called with no text_responses left")
        return self._text.pop(0), Usage(model=self.model, input_tokens=0, output_tokens=0)

    def structured(
        self, *, system: str, user: str, schema: dict[str, Any], max_tokens: int
    ) -> tuple[dict[str, Any], Usage]:
        self.calls.append(
            RecordedCall(system=system, user=user, max_tokens=max_tokens, schema=schema)
        )
        if not self._responses:
            raise LLMError("FakeLLM: structured() called with no responses left")

        payload = self._responses.pop(0)
        if isinstance(payload, Exception):
            raise payload
        if self.enforce_schema:
            problem = schema_error(payload, schema)
            if problem is not None:
                raise LLMSchemaViolation(f"FakeLLM canned response does not fit — {problem}")
        return payload, Usage(model=self.model, input_tokens=0, output_tokens=0)

    @property
    def repairs(self) -> list[RecordedCall]:
        """Calls that carried a repair instruction — one per schema retry."""
        return [c for c in self.calls if REPAIR_PREFIX in c.system]


__all__ = [
    "PROVIDERS",
    "REPAIR_PREFIX",
    "AnthropicClient",
    "FakeLLM",
    "GeminiClient",
    "LLMClient",
    "LLMError",
    "LLMQuotaExhausted",
    "LLMSchemaViolation",
    "LLMTransportError",
    "OpenAIClient",
    "RecordedCall",
    "Usage",
    "build_client",
    "check_schema",
    "repair_instruction",
    "retry_delay",
    "schema_error",
]
