from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models import Conversation, ConversationMessage
from services.conversation_service import (
    append_outbound_message,
    close_conversation,
    get_or_create_conversation,
    mark_waiting_human,
    save_inbound_message,
)


def test_get_or_create_conversation_reuses_phone():
    engine = create_engine('sqlite:///:memory:', future=True)
    Session = sessionmaker(bind=engine, future=True)
    Base.metadata.create_all(engine)

    session = Session()
    first = get_or_create_conversation(session, '+5511999999999')
    second = get_or_create_conversation(session, '+5511999999999')

    assert first.id == second.id
    assert first.status == 'ai_active'


def test_save_inbound_message_creates_message_and_updates_timestamp():
    engine = create_engine('sqlite:///:memory:', future=True)
    Session = sessionmaker(bind=engine, future=True)
    Base.metadata.create_all(engine)

    session = Session()
    conversation, duplicate = save_inbound_message(
        session,
        wa_message_id='wamid.1',
        from_phone='+5511999999999',
        text='Olá',
        raw_payload_excerpt='{"text":"Olá"}',
        push_name='Maria',
        received_at=datetime(2026, 3, 29, 15, 0, tzinfo=timezone.utc),
    )

    saved_messages = session.query(ConversationMessage).all()
    assert duplicate is False
    assert conversation.customer_phone == '+5511999999999'
    assert conversation.last_message_at is not None
    assert len(saved_messages) == 1
    assert saved_messages[0].sender_type == 'customer'


def test_save_inbound_message_is_idempotent_by_wa_message_id():
    engine = create_engine('sqlite:///:memory:', future=True)
    Session = sessionmaker(bind=engine, future=True)
    Base.metadata.create_all(engine)

    session = Session()
    save_inbound_message(
        session,
        wa_message_id='wamid.same',
        from_phone='+5511999999999',
        text='Olá',
        raw_payload_excerpt='{}',
    )
    _conversation, duplicate = save_inbound_message(
        session,
        wa_message_id='wamid.same',
        from_phone='+5511999999999',
        text='Olá de novo',
        raw_payload_excerpt='{}',
    )

    assert duplicate is True
    assert session.query(ConversationMessage).count() == 1


def test_mark_waiting_human_and_close_conversation():
    engine = create_engine('sqlite:///:memory:', future=True)
    Session = sessionmaker(bind=engine, future=True)
    Base.metadata.create_all(engine)

    session = Session()
    conversation = get_or_create_conversation(session, '+5511999999999')

    mark_waiting_human(session, conversation.id, 'purchase_intent', '+5581888888888')
    session.refresh(conversation)
    assert conversation.status == 'waiting_human'
    assert conversation.handoff_target_phone == '+5581888888888'

    close_conversation(session, conversation.id)
    session.refresh(conversation)
    assert conversation.status == 'closed'


def test_append_outbound_message_persists_ai_message():
    engine = create_engine('sqlite:///:memory:', future=True)
    Session = sessionmaker(bind=engine, future=True)
    Base.metadata.create_all(engine)

    session = Session()
    conversation = get_or_create_conversation(session, '+5511999999999')

    message = append_outbound_message(session, conversation_id=conversation.id, text='Como posso ajudar?', sender_type='ai')

    assert message.direction == 'outbound'
    assert message.sender_type == 'ai'
    assert session.query(ConversationMessage).count() == 1


def test_save_inbound_reopens_ai_when_conversation_was_closed():
    engine = create_engine('sqlite:///:memory:', future=True)
    Session = sessionmaker(bind=engine, future=True)
    Base.metadata.create_all(engine)

    session = Session()
    conversation = get_or_create_conversation(session, '+5511999999999')
    close_conversation(session, conversation.id)
    session.refresh(conversation)
    assert conversation.status == 'closed'

    updated, duplicate = save_inbound_message(
        session,
        wa_message_id='wamid.reopen.1',
        from_phone='+5511999999999',
        text='voltei, pode me ajudar?',
        raw_payload_excerpt='{}',
    )

    assert duplicate is False
    assert updated.status == 'ai_active'
