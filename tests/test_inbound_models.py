from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from database import Base
from models import Conversation, ConversationMessage, HandoffEvent


def test_create_conversation_and_related_records():
    engine = create_engine('sqlite:///:memory:', future=True)
    Session = sessionmaker(bind=engine, future=True)
    Base.metadata.create_all(engine)

    session = Session()
    conversation = Conversation(customer_phone='+5511999999999', status='ai_active')
    session.add(conversation)
    session.commit()
    session.refresh(conversation)

    message = ConversationMessage(
        conversation_id=conversation.id,
        wa_message_id='wamid.1',
        direction='inbound',
        sender_type='customer',
        message_text='Olá',
        raw_payload_excerpt='{"text":"Olá"}',
    )
    handoff = HandoffEvent(
        conversation_id=conversation.id,
        reason='purchase_intent',
        notified_phone='+5581888888888',
        status='created',
    )
    session.add_all([message, handoff])
    session.commit()

    assert conversation.id is not None
    assert message.id is not None
    assert handoff.id is not None


def test_conversation_customer_phone_is_unique():
    engine = create_engine('sqlite:///:memory:', future=True)
    Session = sessionmaker(bind=engine, future=True)
    Base.metadata.create_all(engine)

    session = Session()
    session.add(Conversation(customer_phone='+5511999999999', status='ai_active'))
    session.commit()

    session.add(Conversation(customer_phone='+5511999999999', status='ai_active'))

    try:
        session.commit()
        assert False, 'Expected IntegrityError'
    except IntegrityError:
        session.rollback()


def test_conversation_message_wa_message_id_is_unique():
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
            wa_message_id='wamid.dup',
            direction='inbound',
            sender_type='customer',
            message_text='Primeira',
        )
    )
    session.commit()

    session.add(
        ConversationMessage(
            conversation_id=conversation.id,
            wa_message_id='wamid.dup',
            direction='inbound',
            sender_type='customer',
            message_text='Segunda',
        )
    )

    try:
        session.commit()
        assert False, 'Expected IntegrityError'
    except IntegrityError:
        session.rollback()
