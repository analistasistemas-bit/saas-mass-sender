from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

from cryptography.fernet import Fernet
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from sqlalchemy.orm import sessionmaker

from database import Base
from models import AgentSettings

DEFAULT_PRIORITY = ['manual', 'spreadsheet', 'database']
TAB_NAMES = {
    'inbound',
    'personality',
    'behavior',
    'handoff',
    'manual',
    'database',
    'priority',
}


def _parse_models_csv(raw: str) -> list[str]:
    items = [part.strip() for part in str(raw or '').split(',')]
    return [item for item in items if item]


def available_agent_models() -> list[str]:
    configured = _parse_models_csv(os.getenv('OPENROUTER_MODELS', ''))
    primary = str(os.getenv('OPENROUTER_MODEL', '')).strip()
    if primary:
        configured.append(primary)

    deduped: list[str] = []
    seen: set[str] = set()
    for item in configured:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


@dataclass
class AgentSettingsView:
    inbound_ai_enabled: bool
    primary_model: str
    business_name: str
    agent_name: str
    tone: str
    style: str
    proactivity_level: str
    use_emojis: bool
    max_response_length: int
    personality_instructions: str
    can_answer_price: bool
    can_answer_stock: bool
    can_answer_description: bool
    can_suggest_similar_products: bool
    can_negotiate_discount: bool
    can_close_order: bool
    handoff_on_order_intent: bool
    handoff_on_low_confidence: bool
    handoff_on_human_request: bool
    max_auto_replies_per_conversation: int
    response_delay_min_ms: int
    response_delay_max_ms: int
    handoff_enabled: bool
    handoff_message: str
    human_whatsapp_number: str
    stop_ai_after_handoff: bool
    manual_knowledge_enabled: bool
    manual_knowledge_text: str
    db_enabled: bool
    db_type: str
    db_host: str
    db_port: int
    db_service: str
    db_user: str
    db_password_encrypted: str
    db_view_name: str
    db_timeout_seconds: int
    knowledge_priority_json: str


def _fernet() -> Fernet:
    raw = str(os.getenv('AGENT_SETTINGS_ENCRYPTION_KEY') or '').strip()
    if not raw:
        raise RuntimeError('AGENT_SETTINGS_ENCRYPTION_KEY não configurada')
    key = raw.encode('utf-8')
    try:
        return Fernet(key)
    except Exception as exc:
        raise RuntimeError('AGENT_SETTINGS_ENCRYPTION_KEY inválida') from exc


def encrypt_secret(value: str) -> str:
    text_value = str(value or '').strip()
    if not text_value:
        return ''
    return _fernet().encrypt(text_value.encode('utf-8')).decode('utf-8')


def decrypt_secret(value: str) -> str:
    text_value = str(value or '').strip()
    if not text_value:
        return ''
    try:
        return _fernet().decrypt(text_value.encode('utf-8')).decode('utf-8')
    except Exception as exc:
        raise RuntimeError('Não foi possível descriptografar o segredo configurado') from exc


def _normalize_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    lowered = str(value).strip().lower()
    if lowered in {'1', 'true', 'yes', 'on', 'sim'}:
        return True
    if lowered in {'0', 'false', 'no', 'off', 'nao', 'não'}:
        return False
    return default


def _normalize_int(value: Any, default: int, *, minimum: int | None = None, maximum: int | None = None) -> int:
    try:
        normalized = int(value)
    except Exception:
        normalized = default
    if minimum is not None:
        normalized = max(minimum, normalized)
    if maximum is not None:
        normalized = min(maximum, normalized)
    return normalized


def _priority_from_payload(value: Any) -> list[str]:
    items = value if isinstance(value, list) else []
    cleaned: list[str] = []
    for item in items:
        normalized = str(item or '').strip().lower()
        if normalized in {'manual', 'spreadsheet', 'database'} and normalized not in cleaned:
            cleaned.append(normalized)
    for item in DEFAULT_PRIORITY:
        if item not in cleaned:
            cleaned.append(item)
    return cleaned


