from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import main
from database import Base
from models import Campaign, Contact
from services.campaign_service import resume_campaign, start_campaign, stats_payload, update_campaign_operational_settings
from utils.daily_limit import daily_limit_reached, reset_daily_counters_if_needed
from utils.message_compose import choose_greeting, render_campaign_message


def build_session():
    engine = create_engine(
        'sqlite://',
        future=True,
        connect_args={'check_same_thread': False},
        poolclass=StaticPool,
    )
    Session = sessionmaker(bind=engine, future=True)
    Base.metadata.create_all(engine)
    return Session()


def test_choose_greeting_is_deterministic():
    assert choose_greeting(1) == choose_greeting(1)
    assert choose_greeting(2) in {'Ola', 'Oi', 'Bom dia'}


def test_render_campaign_message_keeps_body_and_applies_greeting():
    message = render_campaign_message('Temos uma novidade.\nConfira o link.', 'Maria', 2)

    assert message.startswith(('Ola, Maria!', 'Oi, Maria!', 'Bom dia, Maria!'))
    assert 'Temos uma novidade.\nConfira o link.' in message


def test_update_campaign_operational_settings_rejects_invalid_ranges():
    session = build_session()
    campaign = Campaign(name='Operacao', message_template='Oi {{nome}}', status='draft')
    session.add(campaign)
    session.commit()
    session.refresh(campaign)

    ok, message, _settings = update_campaign_operational_settings(session, campaign.id, 0, 45, 0)
    assert ok is False
    assert 'minimo' in message.lower()

    ok, message, _settings = update_campaign_operational_settings(session, campaign.id, 20, 10, 0)
    assert ok is False
    assert 'maximo' in message.lower()

    ok, message, _settings = update_campaign_operational_settings(session, campaign.id, 15, 45, -1)
    assert ok is False
    assert 'limite' in message.lower()

    ok, message, _settings = update_campaign_operational_settings(
        session,
        campaign.id,
        15,
        45,
        0,
        send_window_start='21:00',
        send_window_end='08:00',
    )
    assert ok is False
    assert 'janela' in message.lower()


def test_update_campaign_operational_settings_persists_values_and_stats_payload_exposes_them():
    session = build_session()
    campaign = Campaign(name='Operacao', message_template='Oi {{nome}}', status='ready')
    session.add(campaign)
    session.commit()
    session.refresh(campaign)

    ok, message, _settings = update_campaign_operational_settings(session, campaign.id, 20, 50, 300)
    assert ok is True
    assert 'salvas' in message.lower()

    payload = stats_payload(session, campaign.id)
    assert payload['send_delay_min_seconds'] == 20
    assert payload['send_delay_max_seconds'] == 50
    assert payload['daily_limit'] == 300
    assert payload['sent_today'] == 0
    assert payload['send_window_start'] == '08:00'
    assert payload['send_window_end'] == '20:00'
    assert payload['performance']['warming_up'] is True
    assert payload['estimates']['configured_batch_pause_min'] == 5
    assert payload['estimates']['configured_batch_pause_max'] == 10


def test_update_campaign_operational_settings_persists_send_window():
    session = build_session()
    campaign = Campaign(name='Janela', message_template='Oi {{nome}}', status='ready')
    session.add(campaign)
    session.commit()
    session.refresh(campaign)

    ok, message, settings = update_campaign_operational_settings(
        session,
        campaign.id,
        10,
        20,
        0,
        send_window_start='09:00',
        send_window_end='18:00',
    )
    assert ok is True
    assert 'salvas' in message.lower()
    assert settings['send_window_start'] == '09:00'
    assert settings['send_window_end'] == '18:00'

    payload = stats_payload(session, campaign.id)
    assert payload['send_window_start'] == '09:00'
    assert payload['send_window_end'] == '18:00'


