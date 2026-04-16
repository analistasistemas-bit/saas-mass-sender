from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from models import Conversation, ConversationMessage, HandoffEvent
from services.agent_settings_service import get_agent_settings


def _build_handoff_summary(conversation: Conversation, reason: str, messages: list[ConversationMessage]) -> str:
    lines = [
        'Novo handoff de atendimento.',
        f'Cliente: {conversation.customer_phone}',
        f'Motivo: {reason}',
        'Ultimas mensagens:',
    ]
    for item in messages[-5:]:
        lines.append(f'- {item.sender_type}: {item.message_text}')
    return '\n'.join(lines)


async def perform_handoff(db: Session, conversation_id: int, reason: str, client) -> None:
    conversation = db.get(Conversation, conversation_id)
    if conversation is None:
        raise ValueError('Conversa não encontrada')

    settings = get_agent_settings(db)
    human_phone = str(settings.human_whatsapp_number or '').strip()
    customer_message = str(settings.handoff_message or 'Vou passar seu atendimento para meu gerente.').strip()
    messages = db.scalars(
        select(ConversationMessage)
        .where(ConversationMessage.conversation_id == conversation_id)
        .order_by(ConversationMessage.created_at.asc(), ConversationMessage.id.asc())
    ).all()

    handoff_status = 'notified'
    try:
        await client.send_text(conversation.customer_phone, customer_message)
    except Exception:
        handoff_status = 'notify_failed'

    if human_phone:
        try:
            await client.send_text(human_phone, _build_handoff_summary(conversation, reason, messages))
        except Exception:
            handoff_status = 'notify_failed'
    else:
        handoff_status = 'notify_failed'

    conversation.status = 'waiting_human'
    conversation.handoff_target_phone = human_phone or None
    latest_inbound = db.scalar(
        select(ConversationMessage.wa_message_id)
        .where(
            ConversationMessage.conversation_id == conversation_id,
            ConversationMessage.direction == 'inbound',
        )
        .order_by(ConversationMessage.created_at.desc(), ConversationMessage.id.desc())
        .limit(1)
    )
    conversation.last_processed_wa_message_id = latest_inbound
    db.add(conversation)
    db.add(
        HandoffEvent(
            conversation_id=conversation_id,
            reason=reason,
            notified_phone=human_phone or None,
            status=handoff_status,
        )
    )
    db.commit()
