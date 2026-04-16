from __future__ import annotations

import time
from dataclasses import dataclass

from sqlalchemy.orm import Session

from services.agent_settings_service import get_agent_settings
from services.ai_agent import AIAction, AIAgent, AIDecision
from services.knowledge_service import KnowledgeService
from services.openrouter_client import OpenRouterClient


@dataclass
class InboundAISimulation:
    decision: AIDecision
    source: str
    matched_product: dict | None
    answer_context: str
    confidence_hint: float
    elapsed_ms: int


class InboundAIService:
    def __init__(self, *, knowledge_service: KnowledgeService | None = None, agent: AIAgent | None = None) -> None:
        self.knowledge_service = knowledge_service or KnowledgeService()
        self.agent = agent or AIAgent(client=OpenRouterClient())

    async def simulate(
        self,
        db: Session,
        *,
        customer_message: str,
        conversation_history: list[dict] | None = None,
        ai_consecutive_replies: int = 0,
        model_override: str | None = None,
    ) -> InboundAISimulation:
        settings = get_agent_settings(db)
        started = time.perf_counter()
        knowledge = self.knowledge_service.resolve(db, customer_message=customer_message)
        decision = await self.agent.decide_next_action(
            inbound_text=customer_message,
            conversation_history=conversation_history or [],
            ai_consecutive_replies=ai_consecutive_replies,
            model=model_override or settings.primary_model,
            max_auto_replies=settings.max_auto_replies_per_conversation,
            system_prompt_override=self._build_prompt(settings, knowledge),
            welcome_message_override=self._welcome_message(settings.business_name),
        )

        if self._human_request(customer_message) and settings.handoff_on_human_request and settings.handoff_enabled:
            decision = AIDecision(
                action=AIAction.HANDOFF,
                reply_text='',
                handoff_reason='human_requested',
                confidence=1.0,
            )

        if (
            decision.action == AIAction.REPLY
            and settings.handoff_on_low_confidence
            and settings.handoff_enabled
            and float(decision.confidence or 0.0) < 0.35
        ):
            decision = AIDecision(
                action=AIAction.HANDOFF,
                reply_text='',
                handoff_reason='low_confidence',
                confidence=decision.confidence,
            )

        if decision.action == AIAction.HANDOFF and not settings.handoff_enabled:
            decision = AIDecision(
                action=AIAction.REPLY,
                reply_text='Posso te ajudar melhor se você me contar um pouco mais do que precisa.',
                handoff_reason='',
                confidence=0.45,
            )

        return InboundAISimulation(
            decision=decision,
            source=str(knowledge.get('source') or 'none'),
            matched_product=knowledge.get('matched_product'),
            answer_context=str(knowledge.get('answer_context') or ''),
            confidence_hint=float(knowledge.get('confidence_hint') or 0.0),
            elapsed_ms=int((time.perf_counter() - started) * 1000),
        )

    def _welcome_message(self, business_name: str) -> str:
        normalized = str(business_name or '').strip()
        if normalized:
            return f'Olá! Tudo bem? Bem-vindo à {normalized}. Como posso te ajudar?'
        return 'Olá! Tudo bem? Como posso te ajudar?'

    def _human_request(self, customer_message: str) -> bool:
        lowered = str(customer_message or '').strip().lower()
        return any(
            item in lowered
            for item in ('falar com humano', 'falar com atendente', 'quero um humano', 'quero falar com gerente')
        )

    def _build_prompt(self, settings, knowledge: dict) -> str:
        capabilities = []
        if settings.can_answer_price:
            capabilities.append('pode informar preço quando houver fonte confiável')
        if settings.can_answer_stock:
            capabilities.append('pode informar estoque quando houver fonte confiável')
        if settings.can_answer_description:
            capabilities.append('pode explicar descrição de produto')
        if settings.can_suggest_similar_products:
            capabilities.append('pode sugerir produtos similares')
        if not settings.can_negotiate_discount:
            capabilities.append('não pode negociar desconto')
        if not settings.can_close_order:
            capabilities.append('não pode concluir pedido')

        handoff_rules = []
        if settings.handoff_on_order_intent:
            handoff_rules.append('handoff quando houver intenção de compra ou pedido')
        if settings.handoff_on_low_confidence:
            handoff_rules.append('handoff quando a confiança estiver baixa')
        if settings.handoff_on_human_request:
            handoff_rules.append('handoff quando o cliente pedir humano')

        return (
            f"Você é {settings.agent_name or 'o agente comercial'} da empresa {settings.business_name or 'configurada no sistema'}. "
            f"Tom: {settings.tone}. Estilo: {settings.style}. Proatividade: {settings.proactivity_level}. "
            f"Use emojis: {'sim' if settings.use_emojis else 'não'}. "
            f"Limite aproximado da resposta: {settings.max_response_length} caracteres. "
            f"Instruções adicionais: {settings.personality_instructions or 'nenhuma'}. "
            f"Capacidades: {', '.join(capabilities) or 'respostas gerais curtas'}. "
            f"Regras de handoff: {', '.join(handoff_rules) or 'sem handoff automático'}. "
            f"Fonte consultada: {knowledge.get('source') or 'nenhuma'}. "
            f"Contexto: {knowledge.get('answer_context') or 'nenhum contexto encontrado; peça mais detalhes ao cliente.'} "
            "Não invente dados. Não negocie. Não conclua pedidos. "
            "Se a informação estiver ambígua, peça mais detalhes. "
            "Responda sempre em JSON com action, reply_text, handoff_reason e confidence."
        )