def test_campaign_defaults_to_conservative_speed_profile():
    session = build_session()
    campaign = Campaign(name='Operacao', message_template='Oi {{nome}}', status='draft')
    session.add(campaign)
    session.commit()
    session.refresh(campaign)

    assert campaign.speed_profile == 'conservative'
    assert campaign.send_delay_min_seconds == 15
    assert campaign.send_delay_max_seconds == 45
    assert campaign.batch_pause_min_seconds == 25
    assert campaign.batch_pause_max_seconds == 40
    assert campaign.batch_size_initial == 5
    assert campaign.batch_size_max == 15


def test_update_campaign_operational_settings_applies_aggressive_preset():
    session = build_session()
    campaign = Campaign(name='Operacao', message_template='Oi {{nome}}', status='ready')
    session.add(campaign)
    session.commit()
    session.refresh(campaign)

    ok, _message, settings = update_campaign_operational_settings(
        session,
        campaign.id,
        8,
        20,
        0,
        speed_profile='aggressive',
        batch_pause_min_seconds=15,
        batch_pause_max_seconds=30,
    )

    assert ok is True
    assert settings['speed_profile'] == 'aggressive'
    assert settings['send_delay_min_seconds'] == 8
    assert settings['send_delay_max_seconds'] == 20
    assert settings['batch_pause_min_seconds'] == 15
    assert settings['batch_pause_max_seconds'] == 30
    assert settings['batch_size_initial'] == 10
    assert settings['batch_size_max'] == 25

    payload = stats_payload(session, campaign.id)
    assert payload['runtime_profile']['selected_profile'] == 'aggressive'
    assert payload['runtime_profile']['effective_profile'] == 'aggressive'


def test_update_campaign_operational_settings_marks_custom_when_manual_values_diverge():
    session = build_session()
    campaign = Campaign(name='Operacao', message_template='Oi {{nome}}', status='ready')
    session.add(campaign)
    session.commit()
    session.refresh(campaign)

    ok, _message, settings = update_campaign_operational_settings(
        session,
        campaign.id,
        6,
        18,
        50,
        speed_profile='aggressive',
        batch_pause_min_seconds=9,
        batch_pause_max_seconds=17,
    )

    assert ok is True
    assert settings['speed_profile'] == 'custom'
    assert settings['send_delay_min_seconds'] == 6
    assert settings['send_delay_max_seconds'] == 18
    assert settings['batch_pause_min_seconds'] == 9
    assert settings['batch_pause_max_seconds'] == 17

    payload = stats_payload(session, campaign.id)
    assert payload['runtime_profile']['selected_profile'] == 'custom'
    assert payload['runtime_profile']['profile_source'] == 'manual_override'


def test_stats_payload_exposes_service_monitor_snapshot():
    session = build_session()
    campaign = Campaign(name='Operacao', message_template='Oi {{nome}}', status='running')
    session.add(campaign)
    session.commit()
    session.refresh(campaign)

    payload = stats_payload(
        session,
        campaign.id,
        service_health={
            'services': {
                'worker': {
                    'key': 'worker',
                    'label': 'Motor de envio',
                    'state': 'recovering',
                    'message': 'Motor reiniciado automaticamente.',
                    'checked_at': '2026-03-20T18:40:00+00:00',
                },
                'bridge': {
                    'key': 'bridge',
                    'label': 'WhatsApp / bridge',
                    'state': 'operational',
                    'message': 'Bridge acessivel.',
                    'checked_at': '2026-03-20T18:40:00+00:00',
                },
            },
            'latest_alert': {
                'id': 'worker-recovered-1',
                'service': 'worker',
                'tone': 'success',
                'title': 'Motor recuperado',
                'message': 'O envio retomou automaticamente.',
                'created_at': '2026-03-20T18:40:00+00:00',
            },
        },
    )

    assert payload['service_health']['services']['worker']['state'] == 'recovering'
    assert payload['service_health']['services']['bridge']['state'] == 'operational'
    assert payload['service_health']['latest_alert']['id'] == 'worker-recovered-1'


