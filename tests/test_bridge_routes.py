from fastapi.testclient import TestClient

import main
from services.whatsapp import WhatsAppError


class _FakeBridgeClient:
    provider = 'bridge'

    async def bridge_session(self):
        return {'connected': False, 'state': 'qr_ready', 'phone': '5581999999999'}

    async def bridge_qr(self):
        return {'base64': 'data:image/png;base64,abc'}

    async def bridge_restart(self):
        return {'ok': True, 'message': 'session restarting'}

    async def bridge_reset(self):
        return {'ok': True, 'message': 'session reset'}


class _FailingBridgeClient:
    provider = 'bridge'

    async def bridge_session(self):
        raise WhatsAppError('Connection refused')

    async def bridge_qr(self):
        raise WhatsAppError('Connection refused')

    async def bridge_restart(self):
        raise WhatsAppError('Connection refused')

    async def bridge_reset(self):
        raise WhatsAppError('Connection refused')


def test_bridge_routes_require_auth():
    client = TestClient(main.app)
    response = client.get('/bridge/session')
    assert response.status_code == 401


def test_html_routes_redirect_to_login_when_unauthenticated():
    client = TestClient(main.app)
    response = client.get('/', follow_redirects=False, headers={'accept': 'text/html'})
    assert response.status_code == 303
    assert response.headers['location'] == '/login'


def test_bridge_routes_with_auth(monkeypatch):
    monkeypatch.setattr(main, 'WhatsAppClient', _FakeBridgeClient)
    client = TestClient(main.app)
    client.cookies.set('mass_sender_admin', main.APP_PASSWORD)

    session = client.get('/bridge/session')
    assert session.status_code == 200
    assert session.json()['ok'] is True
    assert session.json()['session']['state'] == 'qr_ready'

    qr = client.get('/bridge/qr')
    assert qr.status_code == 200
    assert qr.json()['ok'] is True
    assert qr.json()['qr']['base64'].startswith('data:image/png;base64,')

    restart = client.post('/bridge/restart')
    assert restart.status_code == 200
    assert restart.json()['ok'] is True

    reset = client.post('/bridge/reset')
    assert reset.status_code == 200
    assert reset.json()['ok'] is True


class _MediaBridgeClient:
    provider = 'bridge'
    calls = []

    async def send_media(self, phone, *, data_base64, mimetype, filename, caption=''):
        type(self).calls.append(
            {
                'phone': phone,
                'data_base64': data_base64,
                'mimetype': mimetype,
                'filename': filename,
                'caption': caption,
            }
        )
        return {'ok': True, 'chatId': '5581999999999@c.us', 'filename': filename, 'mimetype': mimetype}


class _DisconnectedMediaBridgeClient:
    provider = 'bridge'

    async def send_media(self, phone, *, data_base64, mimetype, filename, caption=''):
        raise WhatsAppError('whatsapp session not connected', http_status=409, error_class='permanent')


class _EvolutionClient:
    provider = 'evolution'


def _auth_client():
    client = TestClient(main.app)
    client.cookies.set('mass_sender_admin', main.APP_PASSWORD)
    return client


def test_bridge_send_media_requires_auth():
    client = TestClient(main.app)
    response = client.post(
        '/bridge/send-media',
        data={'phone': '+5581999999999'},
        files={'file': ('boleto.pdf', b'%PDF-1.4', 'application/pdf')},
    )
    assert response.status_code == 401


def test_bridge_send_media_forwards_file(monkeypatch):
    _MediaBridgeClient.calls = []
    monkeypatch.setattr(main, 'WhatsAppClient', _MediaBridgeClient)
    client = _auth_client()
    response = client.post(
        '/bridge/send-media',
        data={'phone': '+55 (81) 99999-9999', 'caption': 'boleto'},
        files={'file': ('docs/boleto.pdf', b'%PDF-1.4 sample', 'application/pdf')},
    )
    assert response.status_code == 200
    body = response.json()
    assert body['ok'] is True
    assert body['result']['chatId'] == '5581999999999@c.us'
    assert len(_MediaBridgeClient.calls) == 1
    call = _MediaBridgeClient.calls[0]
    assert call['phone'] == '+55 (81) 99999-9999'
    assert call['filename'] == 'boleto.pdf'
    assert call['mimetype'] == 'application/pdf'
    assert call['caption'] == 'boleto'
    assert call['data_base64']


def test_bridge_send_media_rejects_unsupported_type(monkeypatch):
    monkeypatch.setattr(main, 'WhatsAppClient', _MediaBridgeClient)
    client = _auth_client()
    response = client.post(
        '/bridge/send-media',
        data={'phone': '5581999999999'},
        files={'file': ('nota.txt', b'hello', 'text/plain')},
    )
    assert response.status_code == 400
    assert response.json()['ok'] is False


def test_bridge_send_media_rejects_oversize_file(monkeypatch):
    monkeypatch.setattr(main, 'WhatsAppClient', _MediaBridgeClient)
    client = _auth_client()
    blob = b'%PDF-' + b'0' * (10 * 1024 * 1024)
    response = client.post(
        '/bridge/send-media',
        data={'phone': '5581999999999'},
        files={'file': ('boleto.pdf', blob, 'application/pdf')},
    )
    assert response.status_code == 413


def test_bridge_send_media_passes_bridge_client_error(monkeypatch):
    monkeypatch.setattr(main, 'WhatsAppClient', _DisconnectedMediaBridgeClient)
    client = _auth_client()
    response = client.post(
        '/bridge/send-media',
        data={'phone': '5581999999999'},
        files={'file': ('boleto.pdf', b'%PDF-1.4', 'application/pdf')},
    )
    assert response.status_code == 409
    assert 'not connected' in response.json()['message']


def test_bridge_send_media_rejects_non_bridge_provider(monkeypatch):
    monkeypatch.setattr(main, 'WhatsAppClient', _EvolutionClient)
    client = _auth_client()
    response = client.post(
        '/bridge/send-media',
        data={'phone': '5581999999999'},
        files={'file': ('boleto.pdf', b'%PDF-1.4', 'application/pdf')},
    )
    assert response.status_code == 400


def test_openapi_lists_send_media():
    client = TestClient(main.app)
    schema = client.get('/openapi.json')
    assert schema.status_code == 200
    operation = schema.json()['paths']['/bridge/send-media']['post']
    assert 'multipart/form-data' in operation['requestBody']['content']


def test_bridge_routes_return_friendly_hint_on_bridge_down(monkeypatch):
    monkeypatch.setattr(main, 'WhatsAppClient', _FailingBridgeClient)
    client = TestClient(main.app)
    client.cookies.set('mass_sender_admin', main.APP_PASSWORD)

    response = client.get('/bridge/session')
    assert response.status_code == 502
    payload = response.json()
    assert payload['ok'] is False
    assert 'indisponível' in payload['message'].lower()
    assert 'npm start' in payload['hint']
