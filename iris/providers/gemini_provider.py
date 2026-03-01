"""Google Gemini provider adapter."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Generator, List, NoReturn, Optional

from ..core.errors import AuthenticationError, ContextLengthError, ProviderError, RateLimitError
from ..core.types import (
    Message, ModelInfo, ProviderCapabilities, Role, StreamChunk,
    TokenUsage, ToolCall,
)
from .base import LLMProvider


class GeminiProvider(LLMProvider):
    """Adapter for Google Gemini via the google-genai SDK."""

    def __init__(self, api_key: str = "", model: str = "gemini-2.0-flash", **kwargs):
        api_key = api_key or os.environ.get("GOOGLE_API_KEY", "") or os.environ.get("GEMINI_API_KEY", "")
        super().__init__(api_key=api_key, model=model)

    def _get_client(self):
        if self._client is None:
            try:
                import google.generativeai as genai
            except ImportError:
                raise ProviderError(
                    "google-generativeai package not installed. Run: pip install google-generativeai",
                    provider="gemini",
                )
            if not self.api_key:
                raise AuthenticationError(provider="gemini")
            genai.configure(api_key=self.api_key)
            self._client = genai
        return self._client

    @property
    def name(self) -> str:
        return "gemini"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            streaming=True, tool_use=True, vision=True,
            max_context_window=1000000, max_output_tokens=8192,
            supports_system_prompt=True,
        )

    def _fetch_models_live(self) -> List[ModelInfo]:
        """Fetch content-generation models from the Gemini API."""
        genai = self._get_client()
        models = []
        for m in genai.list_models():
            name = m.name
            model_id = name.replace("models/", "") if name.startswith("models/") else name
            methods = getattr(m, "supported_generation_methods", [])
            if "generateContent" not in methods:
                continue
            display = getattr(m, "display_name", model_id)
            ctx = getattr(m, "input_token_limit", 1000000) or 1000000
            out = getattr(m, "output_token_limit", 8192) or 8192
            models.append(ModelInfo(
                id=model_id,
                name=display,
                provider="gemini",
                context_window=ctx,
                max_output_tokens=out,
                supports_tools=True,
                supports_vision=True,
            ))
        models.sort(key=lambda m: m.id, reverse=True)
        return models if models else self._builtin_models()

    @staticmethod
    def _builtin_models() -> List[ModelInfo]:
        return [
            ModelInfo("gemini-2.5-pro-preview-06-05", "Gemini 2.5 Pro", "gemini", 1000000, 65536, True, True),
            ModelInfo("gemini-2.0-flash", "Gemini 2.0 Flash", "gemini", 1000000, 8192, True, True),
            ModelInfo("gemini-2.5-flash-preview-05-20", "Gemini 2.5 Flash", "gemini", 1000000, 65536, True, True),
        ]

    def _handle_api_error(self, e: Exception) -> NoReturn:
        """Raise the appropriate IRIS error from a Gemini API error.

        Uses typed exception checks from google.api_core.exceptions when
        available, falling back to string matching for older SDK versions.
        """
        # Prefer typed exception checks from google.api_core.exceptions
        try:
            from google.api_core import exceptions as gexc
            if isinstance(e, (gexc.Unauthenticated, gexc.PermissionDenied)):
                raise AuthenticationError(provider="gemini") from e
            if isinstance(e, gexc.ResourceExhausted):
                raise RateLimitError(provider="gemini") from e
            if isinstance(e, gexc.InvalidArgument):
                msg = str(e)
                if "token" in msg.lower() and ("limit" in msg.lower() or "exceed" in msg.lower()):
                    raise ContextLengthError(msg, provider="gemini") from e
        except ImportError:
            pass

        # Fallback: string matching for errors not caught above (older SDKs
        # without google.api_core, or unexpected exception types).
        msg = str(e)
        msg_lower = msg.lower()
        if "api key" in msg_lower or "permission" in msg_lower or "unauthenticated" in msg_lower or "401" in msg:
            raise AuthenticationError(provider="gemini") from e
        if "rate limit" in msg_lower or "resource exhausted" in msg_lower or "quota" in msg_lower or "429" in msg:
            raise RateLimitError(provider="gemini") from e
        if "token" in msg_lower and ("limit" in msg_lower or "exceed" in msg_lower):
            raise ContextLengthError(msg, provider="gemini") from e
        raise ProviderError(msg, provider="gemini") from e

    def _build_tools(self, tools: List[Dict[str, Any]]) -> list:
        """Convert tool definitions to Gemini function declarations.

        The Gemini protobuf API expects ``Type`` enum values (``Type.OBJECT``,
        ``Type.STRING``, …) whereas our tool schemas use JSON Schema type
        strings (``"object"``, ``"string"``, …).  We recursively convert
        type strings to the ``Type`` enum before constructing declarations.
        """
        genai = self._get_client()
        Type = genai.protos.Type  # enum: STRING, NUMBER, INTEGER, BOOLEAN, ARRAY, OBJECT
        _TYPE_MAP = {
            "string": Type.STRING,
            "number": Type.NUMBER,
            "integer": Type.INTEGER,
            "boolean": Type.BOOLEAN,
            "array": Type.ARRAY,
            "object": Type.OBJECT,
        }

        def _convert_schema(schema: Dict[str, Any]) -> Dict[str, Any]:
            """Recursively convert JSON Schema type strings to Gemini Type enums."""
            out: Dict[str, Any] = {}
            for k, v in schema.items():
                if k == "type" and isinstance(v, str):
                    out[k] = _TYPE_MAP.get(v, Type.STRING)
                elif k == "properties" and isinstance(v, dict):
                    out[k] = {pk: _convert_schema(pv) for pk, pv in v.items()}
                elif k == "items" and isinstance(v, dict):
                    out[k] = _convert_schema(v)
                else:
                    out[k] = v
            return out

        declarations = []
        for t in tools:
            func = t.get("function", t)
            params = func.get("parameters", {})
            declarations.append(genai.protos.FunctionDeclaration(
                name=func["name"],
                description=func.get("description", ""),
                parameters=_convert_schema(params) if params else None,
            ))
        return [genai.protos.Tool(function_declarations=declarations)]

    def _format_history(self, messages: List[Message]) -> list:
        """Convert messages to Gemini chat history."""
        genai = self._get_client()
        history = []
        for msg in messages:
            if msg.role == Role.SYSTEM:
                continue
            elif msg.role == Role.USER:
                history.append({"role": "user", "parts": [msg.content]})
            elif msg.role == Role.ASSISTANT:
                parts = []
                if msg.content:
                    parts.append(msg.content)
                for tc in msg.tool_calls:
                    parts.append(genai.protos.Part(
                        function_call=genai.protos.FunctionCall(
                            name=tc.name, args=tc.arguments,
                        )
                    ))
                history.append({"role": "model", "parts": parts})
            elif msg.role == Role.TOOL:
                parts = []
                for tr in msg.tool_results:
                    parts.append(genai.protos.Part(
                        function_response=genai.protos.FunctionResponse(
                            name=tr.name,
                            response={"result": tr.content},
                        )
                    ))
                history.append({"role": "user", "parts": parts})
        return history

    def chat(
        self, messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.3, max_tokens: int = 4096, system: str = "",
    ) -> Message:
        genai = self._get_client()
        gen_config = genai.GenerationConfig(
            temperature=temperature, max_output_tokens=max_tokens,
        )
        kwargs: Dict[str, Any] = {"generation_config": gen_config}
        if system:
            kwargs["system_instruction"] = system
        if tools:
            kwargs["tools"] = self._build_tools(tools)

        model = genai.GenerativeModel(self.model, **kwargs)
        history = self._format_history(messages[:-1]) if len(messages) > 1 else []
        chat = model.start_chat(history=history)

        last_msg = messages[-1].content if messages else ""
        try:
            response = chat.send_message(last_msg)
        except Exception as e:
            self._handle_api_error(e)

        return self._normalize_response(response)

    def _normalize_response(self, response) -> Message:
        text = ""
        tool_calls = []
        for part in response.candidates[0].content.parts:
            if hasattr(part, "text") and part.text:
                text += part.text
            if hasattr(part, "function_call") and part.function_call:
                fc = part.function_call
                tool_calls.append(ToolCall(
                    id=ToolCall.make_id(),
                    name=fc.name,
                    arguments=dict(fc.args) if fc.args else {},
                ))

        usage = TokenUsage()
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            um = response.usage_metadata
            usage = TokenUsage(
                prompt_tokens=getattr(um, "prompt_token_count", 0) or 0,
                completion_tokens=getattr(um, "candidates_token_count", 0) or 0,
                total_tokens=getattr(um, "total_token_count", 0) or 0,
            )

        return Message(role=Role.ASSISTANT, content=text, tool_calls=tool_calls, token_usage=usage)

    def chat_stream(
        self, messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.3, max_tokens: int = 4096, system: str = "",
    ) -> Generator[StreamChunk, None, None]:
        genai = self._get_client()
        gen_config = genai.GenerationConfig(
            temperature=temperature, max_output_tokens=max_tokens,
        )
        kwargs: Dict[str, Any] = {"generation_config": gen_config}
        if system:
            kwargs["system_instruction"] = system
        if tools:
            kwargs["tools"] = self._build_tools(tools)

        model = genai.GenerativeModel(self.model, **kwargs)
        history = self._format_history(messages[:-1]) if len(messages) > 1 else []
        chat = model.start_chat(history=history)

        last_msg = messages[-1].content if messages else ""
        try:
            response = chat.send_message(last_msg, stream=True)
            for chunk in response:
                for part in chunk.candidates[0].content.parts:
                    if hasattr(part, "text") and part.text:
                        yield StreamChunk(text=part.text)
                    if hasattr(part, "function_call") and part.function_call:
                        fc = part.function_call
                        call_id = ToolCall.make_id()
                        yield StreamChunk(
                            tool_call_id=call_id,
                            tool_name=fc.name,
                            tool_args_delta=json.dumps(dict(fc.args) if fc.args else {}),
                            is_tool_call_start=True,
                        )
                        yield StreamChunk(
                            tool_call_id=call_id,
                            tool_name=fc.name,
                            is_tool_call_end=True,
                        )
        except Exception as e:
            self._handle_api_error(e)
