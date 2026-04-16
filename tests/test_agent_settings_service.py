import base64
import json

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from database import Base


def test_agent_settings_bootstrap_migrates_legacy_inbound_config(monkeypatch):
    monkeypatch.setenv('OPENROUTER_MODEL', 'google/gemini-3.1-flash-lite-preview')
    monkeypatch.setenv('OPENROUTER_MODELS', 'google/gemini-3.1-flash-lite-preview,openai/gpt-4.1-mini')
    monkeypatch.setenv('BUSINESS_NAME', 'Avil Tecidos e Aviamentos')
    monkeypatch.setenv('AGENT_SETTINGS_ENCRYPTION_KEY', base64.urlsafe_b64encode(b'1' * 32).decode())

    from services.agent_settings_service import ensure_agent_settings_schema, get_agent_settings

    engine = create_engine('sqlite:///:memory:', future=True)
    Session = sessionmaker(bind=engine, future=True)
    Base.metadata.create_all(engine)

    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE app_settings (key VARCHAR(80) PRIMARY KEY, value TEXT NOT NULL, updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)"))
        conn.execute(text("INSERT INTO app_settings (key, value) VALUES ('inbound_ai_enabled', '0')"))
        conn.execute(text("INSERT INTO app_settings (key, value) VALUES ('inbound_ai_model', 'openai/gpt-4.1-mini')"))

    ensure_agent_settings_schema(engine)

    db = Session()
    settings = get_agent_settings(db)

    assert settings.inbound_ai_enabled is False
    assert settings.primary_model == 'openai/gpt-4.1-mini'
    assert settings.business_name == 'Avil Tecidos e Aviamentos'
    assert settings.tone == 'comercial'
    assert settings.max_auto_replies_per_conversation == 5


def test_agent_settings_encrypts_and_masks_db_password(monkeypatch):
    monkeypatch.setenv('OPENROUTER_MODEL', 'google/gemini-3.1-flash-lite-preview')
    monkeypatch.setenv('AGENT_SETTINGS_ENCRYPTION_KEY', base64.urlsafe_b64encode(b'2' * 32).decode())

    from services.agent_settings_service import (
        ensure_agent_settings_schema,
        get_agent_settings_payload,
        save_agent_settings_tab,
    )

    engine = create_engine('sqlite:///:memory:', future=True)
    Session = sessionmaker(bind=engine, future=True)
    Base.metadata.create_all(engine)
    ensure_agent_settings_schema(engine)

    db = Session()
    payload = save_agent_settings_tab(
        db,
        'database',
        {
            'db_enabled': True,
            'db_type': 'oracle',
            'db_host': '10.0.0.10',
            'db_port': 1521,
            'db_service': 'ORCLCDB',
            'db_user': 'readonly',
            'db_password': 'super-secret',
            'db_view_name': 'VW_PRODUTOS',
            'db_timeout_seconds': 5,
        },
    )

    assert payload['database']['db_password_masked'] == '************'
    assert payload['database']['db_password_configured'] is True

    row = db.execute(text('SELECT db_password_encrypted FROM agent_settings WHERE id = 1')).fetchone()
    assert row is not None
    assert row[0]
    assert 'super-secret' not in row[0]

    hydrated = get_agent_settings_payload(db)
    assert hydrated['database']['db_password_masked'] == '************'
    assert hydrated['database']['db_password_configured'] is True
    assert hydrated['database']['db_view_name'] == 'VW_PRODUTOS'


def test_agent_settings_saves_knowledge_priority_json(monkeypatch):
    monkeypatch.setenv('OPENROUTER_MODEL', 'google/gemini-3.1-flash-lite-preview')
    monkeypatch.setenv('AGENT_SETTINGS_ENCRYPTION_KEY', base64.urlsafe_b64encode(b'3' * 32).decode())

    from services.agent_settings_service import ensure_agent_settings_schema, save_agent_settings_tab, get_agent_settings

    engine = create_engine('sqlite:///:memory:', future=True)
    Session = sessionmaker(bind=engine, future=True)
    Base.metadata.create_all(engine)
    ensure_agent_settings_schema(engine)

    db = Session()
    save_agent_settings_tab(
        db,
        'priority',
        {'knowledge_priority': ['database', 'spreadsheet', 'manual']},
    )

    settings = get_agent_settings(db)
    assert json.loads(settings.knowledge_priority_json) == ['database', 'spreadsheet', 'manual']
