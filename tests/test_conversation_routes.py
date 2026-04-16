from fastapi.testclient import TestClient
from sqlalchemy import delete

import main
from database import Base, SessionLocal, engine
from models import Conversation
from services.ai_agent import AIDecision, AIAction


def _authed_client():
    client = TestClient(main.app)
    client.cookies.set('mass_sender_admin', main.APP_PASSWORD)
    return client


def test_conversation_routes_require_auth():
    client = TestClient(main.app)
    response = client.get('/conversations')
    assert response.status_code == 401


def test_list_and_transition_conversation_routes():
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        customer_phone = '+5511888877777'
        db.execute(delete(Conversation).where(Conversation.customer_phone == customer_phone))
        db.commit()
        conversation = Conversation(customer_phone=customer_phone, status='ai_active')
        db.add(conversation)
        db.commit()
        db.refresh(conversation)
        conversation_id = conversation.id

    client = _authed_client()

    listing = client.get('/conversations')
    assert listing.status_code == 200
    assert listing.json()['items']

    handoff = client.post(f'/conversations/{conversation_id}/handoff', json={'reason': 'manual_review'})
    assert handoff.status_code == 200
    assert handoff.json()['ok'] is True

    closed = client.post(f'/conversations/{conversation_id}/close')
    assert closed.status_code == 200
    assert closed.json()['ok'] is True

    reopened = client.post(f'/conversations/{conversation_id}/reopen-ai')
    assert reopened.status_code == 200
    assert reopened.json()['ok'] is True


def test_inbound_ai_control_exposes_models(monkeypatch):
    monkeypatch.setenv('OPENROUTER_MODEL', 'google/gemini-3.1-flash-lite-preview')
    monkeypatch.setenv('OPENROUTER_MODELS', 'google/gemini-3.1-flash-lite-preview,openai/gpt-4.1-mini,minimax/minimax-m2.7')

    client = _authed_client()
    response = client.get('/inbound/ai-control')

    assert response.status_code == 200
    payload = response.json()
    assert payload['ok'] is True
    assert 'minimax/minimax-m2.7' in payload['available_models']


def test_inbound_ai_model_test_preview_does_not_change_selected_model(monkeypatch):
    class _FakeAgent:
        async def preview_decision(self, *, inbound_text, conversation_history, model=None):
            assert inbound_text == 'Teste de produto'
            assert model == 'minimax/minimax-m2.7'
            return AIDecision(
                action=AIAction.REPLY,
                reply_text='Resposta de preview',
                handoff_reason='',
                confidence=0.88,
            )

    monkeypatch.setenv('OPENROUTER_MODEL', 'google/gemini-3.1-flash-lite-preview')
    monkeypatch.setenv('OPENROUTER_MODELS', 'google/gemini-3.1-flash-lite-preview,openai/gpt-4.1-mini,minimax/minimax-m2.7')
    monkeypatch.setattr(main, 'AIAgent', _FakeAgent)

    client = _authed_client()
    client.post('/inbound/ai-model', json={'model': 'google/gemini-3.1-flash-lite-preview'})

    preview = client.post('/inbound/ai-model/test', json={'model': 'minimax/minimax-m2.7', 'prompt': 'Teste de produto'})
    assert preview.status_code == 200
    assert preview.json()['preview_text'] == 'Resposta de preview'
    assert preview.json()['model'] == 'minimax/minimax-m2.7'

    state = client.get('/inbound/ai-control')
    assert state.status_code == 200
    assert state.json()['selected_model'] == 'google/gemini-3.1-flash-lite-preview'