def _default_model() -> str:
    models = available_agent_models()
    if models:
        return models[0]
    return str(os.getenv('OPENROUTER_MODEL') or '').strip()


def ensure_agent_settings_schema(target_engine: Engine) -> None:
    Base.metadata.create_all(bind=target_engine)

    with target_engine.begin() as conn:
        legacy_enabled = True
        legacy_model = _default_model()
        try:
            rows = conn.execute(text("SELECT key, value FROM app_settings WHERE key IN ('inbound_ai_enabled', 'inbound_ai_model')")).fetchall()
            for key, value in rows:
                if key == 'inbound_ai_enabled':
                    legacy_enabled = _normalize_bool(value, True)
                if key == 'inbound_ai_model':
                    legacy_model = str(value or '').strip() or legacy_model
        except Exception:
            pass

        exists = conn.execute(text('SELECT 1 FROM agent_settings WHERE id = 1')).fetchone()
        if exists:
            return

    SessionLocal = sessionmaker(bind=target_engine, autoflush=False, autocommit=False, future=True)
    db = SessionLocal()
    try:
        if db.get(AgentSettings, 1) is None:
            item = AgentSettings(
                id=1,
                inbound_ai_enabled=legacy_enabled,
                primary_model=legacy_model,
                business_name=str(os.getenv('BUSINESS_NAME') or '').strip(),
                human_whatsapp_number=str(os.getenv('HUMAN_HANDOFF_PHONE') or '').strip(),
                knowledge_priority_json=json.dumps(DEFAULT_PRIORITY, ensure_ascii=False),
            )
            db.add(item)
            db.commit()
    finally:
        db.close()


def _settings_row(db: Session) -> AgentSettings:
    item = db.get(AgentSettings, 1)
    if item is None:
        ensure_agent_settings_schema(db.get_bind())
        item = db.get(AgentSettings, 1)
    if item is None:
        raise RuntimeError('Configuração do agente não inicializada')
    return item


def get_agent_settings(db: Session) -> AgentSettingsView:
    item = _settings_row(db)
    return AgentSettingsView(
        inbound_ai_enabled=bool(item.inbound_ai_enabled),
        primary_model=item.primary_model,
        business_name=item.business_name,
        agent_name=item.agent_name,
        tone=item.tone,
        style=item.style,
        proactivity_level=item.proactivity_level,
        use_emojis=bool(item.use_emojis),
        max_response_length=int(item.max_response_length or 500),
        personality_instructions=item.personality_instructions,
        can_answer_price=bool(item.can_answer_price),
        can_answer_stock=bool(item.can_answer_stock),
        can_answer_description=bool(item.can_answer_description),
        can_suggest_similar_products=bool(item.can_suggest_similar_products),
        can_negotiate_discount=bool(item.can_negotiate_discount),
        can_close_order=bool(item.can_close_order),
        handoff_on_order_intent=bool(item.handoff_on_order_intent),
        handoff_on_low_confidence=bool(item.handoff_on_low_confidence),
        handoff_on_human_request=bool(item.handoff_on_human_request),
        max_auto_replies_per_conversation=int(item.max_auto_replies_per_conversation or 5),
        response_delay_min_ms=int(item.response_delay_min_ms or 1000),
        response_delay_max_ms=int(item.response_delay_max_ms or 3000),
        handoff_enabled=bool(item.handoff_enabled),
        handoff_message=item.handoff_message,
        human_whatsapp_number=item.human_whatsapp_number,
        stop_ai_after_handoff=bool(item.stop_ai_after_handoff),
        manual_knowledge_enabled=bool(item.manual_knowledge_enabled),
        manual_knowledge_text=item.manual_knowledge_text,
        db_enabled=bool(item.db_enabled),
        db_type=item.db_type,
        db_host=item.db_host,
        db_port=int(item.db_port or 1521),
        db_service=item.db_service,
        db_user=item.db_user,
        db_password_encrypted=item.db_password_encrypted,
        db_view_name=item.db_view_name,
        db_timeout_seconds=int(item.db_timeout_seconds or 5),
        knowledge_priority_json=item.knowledge_priority_json or json.dumps(DEFAULT_PRIORITY),
    )


