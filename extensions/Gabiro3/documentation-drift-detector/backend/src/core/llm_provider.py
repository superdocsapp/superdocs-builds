import hashlib
import json
import re
from abc import ABC, abstractmethod
from typing import Type, TypeVar, Optional
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLMProvider(ABC):
    @abstractmethod
    async def complete(self, prompt: str, schema: Type[T], system: str = "") -> T:
        ...

    @abstractmethod
    async def embed(self, text: str) -> list[float]:
        ...


class MockLLMProvider(LLMProvider):
    def __init__(self, fixture_path: str = ""):
        self._store: dict[str, dict] = {}
        self._fixture_path = fixture_path
        if fixture_path:
            import os

            if os.path.exists(fixture_path):
                with open(fixture_path, "r") as f:
                    self._store = {item["hash"]: item for item in json.load(f)}

    def _make_hash(self, prompt: str, schema_name: str) -> str:
        return hashlib.sha256((prompt + schema_name).encode()).hexdigest()[:16]

    async def complete(self, prompt: str, schema: Type[T], system: str = "") -> T:
        key = self._make_hash(prompt, schema.__name__)
        if key in self._store:
            return schema.model_validate(self._store[key]["output"])
        return schema.model_validate({})

    async def embed(self, text: str) -> list[float]:
        key = hashlib.sha256(text.encode()).hexdigest()[:16]
        if key in self._store:
            return self._store[key]["embedding"]
        return [0.0] * 1536

    def record(self, prompt: str, schema_name: str, output: dict):
        key = self._make_hash(prompt, schema_name)
        self._store[key] = {"prompt": prompt, "output": output, "schema": schema_name}

    def record_embedding(self, text: str, embedding: list[float]):
        key = hashlib.sha256(text.encode()).hexdigest()[:16]
        self._store[key] = {"text": text, "embedding": embedding}

    def save(self, path: str):
        with open(path, "w") as f:
            json.dump(list(self._store.values()), f, indent=2)


def split_azure_endpoint(endpoint: str) -> tuple[str, str]:
    """Return (resource_root, style) for an Azure OpenAI endpoint.

    Azure accepts two URL shapes and the caller may paste either:
      https://{res}.openai.azure.com              -> classic
      https://{res}.openai.azure.com/openai/v1    -> OpenAI-compatible

    Appending the classic path to a /openai/v1 base yields
    '/openai/v1/openai/deployments/...' which 404s, so the suffix has to be
    detected rather than assumed.
    """
    raw = (endpoint or "").rstrip("/")
    if raw.endswith("/openai/v1"):
        return raw[: -len("/openai/v1")], "v1"
    if raw.endswith("/openai"):
        return raw[: -len("/openai")], "classic"
    return raw, "classic"


class NoEmbeddingDeployment(RuntimeError):
    """The Azure resource exposes no embedding deployment to call."""


