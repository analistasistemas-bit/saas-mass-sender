import asyncio

import httpx
import pytest

from services.whatsapp import (
    MAX_BRIDGE_MEDIA_BYTES,
    MediaUploadError,
    WhatsAppClient,
    WhatsAppError,
    prepare_bridge_media_upload,
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for key in [
        'WHATSAPP_PROVIDER',
        'EVOLUTION_BASE_URL',
        'EVOLUTION_INSTANCE',
        'EVOLUTION_API_KEY',
        'WA_BRIDGE_BASE_URL',
        'WA_BRIDGE_API_KEY',
    ]:
        monkeypatch.delenv(key, raising=False)


def test_bridge_client_healthcheck(monkeypatch):
    monkeypatch.setenv('WHATSAPP_PROVIDER', 'bridge')
    monkeypatch.setenv('WA_BRIDGE_BASE_URL', 'http://bridge.local')

    async def handler(request):
        assert request.url.path == '/health'
        return httpx.Response(200, json={'ok': True, 'connected': True})

    transport = httpx.MockTransport(handler)
    client = WhatsAppClient(transport=transport)

    ok, message = asyncio.run(client.healthcheck())

    assert client.provider == 'bridge'
    assert client.configured is True
    assert ok is True
    assert 'Bridge' in message


def test_bridge_client_send_text(monkeypatch):
    monkeypatch.setenv('WHATSAPP_PROVIDER', 'bridge')
    monkeypatch.setenv('WA_BRIDGE_BASE_URL', 'http://bridge.local')
    monkeypatch.setenv('WA_BRIDGE_API_KEY', 'secret')

    async def handler(request):
        assert request.url.path == '/messages/send-text'
        assert request.headers['x-api-key'] == 'secret'
        assert request.method == 'POST'
        assert request.read() == b'{"phone":"+5511999999999","text":"oi"}'
        return httpx.Response(200, json={'ok': True})

    transport = httpx.MockTransport(handler)
    client = WhatsAppClient(transport=transport)

    asyncio.run(client.send_text('+5511999999999', 'oi'))


def test_bridge_client_send_text_classifies_errors(monkeypatch):
    monkeypatch.setenv('WHATSAPP_PROVIDER', 'bridge')
    monkeypatch.setenv('WA_BRIDGE_BASE_URL', 'http://bridge.local')

    async def handler(_request):
        return httpx.Response(503, text='temporarily down')

    transport = httpx.MockTransport(handler)
    client = WhatsAppClient(transport=transport)

    with pytest.raises(WhatsAppError) as exc:
        asyncio.run(client.send_text('+5511999999999', 'oi'))

    assert exc.value.error_class == 'temporary'
    assert exc.value.http_status == 503


def test_bridge_client_send_text_classifies_detached_frame_as_session_error(monkeypatch):
    monkeypatch.setenv('WHATSAPP_PROVIDER', 'bridge')
    monkeypatch.setenv('WA_BRIDGE_BASE_URL', 'http://bridge.local')

    async def handler(_request):
        return httpx.Response(
            502,
            json={'ok': False, 'message': 'Attempted to use detached Frame "frame-1".', 'state': 'ready'},
        )

    transport = httpx.MockTransport(handler)
    client = WhatsAppClient(transport=transport)

    with pytest.raises(WhatsAppError) as exc:
        asyncio.run(client.send_text('+5511999999999', 'oi'))

    assert exc.value.error_class == 'session'
    assert exc.value.http_status == 502


def test_bridge_session(monkeypatch):
    monkeypatch.setenv('WHATSAPP_PROVIDER', 'bridge')
    monkeypatch.setenv('WA_BRIDGE_BASE_URL', 'http://bridge.local')

    async def handler(request):
        assert request.url.path == '/session'
        return httpx.Response(200, json={'ok': True, 'connected': False, 'state': 'qr_ready'})

    transport = httpx.MockTransport(handler)
    client = WhatsAppClient(transport=transport)
    payload = asyncio.run(client.bridge_session())

    assert payload['state'] == 'qr_ready'


def test_bridge_qr(monkeypatch):
    monkeypatch.setenv('WHATSAPP_PROVIDER', 'bridge')
    monkeypatch.setenv('WA_BRIDGE_BASE_URL', 'http://bridge.local')

    async def handler(request):
        assert request.url.path == '/session/qr'
        return httpx.Response(200, json={'ok': True, 'base64': 'data:image/png;base64,abc'})

    transport = httpx.MockTransport(handler)
    client = WhatsAppClient(transport=transport)
    payload = asyncio.run(client.bridge_qr())

    assert payload['base64'].startswith('data:image/png;base64,')


def test_bridge_restart(monkeypatch):
    monkeypatch.setenv('WHATSAPP_PROVIDER', 'bridge')
    monkeypatch.setenv('WA_BRIDGE_BASE_URL', 'http://bridge.local')

    async def handler(request):
        assert request.url.path == '/session/restart'
        assert request.method == 'POST'
        return httpx.Response(200, json={'ok': True, 'message': 'session restarting'})

    transport = httpx.MockTransport(handler)
    client = WhatsAppClient(transport=transport)
    payload = asyncio.run(client.bridge_restart())

    assert payload['ok'] is True


def test_prepare_bridge_media_upload_accepts_pdf_and_jpeg_alias():
    prepared = prepare_bridge_media_upload(
        filename='pasta/boleto.pdf',
        content_type='application/pdf',
        content=b'%PDF-1.4 ok',
    )
    assert prepared['filename'] == 'boleto.pdf'
    assert prepared['mimetype'] == 'application/pdf'
    assert prepared['data']

    jpeg = prepare_bridge_media_upload(
        filename='foto.jpg',
        content_type='image/jpg',
        content=b'\xff\xd8\xff\xd9',
    )
    assert jpeg['mimetype'] == 'image/jpeg'


def test_prepare_bridge_media_upload_falls_back_to_extension():
    prepared = prepare_bridge_media_upload(
        filename='imagem.PNG',
        content_type='application/octet-stream',
        content=b'\x89PNG\r\n\x1a\nrest',
    )
    assert prepared['mimetype'] == 'image/png'
    assert prepared['filename'] == 'imagem.PNG'


def test_prepare_bridge_media_upload_rejects_type_mismatch_and_size():
    with pytest.raises(MediaUploadError) as bad_type:
        prepare_bridge_media_upload(filename='a.pdf', content_type='application/pdf', content=b'not-a-pdf')
    assert bad_type.value.status_code == 400

    blob = b'%PDF-' + b'0' * (MAX_BRIDGE_MEDIA_BYTES - 4)
    with pytest.raises(MediaUploadError) as too_big:
        prepare_bridge_media_upload(filename='a.pdf', content_type='application/pdf', content=blob)
    assert too_big.value.status_code == 413


def test_bridge_client_send_media(monkeypatch):
    monkeypatch.setenv('WHATSAPP_PROVIDER', 'bridge')
    monkeypatch.setenv('WA_BRIDGE_BASE_URL', 'http://bridge.local')
    monkeypatch.setenv('WA_BRIDGE_API_KEY', 'secret')

    async def handler(request):
        assert request.url.path == '/messages/send-media'
        assert request.headers['x-api-key'] == 'secret'
        body = request.read()
        assert b'"phone":"+5511999999999"' in body
        assert b'"mimetype":"application/pdf"' in body
        assert b'"filename":"boleto.pdf"' in body
        assert b'"caption":"segue"' in body
        return httpx.Response(200, json={'ok': True, 'chatId': '5511999999999@c.us'})

    transport = httpx.MockTransport(handler)
    client = WhatsAppClient(transport=transport)
    payload = asyncio.run(
        client.send_media(
            '+5511999999999',
            data_base64='JVBERi0=',
            mimetype='application/pdf',
            filename='boleto.pdf',
            caption='segue',
        )
    )
    assert payload['chatId'] == '5511999999999@c.us'


def test_bridge_client_send_media_classifies_session_error(monkeypatch):
    monkeypatch.setenv('WHATSAPP_PROVIDER', 'bridge')
    monkeypatch.setenv('WA_BRIDGE_BASE_URL', 'http://bridge.local')

    async def handler(_request):
        return httpx.Response(409, json={'ok': False, 'message': 'whatsapp session not connected'})

    transport = httpx.MockTransport(handler)
    client = WhatsAppClient(transport=transport)
    with pytest.raises(WhatsAppError) as exc:
        asyncio.run(
            client.send_media(
                '+5511999999999',
                data_base64='JVBERi0=',
                mimetype='application/pdf',
                filename='boleto.pdf',
            )
        )
    assert exc.value.http_status == 409
    assert exc.value.error_class == 'permanent'
    assert 'not connected' in str(exc.value)


def test_evolution_client_rejects_send_media(monkeypatch):
    monkeypatch.setenv('WHATSAPP_PROVIDER', 'evolution')
    monkeypatch.setenv('EVOLUTION_BASE_URL', 'http://localhost:8080')
    monkeypatch.setenv('EVOLUTION_INSTANCE', 'demo')
    monkeypatch.setenv('EVOLUTION_API_KEY', 'key')

    client = WhatsAppClient()
    with pytest.raises(WhatsAppError) as exc:
        asyncio.run(
            client.send_media(
                '+5511999999999',
                data_base64='JVBERi0=',
                mimetype='application/pdf',
                filename='boleto.pdf',
            )
        )
    assert exc.value.error_class == 'permanent'


def test_evolution_client_requires_full_credentials(monkeypatch):
    monkeypatch.setenv('WHATSAPP_PROVIDER', 'evolution')
    monkeypatch.setenv('EVOLUTION_BASE_URL', 'http://localhost:8080')

    client = WhatsAppClient()

    assert client.provider == 'evolution'
    assert client.configured is False
    ok, message = asyncio.run(client.healthcheck())
    assert ok is False
    assert 'Credenciais ausentes' in message
