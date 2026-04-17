from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import httpx


class WhatsAppError(Exception):
    def __init__(self, message: str, http_status: Optional[int] = None, error_class: str = 'temporary'):
        super().__init__(message)
        self.http_status = http_status
        self.error_class = error_class


def is_bridge_session_error_message(message: str | None) -> bool:
    lowered = str(message or '').lower()
    markers = (
        'attempted to use detached frame',
        'execution context was destroyed',
        'target closed',
        'session closed',
    )
    return any(marker in lowered for marker in markers)


def is_bridge_session_healthy(session: Optional[dict]) -> bool:
    if not session:
        return False
    if not session.get('connected'):
        return False
    state = str(session.get('state') or '').lower()
    if state not in {'ready', 'connected'}:
        return False
    return not is_bridge_session_error_message(session.get('lastError'))


def classify_http_error(status_code: int) -> str:
    if status_code == 429 or 500 <= status_code <= 599:
        return 'temporary'
    if 400 <= status_code <= 499:
        return 'permanent'
    return 'temporary'


def classify_exception(exc: Exception) -> str:
    if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError)):
        return 'temporary'
    return 'temporary'


class WhatsAppClient:
    _shared_client: httpx.AsyncClient | None = None

    @classmethod
    def get_shared_client(cls) -> httpx.AsyncClient:
        if cls._shared_client is None or cls._shared_client.is_closed:
            cls._shared_client = httpx.AsyncClient()
        return cls._shared_client

    def __init__(self, transport: Optional[httpx.AsyncBaseTransport] = None) -> None:
        explicit_provider = os.getenv('WHATSAPP_PROVIDER', '').strip().lower()
        bridge_base_url = os.getenv('WA_BRIDGE_BASE_URL', '').rstrip('/')

        if explicit_provider:
            self.provider = explicit_provider
        elif bridge_base_url:
            self.provider = 'bridge'
        else:
            self.provider = 'evolution'

        self._transport = transport
        self.base_url = os.getenv('EVOLUTION_BASE_URL', '').rstrip('/')
        self.instance = os.getenv('EVOLUTION_INSTANCE', '')
        self.api_key = os.getenv('EVOLUTION_API_KEY', '')
        self.bridge_base_url = bridge_base_url
        self.bridge_api_key = os.getenv('WA_BRIDGE_API_KEY', '')

    @property
    def configured(self) -> bool:
        if self.provider == 'bridge':
            return bool(self.bridge_base_url)
        return bool(self.base_url and self.instance and self.api_key)

    def _headers(self) -> dict[str, str]:
        if self.provider == 'bridge':
            headers = {}
            if self.bridge_api_key:
                headers['x-api-key'] = self.bridge_api_key
            return headers
        return {'apikey': self.api_key}



    def _send_url(self) -> str:
        if self.provider == 'bridge':
            return f'{self.bridge_base_url}/messages/send-text'
        return f'{self.base_url}/message/sendText/{self.instance}'

    async def _bridge_request(self, method: str, path: str) -> dict:
        if self.provider != 'bridge':
            raise WhatsAppError('Operação disponível apenas para provider bridge', error_class='permanent')
        if not self.configured:
            raise WhatsAppError('Bridge não configurado', error_class='temporary')

        url = f'{self.bridge_base_url}{path}'
        try:
            if self._transport:
                async with httpx.AsyncClient(timeout=15, transport=self._transport) as temp_client:
                    response = await temp_client.request(method, url, headers=self._headers())
            else:
                client = self.get_shared_client()
                response = await client.request(method, url, headers=self._headers(), timeout=15)
        except Exception as exc:
            raise WhatsAppError(str(exc), error_class=classify_exception(exc)) from exc

        if response.status_code >= 400:
            message = response.text[:500]
            err_class = 'session' if is_bridge_session_error_message(message) else classify_http_error(response.status_code)
            raise WhatsAppError(message, http_status=response.status_code, error_class=err_class)

        try:
            return response.json()
        except Exception as exc:
            raise WhatsAppError(f'Resposta inválida do bridge: {exc}', error_class='temporary') from exc

    async def send_text(self, phone_e164: str, text: str) -> None:
        if not self.configured:
            raise WhatsAppError('Backend WhatsApp não configurado', error_class='temporary')

        if self.provider == 'bridge':
            payload = {'phone': phone_e164, 'text': text}
        else:
            payload = {'number': phone_e164, 'textMessage': {'text': text}}

        try:
            if self._transport:
                async with httpx.AsyncClient(timeout=25, transport=self._transport) as temp_client:
                    response = await temp_client.post(self._send_url(), json=payload, headers=self._headers())
            else:
                client = self.get_shared_client()
                response = await client.post(self._send_url(), json=payload, headers=self._headers(), timeout=25)
        except Exception as exc:  # network/timeouts
            raise WhatsAppError(str(exc), error_class=classify_exception(exc)) from exc

        if response.status_code >= 400:
            message = response.text[:500]
            err_class = 'session' if self.provider == 'bridge' and is_bridge_session_error_message(message) else classify_http_error(response.status_code)
            raise WhatsAppError(message, http_status=response.status_code, error_class=err_class)

    async def bridge_session(self) -> dict:
        return await self._bridge_request('GET', '/session')

    async def bridge_qr(self) -> dict:
        return await self._bridge_request('GET', '/session/qr')

    async def bridge_restart(self) -> dict:
        return await self._bridge_request('POST', '/session/restart')

    async def bridge_reset(self) -> dict:
        return await self._bridge_request('POST', '/session/reset')

    def can_manage_local_bridge(self) -> bool:
        if self.provider != 'bridge':
            return False
        if not self.bridge_base_url:
            return False
        parsed = urlparse(self.bridge_base_url)
        host = (parsed.hostname or '').strip().lower()
        bridge_dir = Path(__file__).resolve().parent.parent / 'wa-bridge'
        return host in {'127.0.0.1', 'localhost', '::1'} and bridge_dir.exists() and (bridge_dir / 'package.json').exists()

    async def bridge_restart_local_process(self) -> bool:
        if not self.can_manage_local_bridge():
            return False

        bridge_dir = Path(__file__).resolve().parent.parent / 'wa-bridge'
        npm_bin = shutil.which('npm')
        pkill_bin = shutil.which('pkill')
        if not npm_bin:
            return False

        if pkill_bin:
            stop_process = await asyncio.create_subprocess_exec(
                pkill_bin,
                '-f',
                str(bridge_dir / 'server.js'),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await stop_process.wait()

        start_process = await asyncio.create_subprocess_exec(
            npm_bin,
            'start',
            cwd=str(bridge_dir),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True,
        )
        await asyncio.sleep(1)
        return start_process.returncode in {None, 0}

    async def healthcheck(self) -> tuple[bool, str]:
        if not self.configured:
            return False, 'Credenciais ausentes'

        try:
            if self._transport:
                async with httpx.AsyncClient(timeout=10, transport=self._transport) as temp_client:
                    if self.provider == 'bridge':
                        response = await temp_client.get(f'{self.bridge_base_url}/health', headers=self._headers())
                        if response.status_code < 500:
                            payload = response.json()
                            connected = payload.get('connected')
                            state = payload.get('state', 'unknown')
                            if connected and is_bridge_session_error_message(payload.get('lastError')):
                                return True, f'Bridge acessível, sessão instável ({state})'
                            if connected:
                                return True, f'Bridge acessível ({state})'
                            return True, f'Bridge acessível, sessão {state}'
                        return False, f'Bridge indisponível ({response.status_code})'

                    response = await temp_client.get(self.base_url, headers=self._headers())
            else:
                client = self.get_shared_client()
                if self.provider == 'bridge':
                    response = await client.get(f'{self.bridge_base_url}/health', headers=self._headers(), timeout=10)
                    if response.status_code < 500:
                        payload = response.json()
                        connected = payload.get('connected')
                        state = payload.get('state', 'unknown')
                        if connected and is_bridge_session_error_message(payload.get('lastError')):
                            return True, f'Bridge acessível, sessão instável ({state})'
                        if connected:
                            return True, f'Bridge acessível ({state})'
                        return True, f'Bridge acessível, sessão {state}'
                    return False, f'Bridge indisponível ({response.status_code})'

                response = await client.get(self.base_url, headers=self._headers(), timeout=10)
                
            if response.status_code < 500:
                return True, 'Evolution acessível'
            return False, f'Evolution indisponível ({response.status_code})'
        except Exception as exc:
            return False, f'Falha de conexão: {exc}'
