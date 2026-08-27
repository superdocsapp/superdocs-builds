from __future__ import annotations
from openai import OpenAI

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIM = 1536

CHAT_MODEL = "gpt-4.1-mini"

# Pricing as of Aug 2026 — verify against https://openai.com/api/pricing
# before trusting these for anything beyond rough cost tracking.
EMBEDDING_COST_PER_1M = 0.02
CHAT_INPUT_COST_PER_1M = 0.40
CHAT_OUTPUT_COST_PER_1M = 1.60


class OpenAIClient:
    """Real embed_fn/llm_fn implementations matching every fake used
    throughout the pipeline's tests. Tracks cumulative tokens/cost on
    the instance so Phase 8's run logging can read it after each call,
    without changing any function signature the drafting/verifier/
    revision code already depends on."""

    def __init__(self, api_key: str):
        self.client = OpenAI(api_key=api_key)
        self.total_tokens = 0
        self.total_cost_usd = 0.0

    def embed_fn(self, texts: list[str]) -> list[list[float]]:
        response = self.client.embeddings.create(model=EMBEDDING_MODEL, input=texts)
        tokens = response.usage.total_tokens
        self.total_tokens += tokens
        self.total_cost_usd += (tokens / 1_000_000) * EMBEDDING_COST_PER_1M
        return [item.embedding for item in response.data]

    def llm_fn(self, system_prompt: str, user_prompt: str) -> str:
        """Matches the (system_prompt, user_prompt) -> raw_json_str
        signature every fake_llm_fn in the tests has used."""
        response = self.client.chat.completions.create(
            model=CHAT_MODEL,
            response_format={"type": "json_object"},  # forces valid JSON — every
                                                        # call site does json.loads()
                                                        # with no retry logic
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        usage = response.usage
        self.total_tokens += usage.total_tokens
        self.total_cost_usd += (
            (usage.prompt_tokens / 1_000_000) * CHAT_INPUT_COST_PER_1M
            + (usage.completion_tokens / 1_000_000) * CHAT_OUTPUT_COST_PER_1M
        )
        return response.choices[0].message.content