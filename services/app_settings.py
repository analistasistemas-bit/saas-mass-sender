from __future__ import annotations

import os

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from services.agent_settings_service import ensure_agent_settings_schema, get_agent_settings, save_agent_settings_tab

SETTING_INBOUND_AI_ENABLED = 'inbound_ai_enabled'
SETTING_INBOUND_AI_MODEL = 'inbound_ai_model'


def _parse_models_csv(raw: str) -> list[str]:
    items = [part.strip() for part in str(raw or '').split(',')]
    return [item for item in items if item]


def available_inbound_ai_models() -> list[str]:
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


def ensure_app_settings_table(target_engine: Engine) -> None:
    ensure_agent_settings_schema(target_engine)


def is_inbound_ai_enabled(db: Session) -> bool:
    return get_agent_settings(db).inbound_ai_enabled


def set_inbound_ai_enabled(db: Session, enabled: bool) -> bool:
    save_agent_settings_tab(db, 'inbound', {'inbound_ai_enabled': enabled})
    return enabled


def get_inbound_ai_model(db: Session) -> str:
    current = get_agent_settings(db).primary_model
    if current:
        return current
    models = available_inbound_ai_models()
    return models[0] if models else str(os.getenv('OPENROUTER_MODEL', '')).strip()


def set_inbound_ai_model(db: Session, model: str) -> str:
    value = str(model or '').strip()
    if not value:
        raise ValueError('Modelo inválido')

    models = available_inbound_ai_models()
    allowed = {item.lower() for item in models}
    if models and value.lower() not in allowed:
        raise ValueError('Modelo não permitido pela configuração')

    save_agent_settings_tab(db, 'inbound', {'primary_model': value})
    return value
