from abc import ABC, abstractmethod
from typing import Any, Optional
from pydantic import BaseModel, Field


class LLMMessage(BaseModel):
    role: str
    content: str


class LLMResponse(BaseModel):
    content: str
    model: str
    tokens_used: int
    metadata: dict[str, Any] = Field(default_factory=dict)


class LLMProvider(ABC):
    @abstractmethod
    async def generate(
        self,
        messages: list[LLMMessage],
        model: str,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        response_format: Optional[type[BaseModel]] = None
    ) -> LLMResponse:
        """Generate completion from messages"""
        pass

    @abstractmethod
    async def generate_structured(
        self,
        messages: list[LLMMessage],
        model: str,
        response_schema: type[BaseModel],
        temperature: float = 0.7
    ) -> BaseModel:
        """Generate structured output matching Pydantic schema"""
        pass