class AzureLLMProvider(LLMProvider):
    API_VERSION = "2024-10-21"
    DEPLOYMENTS_API_VERSION = "2023-03-15-preview"

    def __init__(
        self,
        endpoint: str,
        api_key: str,
        deployment: str,
        embedding_deployment: str,
    ):
        self.root, self.style = split_azure_endpoint(endpoint)
        self.api_key = api_key
        self.deployment = deployment
        self.embedding_deployment = embedding_deployment
        self._resolved_embedding: Optional[str] = None
        self._resolution_done = False
        self._resolution_error: Optional[str] = None

    async def list_deployments(self) -> list[dict]:
        """What is actually deployed on this resource (not merely available
        in the region — the /models list includes undeployed models, which is
        what makes a wrong name look plausible)."""
        import httpx

        url = f"{self.root}/openai/deployments?api-version={self.DEPLOYMENTS_API_VERSION}"
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, headers={"api-key": self.api_key})
            resp.raise_for_status()
            return resp.json().get("data", [])

    @staticmethod
    def _looks_like_embedding(dep: dict) -> bool:
        blob = f"{dep.get('id', '')} {dep.get('model', '')}".lower()
        return "embed" in blob

    async def resolve_embedding_deployment(self) -> Optional[str]:
        """Find a usable embedding deployment, preferring the configured one.

        Resolved once and cached. Falling back to discovery means that
        deploying an embedding model later just starts working, and that a
        merely-misspelled name self-corrects instead of failing every run.
        """
        if self._resolution_done:
            # Re-raise the original, detailed reason rather than degrading to a
            # terse one on every subsequent call.
            if self._resolution_error:
                raise NoEmbeddingDeployment(self._resolution_error)
            return self._resolved_embedding
        self._resolution_done = True

        try:
            deployments = await self.list_deployments()
        except Exception:
            # Can't enumerate: trust the configured name and let the call fail
            # with the real upstream error.
            self._resolved_embedding = self.embedding_deployment or None
            return self._resolved_embedding

        names = {d.get("id") for d in deployments if d.get("id")}
        if self.embedding_deployment in names:
            self._resolved_embedding = self.embedding_deployment
            return self._resolved_embedding

        discovered = next(
            (d["id"] for d in deployments if self._looks_like_embedding(d)), None
        )
        if discovered:
            self._resolved_embedding = discovered
            return discovered

        self._resolved_embedding = None
        self._resolution_error = (
            f"No embedding deployment on this Azure resource. "
            f"Configured AZURE_EMBEDDING_DEPLOYMENT='{self.embedding_deployment}' "
            f"is not deployed; available deployments: {sorted(names) or 'none'}. "
            f"Deploy an embedding model (e.g. text-embedding-3-small) in Azure AI "
            f"Foundry, or unset AZURE_OPENAI_ENDPOINT/AZURE_OPENAI_KEY to use the "
            f"local lexical fallback deliberately."
        )
        raise NoEmbeddingDeployment(self._resolution_error)

    @property
    def endpoint(self) -> str:
        return self.root

    def _url(self, deployment: str, path: str) -> str:
        if self.style == "v1":
            return f"{self.root}/openai/v1/{path}"
        return (
            f"{self.root}/openai/deployments/{deployment}/{path}"
            f"?api-version={self.API_VERSION}"
        )

    async def complete(self, prompt: str, schema: Type[T], system: str = "") -> T:
        import httpx

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        body = {
            "messages": messages,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema.__name__,
                    "schema": schema.model_json_schema(),
                    "strict": True,
                },
            },
            "max_tokens": 4096,
        }
        if self.style == "v1":
            body["model"] = self.deployment

        headers = {"api-key": self.api_key, "Content-Type": "application/json"}
        url = self._url(self.deployment, "chat/completions")
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(url, headers=headers, json=body)

            # Newer deployments reject `max_tokens` and require
            # `max_completion_tokens`. Retry once rather than failing the run.
            if resp.status_code == 400 and "max_completion_tokens" in resp.text:
                body["max_completion_tokens"] = body.pop("max_tokens")
                resp = await client.post(url, headers=headers, json=body)

            resp.raise_for_status()
            data = resp.json()
        content = data["choices"][0]["message"]["content"]
        return schema.model_validate_json(_extract_json_object(content))

    async def embed(self, text: str) -> list[float]:
        import httpx

        deployment = await self.resolve_embedding_deployment()
        if not deployment:
            raise NoEmbeddingDeployment("No embedding deployment available")

        body: dict = {"input": text}
        if self.style == "v1":
            body["model"] = deployment

        headers = {"api-key": self.api_key, "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                self._url(deployment, "embeddings"), headers=headers, json=body
            )
            resp.raise_for_status()
            data = resp.json()
        return data["data"][0]["embedding"]

class AnthropicFoundryProvider(LLMProvider):
    """Claude via Microsoft AI Foundry's Anthropic-compatible endpoint.

    Foundry exposes /v1/messages but no embeddings route, so `embed` is
    delegated to a separate provider (Azure OpenAI when configured,
    otherwise the deterministic local fallback below).
    """

    def __init__(
        self,
        endpoint: str,
        api_key: str,
        deployment: str,
        embedder: Optional["LLMProvider"] = None,
    ):
        self.endpoint = endpoint.rstrip("/")
        self.api_key = api_key
        self.deployment = deployment
        self._embedder = embedder or HashingEmbedder()

    async def complete(self, prompt: str, schema: Type[T], system: str = "") -> T:
        import httpx

        schema_json = json.dumps(schema.model_json_schema(), indent=2)
        instruction = (
            f"{prompt}\n\nRespond with a single JSON object matching this schema. "
            f"Output only the JSON, with no prose or code fences.\n\n"
            f"Schema:\n{schema_json}"
        )
        # No `temperature`: reasoning models such as claude-opus-5 reject it
        # ("temperature is deprecated for this model"). Determinism is a
        # property of the scaffolding around the model, not of the sampler.
        body = {
            "model": self.deployment,
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": instruction}],
        }
        if system:
            body["system"] = system

        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{self.endpoint}/v1/messages", headers=headers, json=body
            )
            resp.raise_for_status()
            data = resp.json()

        text = "".join(
            block.get("text", "")
            for block in data.get("content", [])
            if block.get("type") == "text"
        )
        return schema.model_validate_json(_extract_json_object(text))

    async def embed(self, text: str) -> list[float]:
        return await self._embedder.embed(text)


