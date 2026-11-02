# -*- coding: utf-8 -*-
"""LLM client helpers for synchronous and asynchronous OpenAI-compatible calls."""

import asyncio
import json
import os
from typing import Dict, List, Optional, Sequence

from bid_agent.core import settings  # Load the project environment once.
from openai import AsyncOpenAI, OpenAI




def _safe_print(*args, **kwargs) -> None:
    try:
        print(*args, **kwargs)
    except Exception:
        pass


class LLM_Invoke:
    def __init__(
        self,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: Optional[int] = None,
        enable_deep_thinking: bool = False,
    ):
        self.model = model or os.getenv("LLM_MODEL_ID")
        api_key = api_key or os.getenv("LLM_API_KEY")
        base_url = base_url or os.getenv("LLM_BASE_URL")
        self.timeout = timeout or int(os.getenv("LLM_TIMEOUT", "120"))
        self.enable_deep_thinking = enable_deep_thinking

        if not all([self.model, api_key, base_url]):
            raise ValueError(
                "请先配置 LLM_MODEL_ID、LLM_API_KEY、LLM_BASE_URL。"
                "可以复制 .env.example 为 .env 后填写。"
            )

        self.client = OpenAI(api_key=api_key, base_url=base_url, timeout=self.timeout)
        self.async_client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=self.timeout,
        )

    def think(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0,
        stream: bool = True,
    ) -> str:
        """Call the model synchronously and optionally stream chunks to stdout."""
        _safe_print(f"\n[model call] model={self.model}, stream={stream}")
        if not stream:
            response = self.client.chat.completions.create(
                **self._completion_kwargs(messages, temperature),
            )
            content = response.choices[0].message.content or ""
            _safe_print(content)
            return content

        response = self.client.chat.completions.create(
            **self._completion_kwargs(messages, temperature),
            stream=True,
        )

        chunks: List[str] = []
        for chunk in response:
            content = chunk.choices[0].delta.content or ""
            _safe_print(content, end="", flush=True)
            chunks.append(content)
        _safe_print()
        return "".join(chunks)

    def think_json(
        self,
        messages: List[Dict[str, str]],
        schema: Dict[str, object],
        temperature: float = 0,
    ) -> str:
        """Call the model with JSON Schema response format when supported."""
        _safe_print(f"\n[model json call] model={self.model}")
        kwargs = self._completion_kwargs(messages, temperature)
        kwargs["response_format"] = _json_schema_response_format(schema)
        response = self.client.chat.completions.create(**kwargs)
        return response.choices[0].message.content or ""

    async def athink(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0,
        stream: bool = False,
    ) -> str:
        """Call the model asynchronously and optionally stream chunks to stdout."""
        _safe_print(f"\n[async model call] model={self.model}, stream={stream}")

        if stream:
            response = await self.async_client.chat.completions.create(
                **self._completion_kwargs(messages, temperature),
                stream=True,
            )

            chunks: List[str] = []
            async for chunk in response:
                content = chunk.choices[0].delta.content or ""
                _safe_print(content, end="", flush=True)
                chunks.append(content)
            _safe_print()
            return "".join(chunks)

        response = await self.async_client.chat.completions.create(
            **self._completion_kwargs(messages, temperature),
        )
        return response.choices[0].message.content or ""

    async def athink_json(
        self,
        messages: List[Dict[str, str]],
        schema: Dict[str, object],
        temperature: float = 0,
    ) -> str:
        """Call the model asynchronously with JSON Schema response format."""
        _safe_print(f"\n[async model json call] model={self.model}")
        kwargs = self._completion_kwargs(messages, temperature)
        kwargs["response_format"] = _json_schema_response_format(schema)
        response = await self.async_client.chat.completions.create(**kwargs)
        return response.choices[0].message.content or ""

    async def astream(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0,
    ):
        """Yield streamed text chunks from one chat completion."""
        _safe_print(f"\n[async stream model call] model={self.model}")
        response = await self.async_client.chat.completions.create(
            **self._completion_kwargs(messages, temperature),
            stream=True,
        )
        async for chunk in response:
            content = chunk.choices[0].delta.content or ""
            if content:
                _safe_print(content, end="", flush=True)
                yield content
        _safe_print()

    async def think_many(
        self,
        messages_batch: Sequence[List[Dict[str, str]]],
        temperature: float = 0,
        max_concurrency: Optional[int] = None,
        stream: bool = False,
    ) -> List[str]:
        """Run multiple independent prompts concurrently and keep result order."""
        concurrency = max_concurrency or int(os.getenv("LLM_MAX_CONCURRENCY", "2"))
        semaphore = asyncio.Semaphore(concurrency)

        async def run_one(messages: List[Dict[str, str]]) -> str:
            async with semaphore:
                return await self.athink(messages, temperature=temperature, stream=stream)

        return await asyncio.gather(*(run_one(messages) for messages in messages_batch))

    def think_many_sync(
        self,
        messages_batch: Sequence[List[Dict[str, str]]],
        temperature: float = 0,
        max_concurrency: Optional[int] = None,
        stream: bool = False,
    ) -> List[str]:
        """Synchronous wrapper around think_many for scripts without an event loop."""
        return asyncio.run(
            self.think_many(
                messages_batch,
                temperature=temperature,
                max_concurrency=max_concurrency,
                stream=stream,
            )
        )

    def _completion_kwargs(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
    ) -> Dict[str, object]:
        kwargs: Dict[str, object] = {
            "model": self.model,
            "messages": self._prepare_messages(messages),
            "temperature": temperature,
        }
        extra_body = self._deep_thinking_extra_body()
        if extra_body:
            kwargs["extra_body"] = extra_body
        return kwargs

    def _prepare_messages(self, messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
        if not self._supports_deep_thinking():
            return messages

        thinking_instruction = (
            "请开启深度思考模式。先在内部充分分析招标文件上下文、评分规则、"
            "显性和隐性要求，再输出最终结果。最终回复只保留用户要求的内容，"
            "不要输出思考过程。"
        )
        prepared = [dict(message) for message in messages]
        for message in prepared:
            if message.get("role") == "system":
                message["content"] = f"{message.get('content', '')}\n\n{thinking_instruction}"
                return prepared
        return [{"role": "system", "content": thinking_instruction}, *prepared]

    def _deep_thinking_extra_body(self) -> Dict[str, object]:
        if not self._supports_deep_thinking():
            return {}
        model_name = (self.model or "").lower()
        if "qwen" in model_name:
            return {"enable_thinking": True}
        return {}

    def _supports_deep_thinking(self) -> bool:
        if not self.enable_deep_thinking:
            return False
        model_name = (self.model or "").lower()
        return "qwen" in model_name or "deepseek-r1" in model_name


def _json_schema_response_format(schema: Dict[str, object]) -> Dict[str, object]:
    name = str(schema.get("title") or "bid_structured_extraction")
    safe_name = "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in name)[:64]
    return {
        "type": "json_schema",
        "json_schema": {
            "name": safe_name or "bid_structured_extraction",
            "schema": schema,
            "strict": True,
        },
    }
