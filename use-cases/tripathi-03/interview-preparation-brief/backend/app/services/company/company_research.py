"""Grounded company research service.

Accepts a company name (and optional official URL), collects evidence from
public pages when available, and returns structured JSON.

Anti-hallucination rules:
- Extract ONLY from fetched evidence text.
- If a field is not supported by evidence, return exactly "Unknown".
- Never invent industry, products, mission, tech stack, interview process,
  culture, news, blogs, or hiring trends.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from app.agents.llm import invoke_structured
from app.core.config import get_settings
from app.core.logging import get_logger
from app.schemas.company import (
    UNKNOWN,
    CompanyExtractionOutput,
    CompanyResearchRequest,
    CompanyResearchResponse,
    _as_unknown_list,
    _as_unknown_str,
)

logger = get_logger(__name__)

SYSTEM_PROMPT = f"""You are a strict evidence extraction engine for company research.

Rules:
1. Use ONLY the provided evidence text.
2. Do NOT use prior knowledge about the company.
3. Do NOT invent or infer facts that are not explicitly supported.
4. If a field is not clearly supported by the evidence, set it to exactly "{UNKNOWN}".
5. For list fields with no supported items, return an empty list.
6. Prefer short factual phrases over marketing fluff.
7. Never fabricate news headlines, blog titles, tech stack items, or interview steps.
"""

# Common public pages that often contain interview-relevant facts.
_PATH_CANDIDATES = (
    "",
    "/about",
    "/about-us",
    "/company",
    "/products",
    "/platform",
    "/solutions",
    "/careers",
    "/jobs",
    "/blog",
    "/engineering",
    "/engineering/blog",
    "/tech",
    "/news",
    "/press",
)


class CompanyResearchService:
    def __init__(self) -> None:
        self.settings = get_settings()

    async def research(
        self,
        company_name: str,
        company_url: str | None = None,
    ) -> CompanyResearchResponse:
        request = CompanyResearchRequest(
            company_name=company_name,
            company_url=company_url,
        )
        return await self.research_structured(request)

    async def research_structured(
        self,
        request: CompanyResearchRequest,
    ) -> CompanyResearchResponse:
        """Collect structured company research JSON."""
        evidence_docs: list[tuple[str, str]] = []
        sources: list[str] = []

        if request.company_url:
            fetched = await self._collect_site_evidence(request.company_url)
            for url, text in fetched:
                if text.strip():
                    evidence_docs.append((url, text))
                    sources.append(url)

        if not evidence_docs:
            logger.info(
                "No fetchable evidence for company=%s; returning Unknown profile",
                request.company_name,
            )
            return self._unknown_response(request.company_name, sources=[])

        evidence_block = self._format_evidence(evidence_docs)
        extraction = await invoke_structured(
            schema=CompanyExtractionOutput,
            system=SYSTEM_PROMPT,
            user=(
                f"Company name: {request.company_name}\n\n"
                "Extract the following fields from evidence only:\n"
                "- industry\n"
                "- products\n"
                "- mission\n"
                "- tech_stack\n"
                "- interview_process\n"
                "- engineering_culture\n"
                "- latest_news\n"
                "- tech_blogs\n"
                "- hiring_trends\n\n"
                f"If unsupported, use {UNKNOWN} (or empty list for list fields).\n\n"
                f"EVIDENCE:\n{evidence_block}"
            ),
        )

        response = self._normalize_response(
            company_name=request.company_name,
            extraction=extraction,
            sources=sources,
        )
        logger.info(
            "Company research complete name=%s sources=%s known_fields=%s",
            request.company_name,
            len(sources),
            self._known_field_count(response),
        )
        return response

    def _normalize_response(
        self,
        *,
        company_name: str,
        extraction: CompanyExtractionOutput,
        sources: list[str],
    ) -> CompanyResearchResponse:
        response = CompanyResearchResponse(
            company_name=company_name,
            industry=_as_unknown_str(extraction.industry),
            products=_as_unknown_list(extraction.products),
            mission=_as_unknown_str(extraction.mission),
            tech_stack=_as_unknown_list(extraction.tech_stack),
            interview_process=_as_unknown_str(extraction.interview_process),
            engineering_culture=_as_unknown_str(extraction.engineering_culture),
            latest_news=_as_unknown_list(extraction.latest_news),
            tech_blogs=_as_unknown_list(extraction.tech_blogs),
            hiring_trends=_as_unknown_str(extraction.hiring_trends),
            sources=sources,
            overview=UNKNOWN,
        )
        response.overview = response.to_brief_overview()
        return response

    def _unknown_response(
        self,
        company_name: str,
        sources: list[str],
    ) -> CompanyResearchResponse:
        response = CompanyResearchResponse(
            company_name=company_name,
            industry=UNKNOWN,
            products=[UNKNOWN],
            mission=UNKNOWN,
            tech_stack=[UNKNOWN],
            interview_process=UNKNOWN,
            engineering_culture=UNKNOWN,
            latest_news=[UNKNOWN],
            tech_blogs=[UNKNOWN],
            hiring_trends=UNKNOWN,
            sources=sources,
            overview=UNKNOWN,
        )
        response.overview = response.to_brief_overview()
        return response

    async def _collect_site_evidence(self, root_url: str) -> list[tuple[str, str]]:
        parsed = urlparse(root_url)
        if not parsed.scheme or not parsed.netloc:
            return []

        base = f"{parsed.scheme}://{parsed.netloc}"
        results: list[tuple[str, str]] = []
        seen: set[str] = set()

        async with httpx.AsyncClient(
            timeout=self.settings.http_timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": "InterviewPrepBrief/1.0 (+company-research)"},
        ) as client:
            # Always try the provided URL first.
            primary = await self._fetch_url_text(client, root_url)
            if primary:
                results.append((root_url, primary))
                seen.add(self._normalize_url_key(root_url))

            for path in _PATH_CANDIDATES:
                url = urljoin(base + "/", path.lstrip("/")) if path else base + "/"
                key = self._normalize_url_key(url)
                if key in seen:
                    continue
                text = await self._fetch_url_text(client, url)
                if text:
                    results.append((url, text))
                    seen.add(key)
                # Cap pages to keep latency predictable.
                if len(results) >= 6:
                    break

        return results

    async def _fetch_url_text(self, client: httpx.AsyncClient, url: str) -> str:
        try:
            response = await client.get(url)
            if response.status_code >= 400:
                return ""
            content_type = response.headers.get("content-type", "")
            if "text/html" not in content_type and "text/plain" not in content_type:
                return ""
            return self._html_to_text(response.text)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Fetch failed url=%s error=%s", url, exc)
            return ""

    def _html_to_text(self, html: str) -> str:
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript", "svg", "iframe"]):
            tag.decompose()
        text = " ".join(soup.get_text(separator=" ").split())
        text = re.sub(r"\s+", " ", text).strip()
        return text[:10000]

    def _format_evidence(self, docs: list[tuple[str, str]]) -> str:
        parts: list[str] = []
        remaining = 18000
        for url, text in docs:
            snippet = text[: min(len(text), max(1000, remaining // max(len(docs), 1)))]
            block = f"SOURCE: {url}\n{snippet}"
            if len(block) > remaining:
                block = block[:remaining]
            parts.append(block)
            remaining -= len(block)
            if remaining <= 0:
                break
        return "\n\n----\n\n".join(parts)

    @staticmethod
    def _normalize_url_key(url: str) -> str:
        parsed = urlparse(url)
        path = parsed.path.rstrip("/") or "/"
        return f"{parsed.netloc.lower()}{path.lower()}"

    @staticmethod
    def _known_field_count(response: CompanyResearchResponse) -> int:
        count = 0
        if response.industry != UNKNOWN:
            count += 1
        if response.mission != UNKNOWN:
            count += 1
        if response.interview_process != UNKNOWN:
            count += 1
        if response.engineering_culture != UNKNOWN:
            count += 1
        if response.hiring_trends != UNKNOWN:
            count += 1
        if response.products != [UNKNOWN]:
            count += 1
        if response.tech_stack != [UNKNOWN]:
            count += 1
        if response.latest_news != [UNKNOWN]:
            count += 1
        if response.tech_blogs != [UNKNOWN]:
            count += 1
        return count


# Backward-compatible alias used by older imports/tests.
CompanyProfile = CompanyResearchResponse
