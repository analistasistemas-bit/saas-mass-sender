from fastapi.testclient import TestClient
from uuid import uuid4

import main


class _FakeInboundEngine:
    def __init__(self):
        self.enqueued = []

    async def enqueue_conversation(self, conversation_id: int) -> None:
        self.enqueued.append(conversation_id)


def _payload(wa_message_id: str = 'wamid.1') -> dict:
    return {
        'wa_message_id': wa_message_id,
        'from_phone': '+55 11 99999-9999',
        'to_phone': '+55 81 98888-8888',
        'text': 'Olá, preciso de ajuda',
        'timestamp': '2026-03-29T15:00:00Z',
        'push_name': 'Maria',
        'message_type': 'chat',
        'from_me': False,
        'raw_excerpt': '{"text":"Olá, preciso de ajuda"}',
    }


def test_inbound_webhook_rejects_missing_or_invalid_token(monkeypatch):
    monkeypatch.setattr(main, 'INBOUND_WEBHOOK_TOKEN', 'secret-token', raising=False)
    client = TestClient(main.app)

    response = client.post('/webhooks/whatsapp/inbound', json=_payload())
    assert response.status_code == 401

    response = client.post('/webhooks/whatsapp/inbound', json=_payload(), headers={'x-inbound-token': 'wrong'})
    assert response.status_code == 401


def test_inbound_webhook_accepts_payload_and_is_idempotent(monkeypatch):
    fake_engine = _FakeInboundEngine()
    wa_message_id = f'wamid.{uuid4()}'
    monkeypatch.setattr(main, 'INBOUND_WEBHOOK_TOKEN', 'secret-token', raising=False)
    monkeypatch.setattr(main, 'inbound_engine', fake_engine, raising=False)

    client = TestClient(main.app)

    response = client.post('/webhooks/whatsapp/inbound', json=_payload(wa_message_id), headers={'x-inbound-token': 'secret-token'})
    assert response.status_code == 200
    assert response.json() == {'ok': True, 'accepted': True, 'duplicate': False}
    assert len(fake_engine.enqueued) == 1

    second = client.post('/webhooks/whatsapp/inbound', json=_payload(wa_message_id), headers={'x-inbound-token': 'secret-token'})
    assert second.status_code == 200
    assert second.json() == {'ok': True, 'accepted': True, 'duplicate': True}
    assert len(fake_engine.enqueued) == 1


def test_inbound_webhook_ignores_from_me_messages(monkeypatch):
    fake_engine = _FakeInboundEngine()
    payload = _payload('wamid.fromme')
    payload['from_me'] = True

    monkeypatch.setattr(main, 'INBOUND_WEBHOOK_TOKEN', 'secret-token', raising=False)
    monkeypatch.setattr(main, 'inbound_engine', fake_engine, raising=False)

    client = TestClient(main.app)
    response = client.post('/webhooks/whatsapp/inbound', json=payload, headers={'x-inbound-token': 'secret-token'})

    assert response.status_code == 200
    assert response.json() == {'ok': True, 'accepted': False, 'duplicate': False}
    assert fake_engine.enqueued == []