def _masked_password(encrypted_value: str) -> tuple[bool, str]:
    configured = bool(str(encrypted_value or '').strip())
    return configured, '************' if configured else ''


def get_agent_settings_payload(db: Session) -> dict[str, Any]:
    settings = get_agent_settings(db)
    password_configured, password_masked = _masked_password(settings.db_password_encrypted)
    models = available_agent_models()
    primary_model = settings.primary_model or _default_model()
    if models and primary_model not in models:
        primary_model = models[0]

    return {
        'summary': {
            'enabled': settings.inbound_ai_enabled,
            'primary_model': primary_model,
            'business_name': settings.business_name,
        },
        'available_models': models,
        'inbound': {
            'inbound_ai_enabled': settings.inbound_ai_enabled,
            'primary_model': primary_model,
            'test_model': primary_model,
            'business_name': settings.business_name,
        },
        'personality': {
            'agent_name': settings.agent_name,
            'tone': settings.tone,
            'style': settings.style,
            'proactivity_level': settings.proactivity_level,
            'use_emojis': settings.use_emojis,
            'max_response_length': settings.max_response_length,
            'personality_instructions': settings.personality_instructions,
        },
        'behavior': {
            'can_answer_price': settings.can_answer_price,
            'can_answer_stock': settings.can_answer_stock,
            'can_answer_description': settings.can_answer_description,
            'can_suggest_similar_products': settings.can_suggest_similar_products,
            'can_negotiate_discount': settings.can_negotiate_discount,
            'can_close_order': settings.can_close_order,
            'handoff_on_order_intent': settings.handoff_on_order_intent,
            'handoff_on_low_confidence': settings.handoff_on_low_confidence,
            'handoff_on_human_request': settings.handoff_on_human_request,
            'max_auto_replies_per_conversation': settings.max_auto_replies_per_conversation,
            'response_delay_min_ms': settings.response_delay_min_ms,
            'response_delay_max_ms': settings.response_delay_max_ms,
        },
        'handoff': {
            'handoff_enabled': settings.handoff_enabled,
            'handoff_message': settings.handoff_message,
            'human_whatsapp_number': settings.human_whatsapp_number,
            'stop_ai_after_handoff': settings.stop_ai_after_handoff,
        },
        'manual': {
            'manual_knowledge_enabled': settings.manual_knowledge_enabled,
            'manual_knowledge_text': settings.manual_knowledge_text,
        },
        'database': {
            'db_enabled': settings.db_enabled,
            'db_type': settings.db_type,
            'db_host': settings.db_host,
            'db_port': settings.db_port,
            'db_service': settings.db_service,
            'db_user': settings.db_user,
            'db_password_configured': password_configured,
            'db_password_masked': password_masked,
            'db_view_name': settings.db_view_name,
            'db_timeout_seconds': settings.db_timeout_seconds,
        },
        'priority': {
            'knowledge_priority': _priority_from_payload(json.loads(settings.knowledge_priority_json or '[]')),
        },
    }