def test_reset_daily_counters_if_needed_resets_when_date_changes():
    session = build_session()
    campaign = Campaign(
        name='Operacao',
        message_template='Oi {{nome}}',
        status='paused',
        daily_limit=100,
        sent_today=100,
        pause_reason='daily_limit_reached',
        last_send_date=datetime(2026, 3, 18, 12, 0, tzinfo=timezone.utc),
    )
    session.add(campaign)
    session.commit()
    session.refresh(campaign)

    changed = reset_daily_counters_if_needed(campaign, datetime(2026, 3, 19, 8, 0, tzinfo=timezone.utc))

    assert changed is True
    assert campaign.sent_today == 0
    assert campaign.last_send_date.date().isoformat() == '2026-03-19'
    assert daily_limit_reached(campaign) is False


def test_start_and_resume_block_when_daily_limit_already_reached_on_same_day():
    session = build_session()
    same_day = datetime.now(timezone.utc)
    campaign = Campaign(
        name='Operacao',
        message_template='Oi {{nome}}',
        status='ready',
        is_test_required=0,
        daily_limit=100,
        sent_today=100,
        pause_reason='daily_limit_reached',
        last_send_date=same_day,
    )
    session.add(campaign)
    session.commit()
    session.refresh(campaign)

    ok, message = start_campaign(session, campaign.id)
    assert ok is False
    assert 'limite diario' in message.lower()

    campaign.status = 'paused'
    session.add(campaign)
    session.commit()

    ok, message = resume_campaign(session, campaign.id)
    assert ok is False
    assert 'limite diario' in message.lower()


