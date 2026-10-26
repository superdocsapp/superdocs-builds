import pytest

from core.llm_provider import (
    AnthropicFoundryProvider,
    AzureLLMProvider,
    HashingEmbedder,
    MockLLMProvider,
    _extract_json_object,
    create_llm_provider,
)


class TestExtractJsonObject:
    """Reasoning models wrap JSON in prose or fences; the extractor has to
    survive that or every Finder call degrades to UNKNOWN."""

    def test_plain_object(self):
        assert _extract_json_object('{"a": 1}') == '{"a": 1}'

    def test_strips_code_fence(self):
        assert _extract_json_object('```json\n{"a": 1}\n```') == '{"a": 1}'

    def test_strips_surrounding_prose(self):
        assert _extract_json_object('Here you go:\n{"a": 1}\nHope that helps.') == '{"a": 1}'

    def test_keeps_nested_braces(self):
        raw = '{"a": {"b": 2}}'
        assert _extract_json_object(f"noise {raw} noise") == raw


class TestHashingEmbedder:
    @pytest.mark.asyncio
    async def test_dimension_matches_pgvector_column(self):
        vec = await HashingEmbedder().embed("npm install")
        assert len(vec) == 1536

    @pytest.mark.asyncio
    async def test_is_deterministic(self):
        e = HashingEmbedder()
        assert await e.embed("same text") == await e.embed("same text")

    @pytest.mark.asyncio
    async def test_differs_by_content(self):
        e = HashingEmbedder()
        assert await e.embed("npm install") != await e.embed("pnpm install")

    @pytest.mark.asyncio
    async def test_unit_normalised(self):
        vec = await HashingEmbedder().embed("some words here")
        assert abs(sum(v * v for v in vec) ** 0.5 - 1.0) < 1e-9

    @pytest.mark.asyncio
    async def test_empty_text_is_zero_vector(self):
        vec = await HashingEmbedder().embed("")
        assert len(vec) == 1536 and not any(vec)


class TestCreateLlmProvider:
    """Provider selection is config-driven; pin the precedence so a missing
    key silently downgrades rather than crashing, and so Anthropic wins when
    it is configured."""

    def _clear(self, monkeypatch):
        for name in (
            "ANTHROPIC_ENDPOINT", "ANTHROPIC_API_KEY", "ANTHROPIC_DEPLOYMENT",
            "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_KEY",
        ):
            monkeypatch.setattr(f"core.config.{name}", "", raising=False)

    def test_falls_back_to_mock_without_credentials(self, monkeypatch):
        self._clear(monkeypatch)
        assert isinstance(create_llm_provider(), MockLLMProvider)

    def test_prefers_anthropic(self, monkeypatch):
        self._clear(monkeypatch)
        monkeypatch.setattr("core.config.ANTHROPIC_ENDPOINT", "https://x/anthropic")
        monkeypatch.setattr("core.config.ANTHROPIC_API_KEY", "k")
        monkeypatch.setattr("core.config.ANTHROPIC_DEPLOYMENT", "claude-opus-5")
        assert isinstance(create_llm_provider(), AnthropicFoundryProvider)

    def test_uses_azure_when_only_azure_configured(self, monkeypatch):
        from core.llm_provider import FallbackEmbedder

        self._clear(monkeypatch)
        monkeypatch.setattr("core.config.AZURE_OPENAI_ENDPOINT", "https://x")
        monkeypatch.setattr("core.config.AZURE_OPENAI_KEY", "k")
        provider = create_llm_provider()
        # Wrapped so a missing embeddings deployment degrades instead of
        # aborting the run; completions still go to Azure.
        assert isinstance(provider, FallbackEmbedder)
        assert isinstance(provider.primary, AzureLLMProvider)

    def test_anthropic_uses_hashing_embedder_without_azure(self, monkeypatch):
        self._clear(monkeypatch)
        monkeypatch.setattr("core.config.ANTHROPIC_ENDPOINT", "https://x/anthropic")
        monkeypatch.setattr("core.config.ANTHROPIC_API_KEY", "k")
        monkeypatch.setattr("core.config.ANTHROPIC_DEPLOYMENT", "claude-opus-5")
        provider = create_llm_provider()
        assert isinstance(provider._embedder, HashingEmbedder)

    def test_anthropic_delegates_embeddings_to_azure_when_available(self, monkeypatch):
        from core.llm_provider import FallbackEmbedder

        self._clear(monkeypatch)
        monkeypatch.setattr("core.config.ANTHROPIC_ENDPOINT", "https://x/anthropic")
        monkeypatch.setattr("core.config.ANTHROPIC_API_KEY", "k")
        monkeypatch.setattr("core.config.ANTHROPIC_DEPLOYMENT", "claude-opus-5")
        monkeypatch.setattr("core.config.AZURE_OPENAI_ENDPOINT", "https://y")
        monkeypatch.setattr("core.config.AZURE_OPENAI_KEY", "k2")
        provider = create_llm_provider()
        assert isinstance(provider._embedder, FallbackEmbedder)
        assert isinstance(provider._embedder.primary, AzureLLMProvider)