class HashingEmbedder(LLMProvider):
    """Deterministic offline embedding — a hashed bag of words.

    This is a genuine fallback, not a semantic model: it captures lexical
    overlap only, so retrieval recall degrades on paraphrases. It exists so
    the pipeline stays runnable when no embeddings endpoint is configured
    (Anthropic Foundry doesn't provide one). Configure Azure OpenAI
    embeddings for real semantic retrieval.
    """

    DIM = 1536

    async def complete(self, prompt: str, schema: Type[T], system: str = "") -> T:
        raise NotImplementedError("HashingEmbedder only provides embeddings")

    async def embed(self, text: str) -> list[float]:
        import math
        import re

        vec = [0.0] * self.DIM
        for token in re.findall(r"[a-z0-9]+", (text or "").lower()):
            h = int(hashlib.sha256(token.encode()).hexdigest()[:8], 16)
            vec[h % self.DIM] += 1.0
        norm = math.sqrt(sum(v * v for v in vec))
        if norm:
            vec = [v / norm for v in vec]
        return vec


class FallbackEmbedder(LLMProvider):
    """Try a real embeddings endpoint, fall back to hashing if it is broken.

    A misconfigured embedding deployment (wrong name, not deployed at all)
    used to 404 and abort the whole run at EMBED. Retrieval also has a
    keyword leg, so degraded embeddings still produce useful candidates —
    losing recall is much better than losing the run. The degradation is
    recorded on `.degraded` / `.reason` so the pipeline can surface it in the
    trace instead of hiding it.
    """

    def __init__(self, primary: LLMProvider, fallback: Optional[LLMProvider] = None):
        self.primary = primary
        self.fallback = fallback or HashingEmbedder()
        self.degraded = False
        self.reason = ""

    async def complete(self, prompt: str, schema: Type[T], system: str = "") -> T:
        return await self.primary.complete(prompt, schema, system)

    async def embed(self, text: str) -> list[float]:
        if not self.degraded:
            try:
                return await self.primary.embed(text)
            except NoEmbeddingDeployment as exc:
                # Configuration, not an outage: report it as such.
                self.degraded = True
                self.reason = str(exc)
            except Exception as exc:
                self.degraded = True
                self.reason = f"{type(exc).__name__}: {str(exc)[:300]}"
        return await self.fallback.embed(text)


def _extract_json_object(text: str) -> str:
    """Pull the outermost JSON object out of a model response."""
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start != -1 and end > start:
        return cleaned[start : end + 1]
    return cleaned


def create_llm_provider() -> LLMProvider:
    """Pick a provider from configuration.

    Anthropic (Foundry) is preferred, then Azure OpenAI, then the mock.
    When Anthropic is used, embeddings come from Azure OpenAI if it is
    configured, otherwise from the deterministic hashing fallback.
    """
    from core.config import (
        ANTHROPIC_API_KEY,
        ANTHROPIC_DEPLOYMENT,
        ANTHROPIC_ENDPOINT,
        AZURE_EMBEDDING_DEPLOYMENT,
        AZURE_OPENAI_DEPLOYMENT,
        AZURE_OPENAI_ENDPOINT,
        AZURE_OPENAI_KEY,
    )

    azure_ready = bool(AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_KEY)
    azure = (
        AzureLLMProvider(
            endpoint=AZURE_OPENAI_ENDPOINT,
            api_key=AZURE_OPENAI_KEY,
            deployment=AZURE_OPENAI_DEPLOYMENT,
            embedding_deployment=AZURE_EMBEDDING_DEPLOYMENT,
        )
        if azure_ready
        else None
    )

    if ANTHROPIC_ENDPOINT and ANTHROPIC_API_KEY and ANTHROPIC_DEPLOYMENT:
        # Azure may be configured but have no embedding deployment; wrap it so
        # a 404 degrades to hashing instead of aborting the run.
        embedder = FallbackEmbedder(azure) if azure else HashingEmbedder()
        return AnthropicFoundryProvider(
            endpoint=ANTHROPIC_ENDPOINT,
            api_key=ANTHROPIC_API_KEY,
            deployment=ANTHROPIC_DEPLOYMENT,
            embedder=embedder,
        )

    if azure:
        return FallbackEmbedder(azure)

    return MockLLMProvider()
