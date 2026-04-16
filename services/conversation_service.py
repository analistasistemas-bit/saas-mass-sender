from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from models import Conversation, ConversationMessage, HandoffEvent
from utils.phone import normalize_br_phone


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def normalize_inbound_phone(raw_phone: str) -> str:
    ok, normalized, error = normalize_br_phone(raw_phone or '')
    if not ok or not normalized:
        raise ValueError(error or 'Telefone inválido')
    return normalized


def get_or_create_conversation(db: Session, customer_phone: str) -> Conversation:
    conversation = db.scalar(select(Conversation).where(Conversation.customer_phone == customer_phone))
    if conversation is not None:
        return conversation

    conversation = Conversation(customer_phone=customer_phone, status='ai_active')
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return conversation


def save_inbound_message(
    db: Session,
    *,
    wa_message_id: str,
    from_phone: str,
    text: str,
    raw_payload_excerpt: str,
    push_name: str | None = None,
    received_at: Optional[datetime] = None,
) -> tuple[Conversation, bool]:
    existing = db.scalar(select(ConversationMessage).where(ConversationMessage.wa_message_id == wa_message_id))
    if existing is not None:
        conversation = db.get(Conversation, existing.conversation_id)
        if conversation is None:
            raise ValueError('Conversa não encontrada para mensagem existente')
        return conversation, True

    normalized_phone = normalize_inbound_phone(from_phone)
    conversation = get_or_create_conversation(db, normalized_phone)
    timestamp = received_at or now_utc()
    excerpt = raw_payload_excerpt
    if not excerpt:
        excerpt = json.dumps({'push_name': push_name or '', 'text': text[:200]}, ensure_ascii=True)

    message = ConversationMessage(
        conversation_id=conversation.id,
        wa_message_id=wa_message_id,
        direction='inbound',
        sender_type='customer',
        message_text=text.strip(),
        raw_payload_excerpt=excerpt[:2000],
        created_at=timestamp,
    )
    if conversation.status == 'closed':
        conversation.status = 'ai_active'
        conversation.ai_consecutive_replies = 0
        conversation.handoff_target_phone = None
    conversation.last_message_at = timestamp
    db.add(conversation)
    db.add(message)
    db.commit()
    db.refresh(conversation)
    return conversation, False


def append_outbound_message(db: Session, *, conversation_id: int, text: str, sender_type: str) -> ConversationMessage:
    conversation = db.get(Conversation, conversation_id)
    if conversation is None:
        raise ValueError('Conversa não encontrada')

    message = ConversationMessage(
        conversation_id=conversation_id,
        wa_message_id=f'outbound:{conversation_id}:{int(now_utc().timestamp() * 1000000)}',
        direction='outbound',
        sender_type=sender_type,
        message_text=text.strip(),
    )
    conversation.last_message_at = now_utc()
    db.add(conversation)
    db.add(message)
    db.commit()
    db.refresh(message)
    return message


def mark_waiting_human(db: Session, conversation_id: int, reason: str, notified_phone: str | None) -> None:
    conversation = db.get(Conversation, conversation_id)
    if conversation is None:
        raise ValueError('Conversa não encontrada')

    conversation.status = 'waiting_human'
    conversation.handoff_target_phone = notified_phone
    db.add(conversation)
    db.add(
        HandoffEvent(
            conversation_id=conversation_id,
            reason=reason,
            notified_phone=notified_phone,
            status='created',
        )
    )
    db.commit()


def reopen_ai(db: Session, conversation_id: int) -> None:
    conversation = db.get(Conversation, conversation_id)
    if conversation is None:
        raise ValueError('Conversa não encontrada')
    conversation.status = 'ai_active'
    conversation.ai_consecutive_replies = 0
    db.add(conversation)
    db.commit()


def close_conversation(db: Session, conversation_id: int) -> None:
    conversation = db.get(Conversation, conversation_id)
    if conversation is None:
        raise ValueError('Conversa não encontrada')
    conversation.status = 'closed'
    db.add(conversation)
    db.commit()
