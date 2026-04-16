from __future__ import annotations

import os
import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from services.openrouter_client import OpenRouterClient


class AIAction(str, Enum):
    REPLY = 'reply'
    HANDOFF = 'handoff'


@dataclass
class AIDecision:
    action: AIAction
    reply_text: str
    handoff_reason: str
    confidence: float


class AIAgent:
    _fallback_reply = 'Perfeito. Me conta sua duvida que eu te ajudo por aqui.'
    _default_welcome = 'Olá! Tudo bem? Como posso te ajudar?'

    def __init__(self, client: Optional[OpenRouterClient] = None) -> None:
        self.client = client or OpenRouterClient()
        self.business_name = str(os.getenv('BUSINESS_NAME', '')).strip()

    async def decide_next_action(
        self,
        *,
        inbound_text: str,
        conversation_history: list[dict],
        ai_consecutive_replies: int,
        model: str | None = None,
        max_auto_replies: int = 5,
        system_prompt_override: str | None = None,
        welcome_message_override: str | None = None,
    ) -> AIDecision:
        if ai_consecutive_replies >= max_auto_replies:
            return AIDecision(
                action=AIAction.HANDOFF,
                reply_text='',
                handoff_reason='auto_reply_limit',
                confidence=1.0,
            )

        try:
            return await self.preview_decision(
                inbound_text=inbound_text,
                conversation_history=conversation_history,
                model=model,
                system_prompt_override=system_prompt_override,
                welcome_message_override=welcome_message_override,
            )
        except Exception:
            return AIDecision(
                action=AIAction.HANDOFF,
                reply_text='',
                handoff_reason='ai_error',
                confidence=0.0,
            )

    async def preview_decision(
        self,
        *,
        inbound_text: str,
        conversation_history: list[dict],
        model: str | None = None,
        system_prompt_override: str | None = None,
        welcome_message_override: str | None = None,
    ) -> AIDecision:
        if self._is_first_ai_reply(conversation_history):
            return AIDecision(
                action=AIAction.REPLY,
                reply_text=welcome_message_override or self._welcome_message(),
                handoff_reason='',
                confidence=1.0,
            )

        payload = await self.client.complete_json(
            messages=self._build_messages(inbound_text, conversation_history),
            system_prompt=system_prompt_override or self._system_prompt(),
            model_override=model,
        )
        decision = self._validate_payload(payload)
        if decision.action == AIAction.HANDOFF and decision.handoff_reason != 'auto_reply_limit':
            if not self._has_explicit_handoff_intent(inbound_text):
                return AIDecision(
                    action=AIAction.REPLY,
                    reply_text=self._fallback_reply,
                    handoff_reason='',
                    confidence=0.6,
                )
        return self._sanitize_decision(decision)

    def _is_first_ai_reply(self, conversation_history: list[dict]) -> bool:
        return not any(str(item.get('role')) == 'assistant' for item in conversation_history)

    def _welcome_message(self) -> str:
        if self.business_name:
            return f'Olá! Tudo bem? Bem-vindo à {self.business_name}. Como posso te ajudar?'
        return self._default_welcome

    def _build_messages(self, inbound_text: str, conversation_history: list[dict]) -> list[dict]:
        messages: list[dict] = []
        for item in conversation_history[-10:]:
            role = 'assistant' if str(item.get('role')) == 'assistant' else 'user'
            text = str(item.get('text') or '').strip()
            if text:
                messages.append({'role': role, 'content': text[:1000]})
        messages.append({'role': 'user', 'content': inbound_text[:1000]})
        return messages

    def _system_prompt(self) -> str:
        business_context = (
            f'Nome comercial configurado: {self.business_name}. Use apenas esse nome exato se precisar citar a empresa. '
            if self.business_name
            else 'Nenhum nome comercial foi configurado. Nao cite nome de loja, marca, empresa ou organizacao. '
            'Nao diga que voce e assistente de nenhuma loja. Fale de forma neutra.'
        )
        return (
            'Voce e um agente comercial de WhatsApp. '
            'Responda de forma humana, curta e natural. '
            'Nao invente dados. Nao negocie. Nao conclua pedido. '
            + business_context
            + ' '
            'Quando houver intencao explicita de compra, pedido, desconto ou solicitacao de fechamento, '
            'retorne action=handoff. '
            'Em saudacao e perguntas gerais, retorne action=reply. '
            'Responda sempre em JSON com os campos action, reply_text, handoff_reason e confidence.'
        )

    def _has_explicit_handoff_intent(self, inbound_text: str) -> bool:
        text = str(inbound_text or '').strip().lower()
        if not text:
            return False

        triggers = (
            'quero comprar',
            'fazer pedido',
            'fazer um pedido',
            'fechar pedido',
            'fechar compra',
            'desconto',
            'preco final',
            'valor final',
            'condicao de pagamento',
            'pode fechar',
            'quero fechar',
            'vamos fechar',
        )
        return any(trigger in text for trigger in triggers)

    def _validate_payload(self, payload: dict) -> AIDecision:
        action = str(payload.get('action') or '').strip().lower()
        handoff_reason = str(payload.get('handoff_reason') or '').strip()
        reply_text = str(payload.get('reply_text') or '').strip()

        try:
            confidence = float(payload.get('confidence') or 0.0)
        except Exception:
            confidence = 0.0

        if action == AIAction.HANDOFF.value:
            return AIDecision(
                action=AIAction.HANDOFF,
                reply_text='',
                handoff_reason=handoff_reason or 'model_handoff',
                confidence=confidence,
            )

        if action == AIAction.REPLY.value and reply_text:
            return AIDecision(
                action=AIAction.REPLY,
                reply_text=reply_text,
                handoff_reason='',
                confidence=confidence,
            )

        # Alguns modelos podem retornar action livre (ex: "greet_user") com texto válido.
        # Nestes casos tratamos como reply para evitar handoff indevido.
        if reply_text:
            return AIDecision(
                action=AIAction.REPLY,
                reply_text=reply_text,
                handoff_reason='',
                confidence=confidence,
            )

        return AIDecision(
            action=AIAction.HANDOFF,
            reply_text='',
            handoff_reason='invalid_ai_response',
            confidence=0.0,
        )

    def _sanitize_decision(self, decision: AIDecision) -> AIDecision:
        if decision.action != AIAction.REPLY:
            return decision

        reply_text = str(decision.reply_text or '').strip()
        if not reply_text:
            return decision

        if self.business_name:
            return decision

        lowered = reply_text.lower()
        suspicious_markers = (
            'sou o assistente',
            'sou a assistente',
            'da loja',
            'do store',
            'whitelabel store',
            'nossa loja',
            'minha loja',
        )
        if any(marker in lowered for marker in suspicious_markers):
            sanitized = re.sub(
                r'(?i)^oi[!\.\s]*tudo bem\??[^A-Za-z0-9]*',
                'Oi! Tudo bem? ',
                reply_text,
            ).strip()
            if sanitized == reply_text:
                sanitized = 'Oi! Tudo bem? Como posso te ajudar hoje?'
            else:
                sanitized = re.sub(
                    r'(?i)\bsou\s+[oa]\s+assistente\b.*?(?=(?:como posso|em que posso|posso te ajudar|$))',
                    '',
                    sanitized,
                ).strip(' -.,')
                if not sanitized:
                    sanitized = 'Oi! Tudo bem? Como posso te ajudar hoje?'
            return AIDecision(
                action=decision.action,
                reply_text=sanitized,
                handoff_reason=decision.handoff_reason,
                confidence=decision.confidence,
            )

        return decision
