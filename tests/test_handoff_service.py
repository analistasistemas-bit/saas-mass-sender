from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models import Conversation, ConversationMessage, HandoffEvent
from services.handoff_service import perform_handoff


class _FakeClient:
    def __init__(self):
        self.sent = []

    async def send_text(self, phone_e164: str, text: str) -> None:
        self.sent.append((phone_e164, text))


def test_perform_handoff_sends_customer_and_human_messages(monkeypatch):
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
            message_text='Quero fazer um pedido',
        )
    )
    session.commit()

    fake_client = _FakeClient()
    monkeypatch.setenv('HUMAN_HANDOFF_PHONE', '+5581888888888')

    import asyncio

    asyncio.run(perform_handoff(session, conversation.id, 'purchase_intent', fake_client))

    session.refresh(conversation)
    events = session.query(HandoffEvent).all()

    assert conversation.status == 'waiting_human'
    assert len(events) == 1
    assert events[0].reason == 'purchase_intent'
    assert fake_client.sent[0][0] == '+5511999999999'
    assert fake_client.sent[0][1] == 'Vou passar seu atendimento para meu gerente.'
    assert fake_client.sent[1][0] == '+5581888888888'
    assert 'purchase_intent' in fake_client.sent[1][1]
