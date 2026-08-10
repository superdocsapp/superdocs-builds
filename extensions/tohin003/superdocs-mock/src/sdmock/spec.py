"""The published specification, loaded and made queryable.

This is what "built from the published specification" means in practice. The spec is not
decoration here -- it does real work at runtime:

* It supplies the **route table**. Every path the mock will answer comes from
  `openapi.json`, so the mock cannot accidentally serve a route SuperDocs does not have,
  and a route SuperDocs adds shows up the moment the pin is refreshed.

* It supplies **path templating**, which is what makes the cassettes portable. A cassette
  records `/v1/jobs/9e3569a4-…`; an integrator's client will call `/v1/jobs/<their id>`.
  Both normalise to the spec's own `/v1/jobs/{job_id}`, so a recording made against one
  set of ids replays for any client. Without this the mock would only work for the person
  who recorded it.

Loading is lazy and cheap: json.load of a 228 KB file, no validation library, no model
generation. Startup time is a graded property of this project.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterator

from .paths import spec_dir


def _spec_path() -> Path:
    return spec_dir() / "openapi.json"

# A path parameter matches one segment and never a slash.
_PARAM = re.compile(r"\{([^}]+)\}")


class Spec:
    """The pinned OpenAPI document, with a path matcher built from its own routes."""

    def __init__(self, raw: dict[str, Any]) -> None:
        self.raw = raw
        self.paths: dict[str, Any] = raw.get("paths", {})
        self.schemas: dict[str, Any] = raw.get("components", {}).get("schemas", {})
        self._matchers: list[tuple[re.Pattern[str], str]] = []
        for template in self.paths:
            if "{" in template:
                pattern = "^" + _PARAM.sub(r"[^/]+", re.escape(template)
                                          .replace(r"\{", "{").replace(r"\}", "}")) + "$"
                self._matchers.append((re.compile(pattern), template))
        # Longest first, so a literal-heavy template wins over a greedy one.
        self._matchers.sort(key=lambda item: -len(item[1]))

    # ---------------------------------------------------------------- routing

    def match(self, path: str) -> str | None:
        """Normalise a concrete request path to its spec template.

        `/v1/jobs/9e3569a4-...` -> `/v1/jobs/{job_id}`. Returns None when the spec
        describes no such route, which the app reports as an honest 404 rather than
        inventing a response.
        """
        path = path.rstrip("/") or "/"
        if path in self.paths:
            return path
        with_slash = path + "/"
        if with_slash in self.paths:
            return with_slash
        for pattern, template in self._matchers:
            if pattern.match(path):
                return template
        return None

    def methods(self, template: str) -> set[str]:
        node = self.paths.get(template, {})
        return {m.upper() for m in node if m in
                {"get", "post", "put", "patch", "delete", "head", "options"}}

    def operation(self, method: str, template: str) -> dict[str, Any] | None:
        return self.paths.get(template, {}).get(method.lower())

    def summary(self, method: str, template: str) -> str:
        op = self.operation(method, template) or {}
        return op.get("summary", "")

    # ---------------------------------------------------------------- schemas

    def response_schema(self, method: str, template: str, status: int) -> Any | None:
        """A self-contained JSON Schema for one response, refs and all.

        `components` rides along in the returned document so `$ref`s such as
        `#/components/schemas/JobResponse` resolve against it. That is cheaper and far
        more robust than inlining: an earlier version walked the tree substituting refs
        by hand, missed the ones nested inside `anyOf` lists, and blew up on the first
        deeply structured response it met. JSON Schema 2020-12 permits `$ref` alongside
        sibling keywords, so this composes cleanly.
        """
        op = self.operation(method, template)
        if not op:
            return None
        responses = op.get("responses", {})
        node = responses.get(str(status)) or responses.get("default")
        if not node:
            return None
        media = node.get("content", {}).get("application/json")
        if not media or "schema" not in media:
            return None
        return {**media["schema"], "components": self.raw.get("components", {})}

    def iter_routes(self) -> Iterator[tuple[str, str]]:
        for template in sorted(self.paths):
            for method in sorted(self.methods(template)):
                yield method, template

    @property
    def version(self) -> str:
        return self.raw.get("info", {}).get("version", "unknown")


@lru_cache(maxsize=1)
def load(path: Path | None = None) -> Spec:
    target = path or _spec_path()
    return Spec(json.loads(target.read_text(encoding="utf-8")))