def test_campaign_settings_route_saves_values():
    session = build_session()
    campaign = Campaign(name='Operacao', message_template='Oi {{nome}}', status='draft')
    session.add(campaign)
    session.commit()
    session.refresh(campaign)

    def override_get_db():
        try:
            yield session
        finally:
            pass

    main.app.dependency_overrides[main.get_db] = override_get_db
    try:
        client = TestClient(main.app)
        client.cookies.set('mass_sender_admin', main.APP_PASSWORD)

        response = client.post(
            f'/campaigns/{campaign.id}/settings',
            data={
                'speed_profile': 'aggressive',
                'send_delay_min_seconds': 18,
                'send_delay_max_seconds': 48,
                'batch_pause_min_seconds': 8,
                'batch_pause_max_seconds': 15,
                'send_window_start': '09:00',
                'send_window_end': '19:00',
                'daily_limit': 250,
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload['ok'] is True
        assert payload['settings']['speed_profile'] == 'custom'
        assert payload['settings']['send_delay_min_seconds'] == 18
        assert payload['settings']['send_delay_max_seconds'] == 48
        assert payload['settings']['batch_pause_min_seconds'] == 8
        assert payload['settings']['batch_pause_max_seconds'] == 15
        assert payload['settings']['send_window_start'] == '09:00'
        assert payload['settings']['send_window_end'] == '19:00'
        assert payload['settings']['daily_limit'] == 250
    finally:
        main.app.dependency_overrides.clear()


def test_campaign_overview_route_returns_payload_for_running_campaign():
    session = build_session()
    campaign = Campaign(
        name='Overview',
        message_template='Oi {{nome}}',
        status='running',
        started_at=datetime.now(timezone.utc),
    )
    session.add(campaign)
    session.commit()
    session.refresh(campaign)

    session.add_all(
        [
            Contact(
                campaign_id=campaign.id,
                name='Sent',
                phone_raw='81999990001',
                phone_e164='+5581999990001',
                email='a@teste.com',
                status='sent',
                sent_at=datetime.now(timezone.utc),
            ),
            Contact(
                campaign_id=campaign.id,
                name='Pending',
                phone_raw='81999990002',
                phone_e164='+5581999990002',
                email='b@teste.com',
                status='pending',
            ),
        ]
    )
    session.commit()

    def override_get_db():
        try:
            yield session
        finally:
            pass

    main.app.dependency_overrides[main.get_db] = override_get_db
    try:
        client = TestClient(main.app)
        client.cookies.set('mass_sender_admin', main.APP_PASSWORD)

        response = client.get(f'/campaigns/{campaign.id}/overview')
        assert response.status_code == 200
        payload = response.json()
        assert payload['results']['headline'] == 'Campanha em andamento'
        assert payload['results']['distribution']['sent'] == 1
        assert payload['results']['distribution']['pending'] == 1
        assert 'summary_cards' in payload['activity']
        assert 'top_failures' in payload['results']
        assert 'incidents' in payload['activity']
    finally:
        main.app.dependency_overrides.clear()


def test_bootstrap_campaign_columns_adds_missing_operational_fields(tmp_path):
    db_path = tmp_path / 'legacy.db'
    engine = create_engine(f'sqlite:///{db_path}', future=True)
    Contact.__table__.create(bind=engine)
    with engine.begin() as conn:
        conn.execute(
            text(
                '''
                CREATE TABLE campaigns (
                    id INTEGER NOT NULL PRIMARY KEY,
                    name VARCHAR(140) NOT NULL,
                    message_template TEXT NOT NULL,
                    status VARCHAR(20) NOT NULL,
                    is_test_required INTEGER NOT NULL,
                    test_completed_at DATETIME,
                    total_contacts INTEGER NOT NULL,
                    valid_contacts INTEGER NOT NULL,
                    invalid_contacts INTEGER NOT NULL,
                    sent_count INTEGER NOT NULL,
                    failed_count INTEGER NOT NULL,
                    pending_count INTEGER NOT NULL,
                    started_at DATETIME,
                    finished_at DATETIME,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL
                )
                '''
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO campaigns (
                    id, name, message_template, status, is_test_required, total_contacts,
                    valid_contacts, invalid_contacts, sent_count, failed_count, pending_count,
                    created_at, updated_at
                ) VALUES (
                    1, 'Legacy', 'Oi {{nome}}', 'draft', 1, 0, 0, 0, 0, 0, 0,
                    '2026-03-19T00:00:00+00:00', '2026-03-19T00:00:00+00:00'
                )
                """
            )
        )

    main.ensure_campaign_operational_columns(engine)

    with engine.connect() as conn:
        campaign_rows = conn.execute(text("PRAGMA table_info('campaigns')")).fetchall()
        campaign_names = {row[1] for row in campaign_rows}
        assert 'send_delay_min_seconds' in campaign_names
        assert 'send_delay_max_seconds' in campaign_names
        assert 'speed_profile' in campaign_names
        assert 'batch_pause_min_seconds' in campaign_names
        assert 'batch_pause_max_seconds' in campaign_names
        assert 'batch_size_initial' in campaign_names
        assert 'batch_size_max' in campaign_names
        assert 'batch_growth_step' in campaign_names
        assert 'batch_growth_streak_required' in campaign_names
        assert 'batch_shrink_step' in campaign_names
        assert 'batch_shrink_error_streak_required' in campaign_names
        assert 'batch_size_floor' in campaign_names
        assert 'daily_limit' in campaign_names
        assert 'sent_today' in campaign_names
        assert 'last_send_date' in campaign_names
        assert 'pause_reason' in campaign_names
        contact_rows = conn.execute(text("PRAGMA table_info('contacts')")).fetchall()
        contact_names = {row[1] for row in contact_rows}
        assert 'source' in contact_names
        saved = conn.execute(
            text(
                'SELECT speed_profile, send_delay_min_seconds, send_delay_max_seconds, batch_pause_min_seconds, batch_pause_max_seconds, '
                'batch_size_initial, batch_size_max, batch_growth_step, batch_growth_streak_required, batch_shrink_step, '
                'batch_shrink_error_streak_required, batch_size_floor, daily_limit, sent_today, pause_reason '
                'FROM campaigns WHERE id = 1'
            )
        ).fetchone()
        assert saved == ('conservative', 15, 45, 25, 40, 5, 15, 2, 3, 2, 2, 5, 0, 0, None)