def save_agent_settings_tab(db: Session, tab: str, payload: dict[str, Any]) -> dict[str, Any]:
    normalized_tab = str(tab or '').strip().lower()
    if normalized_tab not in TAB_NAMES:
        raise ValueError('Aba inválida')

    item = _settings_row(db)

    if normalized_tab == 'inbound':
        item.inbound_ai_enabled = _normalize_bool(payload.get('inbound_ai_enabled'), item.inbound_ai_enabled)
        model = str(payload.get('primary_model') or '').strip()
        allowed_models = available_agent_models()
        if model:
            if allowed_models and model not in allowed_models:
                raise ValueError('Modelo não permitido pela configuração')
            item.primary_model = model
        if 'business_name' in payload:
            item.business_name = str(payload.get('business_name') or '').strip()

    elif normalized_tab == 'personality':
        item.agent_name = str(payload.get('agent_name') or item.agent_name).strip() or 'Assistente virtual'
        item.tone = str(payload.get('tone') or item.tone).strip() or 'comercial'
        item.style = str(payload.get('style') or item.style).strip() or 'equilibrado'
        item.proactivity_level = str(payload.get('proactivity_level') or item.proactivity_level).strip() or 'medio'
        item.use_emojis = _normalize_bool(payload.get('use_emojis'), item.use_emojis)
        item.max_response_length = _normalize_int(payload.get('max_response_length'), item.max_response_length, minimum=80, maximum=4000)
        item.personality_instructions = str(payload.get('personality_instructions') or '').strip()

    elif normalized_tab == 'behavior':
        for key in (
            'can_answer_price',
            'can_answer_stock',
            'can_answer_description',
            'can_suggest_similar_products',
            'can_negotiate_discount',
            'can_close_order',
            'handoff_on_order_intent',
            'handoff_on_low_confidence',
            'handoff_on_human_request',
        ):
            setattr(item, key, _normalize_bool(payload.get(key), getattr(item, key)))
        item.max_auto_replies_per_conversation = _normalize_int(
            payload.get('max_auto_replies_per_conversation'),
            item.max_auto_replies_per_conversation,
            minimum=1,
            maximum=20,
        )
        item.response_delay_min_ms = _normalize_int(payload.get('response_delay_min_ms'), item.response_delay_min_ms, minimum=0, maximum=60000)
        item.response_delay_max_ms = _normalize_int(payload.get('response_delay_max_ms'), item.response_delay_max_ms, minimum=item.response_delay_min_ms, maximum=120000)

    elif normalized_tab == 'handoff':
        item.handoff_enabled = _normalize_bool(payload.get('handoff_enabled'), item.handoff_enabled)
        item.handoff_message = str(payload.get('handoff_message') or item.handoff_message).strip() or 'Vou passar seu atendimento para meu gerente.'
        item.human_whatsapp_number = str(payload.get('human_whatsapp_number') or item.human_whatsapp_number).strip()
        item.stop_ai_after_handoff = _normalize_bool(payload.get('stop_ai_after_handoff'), item.stop_ai_after_handoff)

    elif normalized_tab == 'manual':
        item.manual_knowledge_enabled = _normalize_bool(payload.get('manual_knowledge_enabled'), item.manual_knowledge_enabled)
        item.manual_knowledge_text = str(payload.get('manual_knowledge_text') or '').strip()

    elif normalized_tab == 'database':
        item.db_enabled = _normalize_bool(payload.get('db_enabled'), item.db_enabled)
        item.db_type = str(payload.get('db_type') or item.db_type).strip() or 'oracle'
        item.db_host = str(payload.get('db_host') or '').strip()
        item.db_port = _normalize_int(payload.get('db_port'), item.db_port, minimum=1, maximum=65535)
        item.db_service = str(payload.get('db_service') or '').strip()
        item.db_user = str(payload.get('db_user') or '').strip()
        if 'db_password' in payload and str(payload.get('db_password') or '').strip():
            item.db_password_encrypted = encrypt_secret(str(payload.get('db_password')))
        item.db_view_name = str(payload.get('db_view_name') or '').strip()
        item.db_timeout_seconds = _normalize_int(payload.get('db_timeout_seconds'), item.db_timeout_seconds, minimum=1, maximum=30)

    elif normalized_tab == 'priority':
        item.knowledge_priority_json = json.dumps(
            _priority_from_payload(payload.get('knowledge_priority')),
            ensure_ascii=False,
        )

    db.add(item)
    db.commit()
    db.refresh(item)
    return get_agent_settings_payload(db)