def test_inbound_ai_model_test_falls_back_to_raw_text(monkeypatch):
    class _BrokenAgent:
        async def preview_decision(self, *, inbound_text, conversation_history, model=None):
            raise ValueError('json inválido')

        def _build_messages(self, inbound_text, conversation_history):
            return [{'role': 'user', 'content': inbound_text}]

        def _system_prompt(self):
            return 'system prompt'

    class _RawClient:
        def __init__(self, *args, **kwargs):
            pass

        async def complete_text(self, *, messages, system_prompt, model_override=None):
            assert model_override == 'minimax/minimax-m2.7'
            assert messages
            assert system_prompt == 'system prompt'
            return 'Texto bruto do modelo'

    monkeypatch.setenv('OPENROUTER_MODEL', 'google/gemini-3.1-flash-lite-preview')
    monkeypatch.setenv('OPENROUTER_MODELS', 'google/gemini-3.1-flash-lite-preview,minimax/minimax-m2.7')
    monkeypatch.setattr(main, 'AIAgent', _BrokenAgent)
    monkeypatch.setattr(main, 'OpenRouterClient', _RawClient)

    client = _authed_client()
    preview = client.post('/inbound/ai-model/test', json={'model': 'minimax/minimax-m2.7', 'prompt': 'Teste bruto'})

    assert preview.status_code == 200
    payload = preview.json()
    assert payload['ok'] is True
    assert payload['action'] == 'raw_text'
    assert payload['preview_text'] == 'Texto bruto do modelo'


def test_agent_settings_test_route_uses_conversation_history_and_reply_count(monkeypatch):
    class _FakeSimulation:
        def __init__(self):
            self.calls = []

        async def simulate(
            self,
            db,
            *,
            customer_message,
            conversation_history=None,
            ai_consecutive_replies=0,
            model_override=None,
        ):
            self.calls.append(
                {
                    'customer_message': customer_message,
                    'conversation_history': conversation_history,
                    'ai_consecutive_replies': ai_consecutive_replies,
                    'model_override': model_override,
                }
            )
            return type(
                'Simulation',
                (),
                {
                    'decision': AIDecision(
                        action=AIAction.REPLY,
                        reply_text='Resposta contextual',
                        handoff_reason='',
                        confidence=0.77,
                    ),
                    'source': 'manual',
                    'matched_product': {'name': 'Tricoline Floral'},
                    'elapsed_ms': 12,
                },
            )()

    fake = _FakeSimulation()
    monkeypatch.setattr(main, 'inbound_ai_service', fake)

    client = _authed_client()
    response = client.post(
        '/agent-settings/test',
        json={
            'customer_message': 'Quais produtos vc tem pra vender?',
            'model': 'qwen/qwen3.5-flash-02-23',
            'conversation_history': [
                {'role': 'user', 'text': 'Oi'},
                {'role': 'assistant', 'text': 'Olá! Tudo bem? Bem-vindo à Avil Tecidos e Aviamentos. Como posso te ajudar?'},
            ],
            'ai_consecutive_replies': 1,
        },
    )

    assert response.status_code == 200
    assert response.json()['preview_text'] == 'Resposta contextual'
    assert fake.calls == [
        {
            'customer_message': 'Quais produtos vc tem pra vender?',
            'conversation_history': [
                {'role': 'user', 'text': 'Oi'},
                {'role': 'assistant', 'text': 'Olá! Tudo bem? Bem-vindo à Avil Tecidos e Aviamentos. Como posso te ajudar?'},
            ],
            'ai_consecutive_replies': 1,
            'model_override': 'qwen/qwen3.5-flash-02-23',
        }
    ]


def test_agent_settings_test_route_uses_configured_handoff_message(monkeypatch):
    class _FakeSimulation:
        async def simulate(
            self,
            db,
            *,
            customer_message,
            conversation_history=None,
            ai_consecutive_replies=0,
            model_override=None,
        ):
            return type(
                'Simulation',
                (),
                {
                    'decision': AIDecision(
                        action=AIAction.HANDOFF,
                        reply_text='',
                        handoff_reason='purchase_intent',
                        confidence=1.0,
                    ),
                    'source': 'none',
                    'matched_product': None,
                    'elapsed_ms': 9,
                },
            )()

    class _FakeSettings:
        handoff_message = 'Vou passar seu atendimento para meu gerente. Clique no link https://api.whatsapp.com/send?phone=5581996125349'

    monkeypatch.setattr(main, 'inbound_ai_service', _FakeSimulation())
    monkeypatch.setattr(main, 'get_agent_settings', lambda db: _FakeSettings())

    client = _authed_client()
    response = client.post(
        '/agent-settings/test',
        json={
            'customer_message': 'Quero fechar um pedido',
            'model': 'qwen/qwen3.5-flash-02-23',
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload['action'] == 'handoff'
    assert payload['preview_text'] == _FakeSettings.handoff_message
