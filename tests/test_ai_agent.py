import asyncio

from services.ai_agent import AIAgent, AIAction


class _ReplyingClient:
    async def complete_json(self, *, messages, system_prompt, model_override=None):
        assert messages
        assert system_prompt
        return {
            'action': 'reply',
            'reply_text': 'Oi! Posso te ajudar com informações do produto.',
            'handoff_reason': '',
            'confidence': 0.92,
        }


class _HandoffClient:
    async def complete_json(self, *, messages, system_prompt, model_override=None):
        return {
            'action': 'handoff',
            'reply_text': '',
            'handoff_reason': 'purchase_intent',
            'confidence': 0.55,
        }


class _BrokenClient:
    async def complete_json(self, *, messages, system_prompt, model_override=None):
        raise RuntimeError('provider timeout')


class _EarlyHandoffClient:
    async def complete_json(self, *, messages, system_prompt, model_override=None):
        return {
            'action': 'handoff',
            'reply_text': '',
            'handoff_reason': 'model_handoff',
            'confidence': 0.9,
        }


class _UnexpectedCallClient:
    async def complete_json(self, *, messages, system_prompt, model_override=None):
        raise AssertionError('model should not be called for the first inbound reply')


def test_ai_agent_returns_reply_action():
    agent = AIAgent(client=_ReplyingClient())

    decision = asyncio.run(
        agent.decide_next_action(
            inbound_text='Quais sabores vocês têm?',
            conversation_history=[{'role': 'user', 'text': 'Olá'}],
            ai_consecutive_replies=0,
        )
    )

    assert decision.action == AIAction.REPLY
    assert 'ajudar' in decision.reply_text.lower()


def test_ai_agent_returns_handoff_on_provider_signal():
    agent = AIAgent(client=_HandoffClient())

    decision = asyncio.run(
        agent.decide_next_action(
            inbound_text='Quero fazer um pedido',
            conversation_history=[{'role': 'assistant', 'text': 'Olá! Tudo bem? Como posso te ajudar?'}],
            ai_consecutive_replies=0,
        )
    )

    assert decision.action == AIAction.HANDOFF
    assert decision.handoff_reason == 'purchase_intent'


def test_ai_agent_avoids_early_handoff_when_no_explicit_intent():
    agent = AIAgent(client=_EarlyHandoffClient())

    decision = asyncio.run(
        agent.decide_next_action(
            inbound_text='Oi, tudo bem?',
            conversation_history=[],
            ai_consecutive_replies=0,
        )
    )

    assert decision.action == AIAction.REPLY
    assert 'como posso te ajudar' in decision.reply_text.lower()


def test_ai_agent_forces_handoff_after_five_replies():
    agent = AIAgent(client=_ReplyingClient())

    decision = asyncio.run(
        agent.decide_next_action(
            inbound_text='Ainda tenho dúvida',
            conversation_history=[],
            ai_consecutive_replies=5,
        )
    )

    assert decision.action == AIAction.HANDOFF
    assert decision.handoff_reason == 'auto_reply_limit'


def test_ai_agent_falls_back_to_handoff_on_error():
    agent = AIAgent(client=_BrokenClient())

    decision = asyncio.run(
        agent.decide_next_action(
            inbound_text='Tem desconto?',
            conversation_history=[{'role': 'assistant', 'text': 'Olá! Tudo bem? Como posso te ajudar?'}],
            ai_consecutive_replies=0,
        )
    )

    assert decision.action == AIAction.HANDOFF
    assert decision.handoff_reason == 'ai_error'


def test_ai_agent_removes_invented_store_identity_without_business_name(monkeypatch):
    class _HallucinatedStoreClient:
        async def complete_json(self, *, messages, system_prompt, model_override=None):
            return {
                'action': 'reply',
                'reply_text': 'Oi! Tudo bem? Sou o assistente do Whitelabel Store. Como posso te ajudar hoje?',
                'handoff_reason': '',
                'confidence': 0.95,
            }

    monkeypatch.delenv('BUSINESS_NAME', raising=False)
    agent = AIAgent(client=_HallucinatedStoreClient())

    decision = asyncio.run(
        agent.decide_next_action(
            inbound_text='Oi',
            conversation_history=[],
            ai_consecutive_replies=0,
        )
    )

    assert decision.action == AIAction.REPLY
    assert 'whitelabel store' not in decision.reply_text.lower()
    assert 'assistente do' not in decision.reply_text.lower()


def test_ai_agent_allows_configured_business_name(monkeypatch):
    class _NamedStoreClient:
        async def complete_json(self, *, messages, system_prompt, model_override=None):
            return {
                'action': 'reply',
                'reply_text': 'Oi! Tudo bem? Sou o assistente da Loja Exemplo. Como posso te ajudar hoje?',
                'handoff_reason': '',
                'confidence': 0.91,
            }

    monkeypatch.setenv('BUSINESS_NAME', 'Loja Exemplo')
    agent = AIAgent(client=_NamedStoreClient())

    decision = asyncio.run(
        agent.decide_next_action(
            inbound_text='Oi',
            conversation_history=[],
            ai_consecutive_replies=0,
        )
    )

    assert decision.action == AIAction.REPLY
    assert 'loja exemplo' in decision.reply_text.lower()


def test_ai_agent_uses_fixed_welcome_message_on_first_reply(monkeypatch):
    monkeypatch.setenv('BUSINESS_NAME', 'Avil Tecidos e Aviamentos')
    agent = AIAgent(client=_UnexpectedCallClient())

    decision = asyncio.run(
        agent.decide_next_action(
            inbound_text='Oi',
            conversation_history=[],
            ai_consecutive_replies=0,
        )
    )

    assert decision.action == AIAction.REPLY
    assert (
        decision.reply_text
        == 'Olá! Tudo bem? Bem-vindo à Avil Tecidos e Aviamentos. Como posso te ajudar?'
    )
    assert decision.confidence == 1.0
