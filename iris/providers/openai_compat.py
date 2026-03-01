"""OpenAI-compatible provider for third-party endpoints (e.g. Together, Groq, vLLM)."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from ..core.types import ModelInfo, ProviderCapabilities
from .openai_provider import OpenAIProvider


class OpenAICompatProvider(OpenAIProvider):
    """Provider that speaks the OpenAI API protocol against a custom base URL."""

    def __init__(
        self,
        api_key: str = "",
        api_base: str = "",
        model: str = "",
        provider_name: str = "openai_compat",
        **kwargs,
    ):
        super().__init__(api_key=api_key, model=model, **kwargs)
        self.api_base = api_base
        self._provider_name = provider_name

    def _get_client(self):
        if self._client is None:
            try:
                import openai
            except ImportError:
                from ..core.errors import ProviderError
                raise ProviderError(
                    "openai package not installed. Run: pip install openai",
                    provider=self._provider_name,
                )
            kwargs: Dict[str, Any] = {}
            if self.api_key:
                kwargs["api_key"] = self.api_key
            if self.api_base:
                kwargs["base_url"] = self.api_base
            self._client = openai.OpenAI(**kwargs)
        return self._client

    @property
    def name(self) -> str:
        return self._provider_name

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            streaming=True, tool_use=True, vision=False,
            max_context_window=128000, max_output_tokens=4096,
        )

    def list_models(self) -> List[ModelInfo]:
        if self.model:
            return [ModelInfo(self.model, self.model, self._provider_name)]
        return []
