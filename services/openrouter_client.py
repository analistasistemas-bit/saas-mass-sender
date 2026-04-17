from __future__ import annotations

import json
import os
import re
from typing import Optional

import httpx


class OpenRouterClient:
    _shared_client: httpx.AsyncClient | None = None

    @classmethod
    def get_shared_client(cls) -> httpx.AsyncClient:
        if cls._shared_client is None or cls._shared_client.is_closed:
            cls._shared_client = httpx.AsyncClient()
        return cls._shared_client

    def __init__(self, transport: Optional[httpx.AsyncBaseTransport] = None) -> None:
        self.api_key = os.getenv('OPENROUTER_API_KEY', '').strip()
        self.model = os.getenv('OPENROUTER_MODEL', '').strip()
        self.base_url = os.getenv('OPENROUTER_BASE_URL', 'https://openrouter.ai/api/v1').rstrip('/')
        self._transport = transport

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.model)

    async def _chat_completion(self, *, messages: list[dict], system_prompt: str, model_override: str | None = None, response_format: dict | None = None) -> dict:
        model = str(model_override or self.model or '').strip()
        if not self.api_key or not model:
            raise RuntimeError('OpenRouter não configurado')

        payload = {
            'model': model,
            'messages': [{'role': 'system', 'content': system_prompt}] + messages,
        }
        if response_format is not None:
            payload['response_format'] = response_format

        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json',
        }

        if self._transport:
            async with httpx.AsyncClient(timeout=20, transport=self._transport) as temp_client:
                response = await temp_client.post(f'{self.base_url}/chat/completions', json=payload, headers=headers)
        else:
            client = self.get_shared_client()
            response = await client.post(f'{self.base_url}/chat/completions', json=payload, headers=headers, timeout=20)
            
        response.raise_for_status()
        return response.json()

    def _extract_content(self, data: dict) -> str:
        choices = data.get('choices') or []
        if not choices:
            raise RuntimeError('OpenRouter sem choices')

        message = choices[0].get('message') or {}
        content = message.get('content')
        if isinstance(content, list):
            content = ''.join(str(item.get('text') or '') for item in content if isinstance(item, dict))
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError('OpenRouter sem conteúdo')
        return content

    def _parse_json_content(self, content: str) -> dict:
        raw = str(content or '').strip()
        if not raw:
            raise RuntimeError('OpenRouter sem conteúdo JSON')

        candidates = [raw]

        fenced_match = re.search(r"```(?:json)?\s*(.*?)\s*```", raw, flags=re.IGNORECASE | re.DOTALL)
        if fenced_match:
            candidates.append(fenced_match.group(1).strip())

        first_brace = raw.find('{')
        last_brace = raw.rfind('}')
        if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
            candidates.append(raw[first_brace:last_brace + 1].strip())

        for candidate in candidates:
            try:
                parsed = json.loads(candidate)
            except Exception:
                continue
            if isinstance(parsed, dict):
                return parsed

        raise RuntimeError('OpenRouter retornou conteúdo não compatível com JSON estruturado')

    async def complete_json(self, *, messages: list[dict], system_prompt: str, model_override: str | None = None) -> dict:
        data = await self._chat_completion(
            messages=messages,
            system_prompt=system_prompt,
            model_override=model_override,
            response_format={'type': 'json_object'},
        )
        content = self._extract_content(data)
        return self._parse_json_content(content)

    async def complete_text(self, *, messages: list[dict], system_prompt: str, model_override: str | None = None) -> str:
        data = await self._chat_completion(
            messages=messages,
            system_prompt=system_prompt,
            model_override=model_override,
            response_format=None,
        )
        return self._extract_content(data)