class TestAnthropicRequestShape:
    def test_never_sends_temperature(self):
        """claude-opus-5 rejects `temperature` outright ('deprecated for this
        model'), which surfaced as a 400 on every call."""
        import inspect

        source = inspect.getsource(AnthropicFoundryProvider.complete)
        assert '"temperature"' not in source


class TestAzureEndpointShapes:
    """A /openai/v1 base with the classic path appended yields
    '/openai/v1/openai/deployments/...' and 404s — which aborted whole runs."""

    def test_v1_suffix_detected(self):
        from core.llm_provider import split_azure_endpoint

        root, style = split_azure_endpoint("https://r.openai.azure.com/openai/v1/")
        assert root == "https://r.openai.azure.com" and style == "v1"

    def test_openai_suffix_detected(self):
        from core.llm_provider import split_azure_endpoint

        root, style = split_azure_endpoint("https://r.openai.azure.com/openai")
        assert root == "https://r.openai.azure.com" and style == "classic"

    def test_bare_resource_is_classic(self):
        from core.llm_provider import split_azure_endpoint

        root, style = split_azure_endpoint("https://r.openai.azure.com")
        assert root == "https://r.openai.azure.com" and style == "classic"

    def test_v1_url_has_no_duplicated_openai_segment(self):
        from core.llm_provider import AzureLLMProvider

        p = AzureLLMProvider("https://r.openai.azure.com/openai/v1", "k", "gpt", "emb")
        url = p._url("emb", "embeddings")
        assert url == "https://r.openai.azure.com/openai/v1/embeddings"
        assert url.count("/openai") == 1

    def test_classic_url_includes_deployment_and_api_version(self):
        from core.llm_provider import AzureLLMProvider

        p = AzureLLMProvider("https://r.openai.azure.com", "k", "gpt", "emb")
        url = p._url("emb", "embeddings")
        assert "/openai/deployments/emb/embeddings" in url
        assert "api-version=" in url


class TestFallbackEmbedder:
    """A misconfigured embeddings deployment must degrade, not kill the run."""

    @pytest.mark.asyncio
    async def test_falls_back_when_primary_raises(self):
        from core.llm_provider import FallbackEmbedder

        class Broken(MockLLMProvider):
            async def embed(self, text):
                raise RuntimeError("404 DeploymentNotFound")

        fb = FallbackEmbedder(Broken())
        vec = await fb.embed("npm install")
        assert len(vec) == 1536
        assert fb.degraded is True
        assert "404" in fb.reason

    @pytest.mark.asyncio
    async def test_uses_primary_while_healthy(self):
        from core.llm_provider import FallbackEmbedder

        class Fine(MockLLMProvider):
            async def embed(self, text):
                return [0.5] * 1536

        fb = FallbackEmbedder(Fine())
        assert (await fb.embed("x"))[0] == 0.5
        assert fb.degraded is False

    @pytest.mark.asyncio
    async def test_does_not_retry_primary_after_failing(self):
        from core.llm_provider import FallbackEmbedder

        calls = {"n": 0}

        class Broken(MockLLMProvider):
            async def embed(self, text):
                calls["n"] += 1
                raise RuntimeError("down")

        fb = FallbackEmbedder(Broken())
        await fb.embed("a")
        await fb.embed("b")
        # One failed attempt is enough; hammering a dead endpoint per chunk
        # would make every run crawl.
        assert calls["n"] == 1


