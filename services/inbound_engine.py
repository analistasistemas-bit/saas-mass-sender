from __future__ import annotations

import asyncio
import random
import traceback
from collections import deque

from sqlalchemy import select

from database import SessionLocal
from models import Conversation, ConversationMessage
from services.agent_settings_service import get_agent_settings
from services.ai_agent import AIAction
from services.conversation_service import append_outbound_message
from services.handoff_service import perform_handoff
from services.inbound_ai_service import InboundAIService
from services.whatsapp import WhatsAppClient


class InboundEngine:
    def __init__(self) -> None:
        self._locks: set[int] = set()
        self._queue: deque[int] = deque()
        self._worker_task: asyncio.Task | None = None
        self._stop = False
        self._event = asyncio.Event()
        self.agent = InboundAIService()
        self.client = WhatsAppClient()

    async def start(self) -> None:
        if self._worker_task is None or self._worker_task.done():
            self._stop = False
            self._worker_task = asyncio.create_task(self.run_forever())

    async def stop(self) -> None:
        self._stop = True
        task = self._worker_task
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def enqueue_conversation(self, conversation_id: int) -> None:
        if self._worker_task is None or self._worker_task.done():
            await self.start()
        self._queue.append(conversation_id)
        self._event.set()

    async def process_conversation_now(self, conversation_id: int) -> None:
        if conversation_id in self._locks:
            return
        self._locks.add(conversation_id)
        try:
            await self._process_conversation(conversation_id)
        finally:
            self._locks.discard(conversation_id)

    async def run_forever(self) -> None:
        while not self._stop:
            try:
                if not self._queue:
                    await self._event.wait()
                    self._event.clear()
                    continue
                conversation_id = self._queue.popleft()
                if conversation_id in self._locks:
                    continue
                self._locks.add(conversation_id)
                try:
                    await self._process_conversation(conversation_id)
                finally:
                    self._locks.discard(conversation_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                traceback.print_exc()
                await asyncio.sleep(0.5)

    async def _process_conversation(self, conversation_id: int) -> None:
        with SessionLocal() as db:
            settings = get_agent_settings(db)
            if not settings.inbound_ai_enabled:
                return
            conversation = db.get(Conversation, conversation_id)
            if conversation is None:
                return
            if conversation.status in {'waiting_human', 'closed'}:
                return
            if int(conversation.ai_consecutive_replies or 0) >= int(settings.max_auto_replies_per_conversation or 5):
                await perform_handoff(db, conversation_id, 'auto_reply_limit', self.client)
                return

            inbound_messages = db.scalars(
                select(ConversationMessage)
                .where(
                    ConversationMessage.conversation_id == conversation_id,
                    ConversationMessage.direction == 'inbound',
                )
                .order_by(ConversationMessage.created_at.asc(), ConversationMessage.id.asc())
            ).all()
            if not inbound_messages:
                return

            latest_inbound = inbound_messages[-1]
            if conversation.last_processed_wa_message_id == latest_inbound.wa_message_id:
                return

            conversation_history = self._build_history(
                db.scalars(
                    select(ConversationMessage)
                    .where(ConversationMessage.conversation_id == conversation_id)
                    .order_by(ConversationMessage.created_at.asc(), ConversationMessage.id.asc())
                ).all()
            )
            consecutive_replies = int(conversation.ai_consecutive_replies or 0)
            if hasattr(self.agent, 'simulate'):
                simulation = await self.agent.simulate(
                    db,
                    customer_message=latest_inbound.message_text,
                    conversation_history=conversation_history,
                    ai_consecutive_replies=consecutive_replies,
                    model_override=settings.primary_model,
                )
                decision = simulation.decision
            else:
                decision = await self.agent.decide_next_action(
                    inbound_text=latest_inbound.message_text,
                    conversation_history=conversation_history,
                    ai_consecutive_replies=consecutive_replies,
                )

        if decision.action == AIAction.HANDOFF:
            with SessionLocal() as db:
                await perform_handoff(db, conversation_id, decision.handoff_reason, self.client)
            return

        await asyncio.sleep(
            random.uniform(
                max(0, int(settings.response_delay_min_ms or 0)) / 1000,
                max(int(settings.response_delay_min_ms or 0), int(settings.response_delay_max_ms or 0)) / 1000,
            )
        )

        with SessionLocal() as db:
            conversation = db.get(Conversation, conversation_id)
            if conversation is None or conversation.status != 'ai_active':
                return
            await self.client.send_text(conversation.customer_phone, decision.reply_text)
            append_outbound_message(db, conversation_id=conversation_id, text=decision.reply_text, sender_type='ai')
            conversation.ai_consecutive_replies = int(conversation.ai_consecutive_replies or 0) + 1
            conversation.last_processed_wa_message_id = latest_inbound.wa_message_id
            db.add(conversation)
            db.commit()

    def _build_history(self, messages: list[ConversationMessage]) -> list[dict]:
        history: list[dict] = []
        for item in messages[-10:]:
            role = 'assistant' if item.direction == 'outbound' else 'user'
            history.append({'role': role, 'text': item.message_text})
        return history
