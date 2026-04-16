import asyncio

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models import Conversation, ConversationMessage
from services.ai_agent import AIDecision, AIAction
from services import inbound_engine


class _ReplyingAgent:
    def __init__(self, text='Posso te ajudar com isso.'):
        self.text = text
        self.calls = []

    async def decide_next_action(self, *, inbound_text, conversation_history, ai_consecutive_replies):
        self.calls.append((inbound_text, conversation_history, ai_consecutive_replies))
        return AIDecision(action=AIAction.REPLY, reply_text=self.text, handoff_reason='', confidence=0.9)


class _HandoffAgent:
    async def decide_next_action(self, *, inbound_text, conversation_history, ai_consecutive_replies):
        return AIDecision(action=AIAction.HANDOFF, reply_text='', handoff_reason='purchase_intent', confidence=0.5)


class _FakeClient:
    def __init__(self):
        self.sent = []

    async def send_text(self, phone_e164: str, text: str):
        self.sent.append((phone_e164, text))


async def _fake_handoff(db, conversation_id, reason, client):
    conversation = db.get(Conversation, conversation_id)
    conversation.status = 'waiting_human'
    db.add(conversation)
    db.commit()
    await client.send_text(conversation.customer_phone, 'Vou passar seu atendimento para meu gerente.')


def test_process_conversation_replies_and_persists_outbound(monkeypatch):
    engine = create_engine('sqlite:///:memory:', future=True)
    Session = sessionmaker(bind=engine, future=True)
    Base.metadata.create_all(engine)

    session = Session()
    conversation = Conversation(customer_phone='+5511999999999', status='ai_active')
    session.add(conversation)
    session.commit()
    session.refresh(conversation)
    session.add(
        ConversationMessage(
            conversation_id=conversation.id,
            wa_message_id='wamid.1',
            direction='inbound',
            sender_type='customer',
            message_text='Quais sabores vocês têm?',
        )
    )
    session.commit()

    monkeypatch.setattr(inbound_engine, 'SessionLocal', Session)

    worker = inbound_engine.InboundEngine()
    worker.agent = _ReplyingAgent()
    worker.client = _FakeClient()
    monkeypatch.setattr(inbound_engine, 'perform_handoff', _fake_handoff)
    monkeypatch.setattr(inbound_engine.random, 'uniform', lambda _a, _b: 0)

    async def fake_sleep(_seconds):
        return None

    monkeypatch.setattr(inbound_engine.asyncio, 'sleep', fake_sleep)
    asyncio.run(worker._process_conversation(conversation.id))

    check = Session()
    saved = check.get(Conversation, conversation.id)
    messages = check.query(ConversationMessage).filter(ConversationMessage.conversation_id == conversation.id).all()

    assert saved.ai_consecutive_replies == 1
    assert len(messages) == 2
    assert messages[-1].direction == 'outbound'
    assert worker.client.sent[0][0] == '+5511999999999'


def test_process_conversation_handoff_when_waiting_human(monkeypatch):
    engine = create_engine('sqlite:///:memory:', future=True)
    Session = sessionmaker(bind=engine, future=True)
    Base.metadata.create_all(engine)

    session = Session()
    conversation = Conversation(customer_phone='+5511999999999', status='waiting_human')
    session.add(conversation)
    session.commit()
    session.refresh(conversation)
    session.add(
        ConversationMessage(
            conversation_id=conversation.id,
            wa_message_id='wamid.2',
            direction='inbound',
            sender_type='customer',
            message_text='Oi?',
        )
    )
    session.commit()

    monkeypatch.setattr(inbound_engine, 'SessionLocal', Session)
    worker = inbound_engine.InboundEngine()
    worker.agent = _ReplyingAgent()
    worker.client = _FakeClient()
    monkeypatch.setattr(inbound_engine, 'perform_handoff', _fake_handoff)

    asyncio.run(worker._process_conversation(conversation.id))

    check = Session()
    messages = check.query(ConversationMessage).filter(ConversationMessage.conversation_id == conversation.id).all()
    assert len(messages) == 1
    assert worker.client.sent == []


def test_process_conversation_forces_handoff_after_limit(monkeypatch):
    engine = create_engine('sqlite:///:memory:', future=True)
    Session = sessionmaker(bind=engine, future=True)
    Base.metadata.create_all(engine)

    session = Session()
    conversation = Conversation(customer_phone='+5511999999999', status='ai_active', ai_consecutive_replies=5)
    session.add(conversation)
    session.commit()
    session.refresh(conversation)
    session.add(
        ConversationMessage(
            conversation_id=conversation.id,
            wa_message_id='wamid.3',
            direction='inbound',
            sender_type='customer',
            message_text='Tenho outra dúvida',
        )
    )
    session.commit()

    monkeypatch.setattr(inbound_engine, 'SessionLocal', Session)
    worker = inbound_engine.InboundEngine()
    worker.agent = _ReplyingAgent()
    worker.client = _FakeClient()
    monkeypatch.setattr(inbound_engine, 'perform_handoff', _fake_handoff)

    asyncio.run(worker._process_conversation(conversation.id))

    check = Session()
    saved = check.get(Conversation, conversation.id)
    assert saved.status == 'waiting_human'
    assert worker.client.sent[0][1] == 'Vou passar seu atendimento para meu gerente.'


def test_process_conversation_does_not_reply_twice_to_same_inbound(monkeypatch):
    engine = create_engine('sqlite:///:memory:', future=True)
    Session = sessionmaker(bind=engine, future=True)
    Base.metadata.create_all(engine)

    session = Session()
    conversation = Conversation(customer_phone='+5511999999999', status='ai_active')
    session.add(conversation)
    session.commit()
    session.refresh(conversation)
    session.add(
        ConversationMessage(
            conversation_id=conversation.id,
            wa_message_id='wamid.same',
            direction='inbound',
            sender_type='customer',
            message_text='Oi, quero saber mais',
        )
    )
    session.commit()

    monkeypatch.setattr(inbound_engine, 'SessionLocal', Session)

    worker = inbound_engine.InboundEngine()
    worker.agent = _ReplyingAgent()
    worker.client = _FakeClient()
    monkeypatch.setattr(inbound_engine, 'perform_handoff', _fake_handoff)
    monkeypatch.setattr(inbound_engine.random, 'uniform', lambda _a, _b: 0)

    async def fake_sleep(_seconds):
        return None

    monkeypatch.setattr(inbound_engine.asyncio, 'sleep', fake_sleep)

    asyncio.run(worker._process_conversation(conversation.id))
    asyncio.run(worker._process_conversation(conversation.id))

    check = Session()
    messages = check.query(ConversationMessage).filter(ConversationMessage.conversation_id == conversation.id).all()

    assert len(messages) == 2
    assert len(worker.client.sent) == 1