class TestEmbeddingDeploymentDiscovery:
    """A hardcoded deployment name that doesn't exist failed every run. The
    provider now resolves against what is actually deployed."""

    def _provider(self, deployments, configured="text-embedding-3-small"):
        from core.llm_provider import AzureLLMProvider

        p = AzureLLMProvider(
            "https://r.openai.azure.com/openai/v1", "k", "gpt", configured
        )

        async def fake_list():
            return deployments

        p.list_deployments = fake_list
        return p

    @pytest.mark.asyncio
    async def test_prefers_configured_name_when_deployed(self):
        p = self._provider([{"id": "text-embedding-3-small", "model": "x"}])
        assert await p.resolve_embedding_deployment() == "text-embedding-3-small"

    @pytest.mark.asyncio
    async def test_discovers_alternative_embedding_deployment(self):
        p = self._provider(
            [{"id": "gpt-4o", "model": "gpt-4o"},
             {"id": "my-embeddings", "model": "text-embedding-3-large"}]
        )
        assert await p.resolve_embedding_deployment() == "my-embeddings"

    @pytest.mark.asyncio
    async def test_raises_actionable_error_when_none_deployed(self):
        from core.llm_provider import NoEmbeddingDeployment

        p = self._provider(
            [{"id": "claude-opus-5", "model": "claude-opus-5"},
             {"id": "gpt-5.6-sol", "model": "gpt-5.6-sol"}]
        )
        with pytest.raises(NoEmbeddingDeployment) as exc:
            await p.resolve_embedding_deployment()
        msg = str(exc.value)
        # Must name what IS available, so the fix is obvious.
        assert "claude-opus-5" in msg
        assert "text-embedding-3-small" in msg

    @pytest.mark.asyncio
    async def test_resolution_is_cached(self):
        calls = {"n": 0}
        from core.llm_provider import AzureLLMProvider

        p = AzureLLMProvider("https://r.openai.azure.com/openai/v1", "k", "g", "emb")

        async def fake_list():
            calls["n"] += 1
            return [{"id": "emb", "model": "text-embedding-3-small"}]

        p.list_deployments = fake_list
        await p.resolve_embedding_deployment()
        await p.resolve_embedding_deployment()
        assert calls["n"] == 1

    @pytest.mark.asyncio
    async def test_falls_back_to_configured_name_if_listing_fails(self):
        from core.llm_provider import AzureLLMProvider

        p = AzureLLMProvider("https://r.openai.azure.com/openai/v1", "k", "g", "emb")

        async def boom():
            raise RuntimeError("no permission to list")

        p.list_deployments = boom
        # Better to attempt the call and surface the real upstream error than
        # to refuse to try.
        assert await p.resolve_embedding_deployment() == "emb"

    @pytest.mark.asyncio
    async def test_no_embedding_deployment_is_reported_as_configuration(self):
        from core.llm_provider import FallbackEmbedder, NoEmbeddingDeployment

        class Missing(MockLLMProvider):
            async def embed(self, text):
                raise NoEmbeddingDeployment("Deploy an embedding model ...")

        fb = FallbackEmbedder(Missing())
        await fb.embed("x")
        assert fb.degraded
        # The guidance is preserved verbatim, not flattened to a class name.
        assert "Deploy an embedding model" in fb.reason


class TestResolutionErrorIsSticky:
    """Resolution is cached; the cached path must re-raise the detailed
    reason, not degrade to a terse one after the first call."""

    @pytest.mark.asyncio
    async def test_detailed_reason_survives_repeat_calls(self):
        from core.llm_provider import AzureLLMProvider, NoEmbeddingDeployment

        p = AzureLLMProvider("https://r.openai.azure.com/openai/v1", "k", "g", "missing")

        async def fake_list():
            return [{"id": "claude-opus-5", "model": "claude-opus-5"}]

        p.list_deployments = fake_list

        with pytest.raises(NoEmbeddingDeployment) as first:
            await p.resolve_embedding_deployment()
        with pytest.raises(NoEmbeddingDeployment) as second:
            await p.resolve_embedding_deployment()

        assert "claude-opus-5" in str(second.value)
        assert str(first.value) == str(second.value)
