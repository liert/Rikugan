"""Provider registry: factory for creating provider instances."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Type

from ..core.errors import ProviderError
from .base import LLMProvider
from .anthropic_provider import AnthropicProvider
from .openai_provider import OpenAIProvider
from .openai_compat import OpenAICompatProvider
from .gemini_provider import GeminiProvider
from .ollama_provider import OllamaProvider


_BUILTIN_PROVIDERS: Dict[str, Type[LLMProvider]] = {
    "anthropic": AnthropicProvider,
    "openai": OpenAIProvider,
    "openai_compat": OpenAICompatProvider,
    "gemini": GeminiProvider,
    "ollama": OllamaProvider,
}


class ProviderRegistry:
    """Factory for creating and managing LLM providers."""

    def __init__(self) -> None:
        self._providers: Dict[str, Type[LLMProvider]] = dict(_BUILTIN_PROVIDERS)
        self._instances: Dict[str, LLMProvider] = {}

    def register(self, name: str, provider_cls: Type[LLMProvider]) -> None:
        self._providers[name] = provider_cls

    def list_providers(self) -> List[str]:
        return list(self._providers.keys())

    def create(
        self,
        name: str,
        api_key: str = "",
        api_base: str = "",
        model: str = "",
        **kwargs: Any,
    ) -> LLMProvider:
        """Create a new provider instance."""
        cls = self._providers.get(name)
        if cls is None:
            raise ProviderError(f"Unknown provider: {name}. Available: {self.list_providers()}")

        instance = cls(api_key=api_key, api_base=api_base, model=model, **kwargs)
        self._instances[name] = instance
        return instance

    def get_or_create(
        self,
        name: str,
        api_key: str = "",
        api_base: str = "",
        model: str = "",
        **kwargs: Any,
    ) -> LLMProvider:
        """Get existing instance or create new one.

        Recreates the instance if api_key or api_base changed.
        """
        if name in self._instances:
            inst = self._instances[name]
            key_changed = api_key != inst.api_key
            base_changed = api_base != (inst.api_base or "")
            if key_changed or base_changed:
                return self.create(name, api_key=api_key, api_base=api_base, model=model, **kwargs)
            if model and inst.model != model:
                inst.model = model
            return inst
        return self.create(name, api_key=api_key, api_base=api_base, model=model, **kwargs)

    def get_instance(self, name: str) -> Optional[LLMProvider]:
        return self._instances.get(name)
