from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models import Campaign, Contact
from services.campaign_service import (
    add_manual_contact,
    build_activity_payload,
    build_results_payload,
    delete_campaign,
    delete_imported_contacts_from_campaign,
    delete_contact_from_campaign,
    dry_run,
    log_event,
    restart_campaign,
    start_campaign,
    stats_payload,
    upload_contacts,
)


def build_session():
    engine = create_engine('sqlite:///:memory:', future=True)
    Session = sessionmaker(bind=engine, future=True)
    Base.metadata.create_all(engine)
    return Session()


def test_dry_run_returns_friendly_empty_payload_for_completed_campaign():
    session = build_session()
    campaign = Campaign(name='Lote', message_template='Oi {{nome}}', status='completed')
    session.add(campaign)
    session.commit()
    session.refresh(campaign)

    payload = dry_run(session, campaign.id)

    assert payload['ok'] is True
    assert payload['pending_count'] == 0
    assert payload['empty_reason'] == 'campaign_completed'
    assert 'já foi concluída' in payload['message']
    assert payload['preview'] == []


def test_restart_campaign_all_resets_sent_failed_and_processing():
    session = build_session()
    campaign = Campaign(
        name='Reenvio',
        message_template='Oi, {{nome}}',
        status='completed',
        test_completed_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
    )
    session.add(campaign)
    session.commit()
    session.refresh(campaign)

    rows = [
        Contact(campaign_id=campaign.id, name='Sent', phone_raw='1', phone_e164='+5511', email='a@a', status='sent', attempt_count=2, error_message='x', sent_at=datetime.now(timezone.utc), last_attempt_at=datetime.now(timezone.utc)),
        Contact(campaign_id=campaign.id, name='Failed', phone_raw='2', phone_e164='+5512', email='b@b', status='failed', attempt_count=1, error_message='boom', last_attempt_at=datetime.now(timezone.utc)),
        Contact(campaign_id=campaign.id, name='Processing', phone_raw='3', phone_e164='+5513', email='c@c', status='processing', attempt_count=1, error_message='wait', last_attempt_at=datetime.now(timezone.utc)),
        Contact(campaign_id=campaign.id, name='Invalid', phone_raw='4', phone_e164=None, email='d@d', status='invalid', error_message='bad'),
    ]
    session.add_all(rows)
    session.commit()

    ok, message, reset_contacts, new_status = restart_campaign(session, campaign.id, 'all')

    assert ok is True
    assert new_status == 'ready'
    assert reset_contacts == 3
    assert 'Fila recriada' in message

    refreshed = {c.name: c for c in session.query(Contact).filter(Contact.campaign_id == campaign.id).all()}
    assert refreshed['Sent'].status == 'pending'
    assert refreshed['Sent'].attempt_count == 0
    assert refreshed['Sent'].error_message is None
    assert refreshed['Sent'].sent_at is None
    assert refreshed['Failed'].status == 'pending'
    assert refreshed['Processing'].status == 'pending'
    assert refreshed['Invalid'].status == 'invalid'

    session.refresh(campaign)
    assert campaign.status == 'ready'
    assert campaign.test_completed_at is None
    assert campaign.started_at is None
    assert campaign.finished_at is None


def test_restart_campaign_failed_only_resets_failed_and_processing():
    session = build_session()
    campaign = Campaign(
        name='Reenvio',
        message_template='Oi, {{nome}}',
        status='completed',
        test_completed_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
    )
    session.add(campaign)
    session.commit()
    session.refresh(campaign)

    rows = [
        Contact(campaign_id=campaign.id, name='Sent', phone_raw='1', phone_e164='+5511', email='a@a', status='sent', attempt_count=2, sent_at=datetime.now(timezone.utc)),
        Contact(campaign_id=campaign.id, name='Failed', phone_raw='2', phone_e164='+5512', email='b@b', status='failed', attempt_count=1, error_message='boom', last_attempt_at=datetime.now(timezone.utc)),
        Contact(campaign_id=campaign.id, name='Processing', phone_raw='3', phone_e164='+5513', email='c@c', status='processing', attempt_count=1, error_message='wait', last_attempt_at=datetime.now(timezone.utc)),
    ]
    session.add_all(rows)
    session.commit()

    ok, message, reset_contacts, new_status = restart_campaign(session, campaign.id, 'failed')

    assert ok is True
    assert new_status == 'ready'
    assert reset_contacts == 2
    assert 'falhas' in message.lower()

    refreshed = {c.name: c for c in session.query(Contact).filter(Contact.campaign_id == campaign.id).all()}
    assert refreshed['Sent'].status == 'sent'
    assert refreshed['Failed'].status == 'pending'
    assert refreshed['Processing'].status == 'pending'


def test_add_manual_contact_inserts_pending_contact_with_optional_email():
    session = build_session()
    campaign = Campaign(name='Manual', message_template='Oi {{nome}}', status='draft')
    session.add(campaign)
    session.commit()
    session.refresh(campaign)

    result = add_manual_contact(
        session,
        campaign.id,
        name='Cliente Manual',
        phone='(81) 99999-9999',
        email='',
    )

    assert result['ok'] is True
    assert result['contact']['name'] == 'Cliente Manual'
    assert result['contact']['phone_e164'] == '+5581999999999'
    assert result['contact']['email'] == ''

    inserted = session.query(Contact).filter(Contact.campaign_id == campaign.id).all()
    assert len(inserted) == 1
    assert inserted[0].status == 'pending'
    assert inserted[0].phone_e164 == '+5581999999999'


def test_add_manual_contact_rejects_invalid_phone():
    session = build_session()
    campaign = Campaign(name='Manual', message_template='Oi {{nome}}', status='draft')
    session.add(campaign)
    session.commit()
    session.refresh(campaign)

    result = add_manual_contact(
        session,
        campaign.id,
        name='Cliente Invalido',
        phone='1234',
        email='x@x.com',
    )

    assert result['ok'] is False
    assert 'Formato' in result['message'] or 'Telefone' in result['message']


def test_add_manual_contact_rejects_duplicate_phone_in_same_campaign():
    session = build_session()
    campaign = Campaign(name='Manual', message_template='Oi {{nome}}', status='draft')
    session.add(campaign)
    session.commit()
    session.refresh(campaign)

    first = add_manual_contact(
        session,
        campaign.id,
        name='Primeiro',
        phone='+55 81 99999-9999',
        email='a@a.com',
    )
    assert first['ok'] is True

    duplicate = add_manual_contact(
        session,
        campaign.id,
        name='Segundo',
        phone='81999999999',
        email='b@b.com',
    )

    assert duplicate['ok'] is False
    assert 'já existe' in duplicate['message'].lower()


def test_add_manual_contact_reopens_completed_campaign_to_ready():
    session = build_session()
    campaign = Campaign(
        name='Manual',
        message_template='Oi {{nome}}',
        status='completed',
        test_completed_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
    )
    session.add(campaign)
    session.commit()
    session.refresh(campaign)

    result = add_manual_contact(
        session,
        campaign.id,
        name='Novo Cliente',
        phone='+55 81999999999',
        email='novo@cliente.com',
    )

    assert result['ok'] is True
    session.refresh(campaign)
    assert campaign.status == 'ready'
    assert campaign.finished_at is None


def test_upload_contacts_replaces_previous_csv_contacts_and_preserves_manual_ones():
    session = build_session()
    campaign = Campaign(name='Reimportar', message_template='Oi {{nome}}', status='draft')
    session.add(campaign)
    session.commit()
    session.refresh(campaign)

    session.add_all(
        [
            Contact(
                campaign_id=campaign.id,
                name='CSV antigo 1',
                phone_raw='81999990001',
                phone_e164='+5581999990001',
                email='old1@csv.com',
                status='pending',
                source='csv',
            ),
            Contact(
                campaign_id=campaign.id,
                name='CSV antigo 2',
                phone_raw='81999990002',
                phone_e164='+5581999990002',
                email='old2@csv.com',
                status='invalid',
                error_message='Telefone ausente',
                source='csv',
            ),
            Contact(
                campaign_id=campaign.id,
                name='Manual preservado',
                phone_raw='81999990003',
                phone_e164='+5581999990003',
                email='manual@cliente.com',
                status='pending',
                source='manual',
            ),
        ]
    )
    session.commit()

    payload = 'nome,telefone,email\nNovo CSV,81999990004,novo@csv.com\n'.encode('utf-8')
    result = upload_contacts(session, campaign.id, payload)

    assert result['summary']['total'] == 1
    assert result['summary']['inserted'] == 1

    contacts = session.query(Contact).filter(Contact.campaign_id == campaign.id).order_by(Contact.id.asc()).all()
    assert len(contacts) == 2
    assert {contact.name for contact in contacts} == {'Manual preservado', 'Novo CSV'}
    assert {contact.source for contact in contacts} == {'manual', 'csv'}


def test_upload_contacts_promotes_draft_campaign_to_ready():
    session = build_session()
    campaign = Campaign(name='Upload libera fluxo', message_template='Oi {{nome}}', status='draft')
    session.add(campaign)
    session.commit()
    session.refresh(campaign)

    payload = 'nome,telefone,email\nNovo CSV,81999990004,novo@csv.com\n'.encode('utf-8')

    result = upload_contacts(session, campaign.id, payload)

    assert result['summary']['inserted'] == 1
    session.refresh(campaign)
    assert campaign.status == 'ready'


def test_stats_payload_reopens_completed_campaign_when_pending_exists():
    session = build_session()
    campaign = Campaign(
        name='Manual',
        message_template='Oi {{nome}}',
        status='completed',
        test_completed_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
    )
    session.add(campaign)
    session.commit()
    session.refresh(campaign)

    session.add(
        Contact(
            campaign_id=campaign.id,
            name='Pendente antigo',
            phone_raw='+55 81999999997',
            phone_e164='+5581999999997',
            email='pendente@cliente.com',
            status='pending',
        )
    )
    session.commit()

    payload = stats_payload(session, campaign.id)

    session.refresh(campaign)
    assert payload['status'] == 'ready'
    assert payload['pending'] == 1
    assert campaign.status == 'ready'
    assert campaign.finished_at is None


def test_stats_payload_promotes_draft_campaign_when_pending_exists():
    session = build_session()
    campaign = Campaign(name='Draft com fila', message_template='Oi {{nome}}', status='draft')
    session.add(campaign)
    session.commit()
    session.refresh(campaign)

    session.add(
        Contact(
            campaign_id=campaign.id,
            name='Pendente atual',
            phone_raw='+55 81999999994',
            phone_e164='+5581999999994',
            email='pendente@cliente.com',
            status='pending',
        )
    )
    session.commit()

    payload = stats_payload(session, campaign.id)

    session.refresh(campaign)
    assert payload['status'] == 'ready'
    assert payload['pending'] == 1
    assert campaign.status == 'ready'


def test_start_campaign_allows_reopened_queue_without_new_test_when_history_exists():
    session = build_session()
    campaign = Campaign(
        name='Manual',
        message_template='Oi {{nome}}',
        status='completed',
        finished_at=datetime.now(timezone.utc),
    )
    session.add(campaign)
    session.commit()
    session.refresh(campaign)

    session.add_all(
        [
            Contact(
                campaign_id=campaign.id,
                name='Ja enviado',
                phone_raw='+55 81999999996',
                phone_e164='+5581999999996',
                email='sent@cliente.com',
                status='sent',
                sent_at=datetime.now(timezone.utc),
            ),
            Contact(
                campaign_id=campaign.id,
                name='Novo contato',
                phone_raw='+55 81999999995',
                phone_e164='+5581999999995',
                email='novo@cliente.com',
                status='pending',
            ),
        ]
    )
    session.commit()

    payload = stats_payload(session, campaign.id)
    assert payload['status'] == 'ready'

    ok, message = start_campaign(session, campaign.id)

    assert ok is True
    assert 'iniciada' in message.lower()


def test_stats_payload_exposes_current_cycle_metrics():
    session = build_session()
    started_at = datetime.now(timezone.utc)
    campaign = Campaign(
        name='Metrics',
        message_template='Oi {{nome}}',
        status='running',
        started_at=started_at,
    )
    session.add(campaign)
    session.commit()
    session.refresh(campaign)

    session.add_all(
        [
            Contact(
                campaign_id=campaign.id,
                name='Historico antigo',
                phone_raw='+55 81999999994',
                phone_e164='+5581999999994',
                email='old@cliente.com',
                status='sent',
                sent_at=datetime.now(timezone.utc).replace(year=2025),
            ),
            Contact(
                campaign_id=campaign.id,
                name='Enviado atual',
                phone_raw='+55 81999999993',
                phone_e164='+5581999999993',
                email='new@cliente.com',
                status='sent',
                sent_at=started_at,
            ),
            Contact(
                campaign_id=campaign.id,
                name='Pendente atual',
                phone_raw='+55 81999999992',
                phone_e164='+5581999999992',
                email='pending@cliente.com',
                status='pending',
            ),
        ]
    )
    session.commit()

    payload = stats_payload(session, campaign.id)

    assert payload['current_cycle']['sent'] == 1
    assert payload['current_cycle']['pending'] == 1
    assert payload['current_cycle']['total'] == 2


def test_stats_payload_exposes_observed_performance_and_estimates():
    session = build_session()
    started_at = datetime.now(timezone.utc) - timedelta(minutes=4)
    campaign = Campaign(
        name='Observed',
        message_template='Oi {{nome}}',
        status='running',
        started_at=started_at,
        send_delay_min_seconds=5,
        send_delay_max_seconds=10,
    )
    session.add(campaign)
    session.commit()
    session.refresh(campaign)

    session.add_all(
        [
            Contact(
                campaign_id=campaign.id,
                name='Sent 1',
                phone_raw='+55 81999999981',
                phone_e164='+5581999999981',
                email='a@cliente.com',
                status='sent',
                sent_at=started_at + timedelta(seconds=60),
            ),
            Contact(
                campaign_id=campaign.id,
                name='Sent 2',
                phone_raw='+55 81999999982',
                phone_e164='+5581999999982',
                email='b@cliente.com',
                status='sent',
                sent_at=started_at + timedelta(seconds=120),
            ),
            Contact(
                campaign_id=campaign.id,
                name='Sent 3',
                phone_raw='+55 81999999983',
                phone_e164='+5581999999983',
                email='c@cliente.com',
                status='sent',
                sent_at=started_at + timedelta(seconds=180),
            ),
            Contact(
                campaign_id=campaign.id,
                name='Pending',
                phone_raw='+55 81999999984',
                phone_e164='+5581999999984',
                email='d@cliente.com',
                status='pending',
            ),
            Contact(
                campaign_id=campaign.id,
                name='Pending 2',
                phone_raw='+55 81999999985',
                phone_e164='+5581999999985',
                email='e@cliente.com',
                status='pending',
            ),
        ]
    )
    session.commit()

    payload = stats_payload(session, campaign.id)

    assert payload['performance']['warming_up'] is False
    assert payload['performance']['measurement_basis'] == 'recent_window'
    assert payload['performance']['sample_size'] == 3
    assert payload['performance']['observed_seconds_per_contact'] == 60
    assert payload['performance']['observed_contacts_per_minute'] == 1.0
    assert payload['estimates']['remaining_seconds_observed'] == 120
    assert payload['estimates']['configured_batch_pause_min'] == 5
    assert payload['estimates']['configured_batch_pause_max'] == 10
    assert 'Config.:' in payload['estimates']['label_configured_pace']


def test_stats_payload_marks_warming_up_when_sample_is_too_small():
    session = build_session()
    started_at = datetime.now(timezone.utc) - timedelta(minutes=2)
    campaign = Campaign(
        name='Warmup',
        message_template='Oi {{nome}}',
        status='running',
        started_at=started_at,
    )
    session.add(campaign)
    session.commit()
    session.refresh(campaign)

    session.add_all(
        [
            Contact(
                campaign_id=campaign.id,
                name='Sent 1',
                phone_raw='+55 81999999986',
                phone_e164='+5581999999986',
                email='a@cliente.com',
                status='sent',
                sent_at=started_at + timedelta(seconds=45),
            ),
            Contact(
                campaign_id=campaign.id,
                name='Pending',
                phone_raw='+55 81999999987',
                phone_e164='+5581999999987',
                email='b@cliente.com',
                status='pending',
            ),
        ]
    )
    session.commit()

    payload = stats_payload(session, campaign.id)

    assert payload['performance']['warming_up'] is True
    assert payload['performance']['measurement_basis'] == 'warming_up'
    assert payload['estimates']['label_speed'] == 'Aquecendo medicao'
    assert payload['estimates']['label_eta'] == 'Calculando com base na execucao real'


def test_stats_payload_reconciles_ready_campaign_without_pending_back_to_completed():
    session = build_session()
    campaign = Campaign(
        name='Reconciliar',
        message_template='Oi {{nome}}',
        status='ready',
    )
    session.add(campaign)
    session.commit()
    session.refresh(campaign)

    session.add_all(
        [
            Contact(
                campaign_id=campaign.id,
                name='Contato 1',
                phone_raw='+55 81999999990',
                phone_e164='+5581999999990',
                email='a@cliente.com',
                status='sent',
                sent_at=datetime.now(timezone.utc),
            ),
            Contact(
                campaign_id=campaign.id,
                name='Contato 2',
                phone_raw='+55 81999999991',
                phone_e164='+5581999999991',
                email='b@cliente.com',
                status='sent',
                sent_at=datetime.now(timezone.utc),
            ),
        ]
    )
    session.commit()

    payload = stats_payload(session, campaign.id)

    session.refresh(campaign)
    assert payload['status'] == 'completed'
    assert campaign.status == 'completed'
    assert campaign.finished_at is not None


def test_delete_contact_from_campaign_removes_contact_in_ready_status():
    session = build_session()
    campaign = Campaign(name='Excluir', message_template='Oi {{nome}}', status='ready')
    session.add(campaign)
    session.commit()
    session.refresh(campaign)

    contact = Contact(
        campaign_id=campaign.id,
        name='Contato Excluir',
        phone_raw='+55 81999999999',
        phone_e164='+5581999999999',
        email='x@x.com',
        status='pending',
    )
    session.add(contact)
    session.commit()
    session.refresh(contact)

    result = delete_contact_from_campaign(session, campaign.id, contact.id)

    assert result['ok'] is True
    assert 'removido' in result['message'].lower()
    assert session.get(Contact, contact.id) is None


def test_delete_contact_from_campaign_blocks_when_campaign_running():
    session = build_session()
    campaign = Campaign(name='Excluir', message_template='Oi {{nome}}', status='running')
    session.add(campaign)
    session.commit()
    session.refresh(campaign)

    contact = Contact(
        campaign_id=campaign.id,
        name='Contato Running',
        phone_raw='+55 81999999998',
        phone_e164='+5581999999998',
        email='x@x.com',
        status='pending',
    )
    session.add(contact)
    session.commit()
    session.refresh(contact)

    result = delete_contact_from_campaign(session, campaign.id, contact.id)

    assert result['ok'] is False
    assert 'nao pode remover' in result['message'].lower()
    assert session.get(Contact, contact.id) is not None


def test_delete_imported_contacts_from_campaign_removes_only_csv_contacts():
    session = build_session()
    campaign = Campaign(name='Limpar CSV', message_template='Oi {{nome}}', status='ready')
    session.add(campaign)
    session.commit()
    session.refresh(campaign)

    csv_contacts = [
        Contact(
            campaign_id=campaign.id,
            name='CSV 1',
            phone_raw='+55 81999999991',
            phone_e164='+5581999999991',
            email='csv1@x.com',
            source='csv',
            status='pending',
        ),
        Contact(
            campaign_id=campaign.id,
            name='CSV 2',
            phone_raw='+55 81999999992',
            phone_e164='+5581999999992',
            email='csv2@x.com',
            source='csv',
            status='invalid',
        ),
    ]
    manual_contact = Contact(
        campaign_id=campaign.id,
        name='Manual',
        phone_raw='+55 81999999993',
        phone_e164='+5581999999993',
        email='manual@x.com',
        source='manual',
        status='pending',
    )
    session.add_all(csv_contacts + [manual_contact])
    session.commit()

    result = delete_imported_contacts_from_campaign(session, campaign.id)

    assert result['ok'] is True
    assert result['deleted_count'] == 2
    assert 'importados' in result['message'].lower()
    remaining = session.query(Contact).filter(Contact.campaign_id == campaign.id).all()
    assert len(remaining) == 1
    assert remaining[0].source == 'manual'


def test_delete_imported_contacts_from_campaign_blocks_when_campaign_running():
    session = build_session()
    campaign = Campaign(name='Limpar CSV', message_template='Oi {{nome}}', status='running')
    session.add(campaign)
    session.commit()
    session.refresh(campaign)

    session.add(
        Contact(
            campaign_id=campaign.id,
            name='CSV 1',
            phone_raw='+55 81999999991',
            phone_e164='+5581999999991',
            email='csv1@x.com',
            source='csv',
            status='pending',
        )
    )
    session.commit()

    result = delete_imported_contacts_from_campaign(session, campaign.id)

    assert result['ok'] is False
    assert 'nao pode limpar' in result['message'].lower()
    assert session.query(Contact).filter(Contact.campaign_id == campaign.id).count() == 1


def test_delete_campaign_removes_campaign_contacts_and_logs():
    session = build_session()
    campaign = Campaign(name='Excluir campanha', message_template='Oi {{nome}}', status='paused')
    session.add(campaign)
    session.commit()
    session.refresh(campaign)

    contact = Contact(
        campaign_id=campaign.id,
        name='Contato',
        phone_raw='+55 81999999991',
        phone_e164='+5581999999991',
        email='x@x.com',
        source='csv',
        status='pending',
    )
    session.add(contact)
    session.commit()
    session.refresh(contact)
    log_event(session, campaign.id, contact.id, 'campaign_state_change', 'campaign paused')
    session.commit()

    result = delete_campaign(session, campaign.id)

    assert result['ok'] is True
    assert 'excluida' in result['message'].lower()
    assert session.get(Campaign, campaign.id) is None
    assert session.query(Contact).filter(Contact.campaign_id == campaign.id).count() == 0


def test_delete_campaign_blocks_when_running():
    session = build_session()
    campaign = Campaign(name='Excluir campanha', message_template='Oi {{nome}}', status='running')
    session.add(campaign)
    session.commit()
    session.refresh(campaign)

    result = delete_campaign(session, campaign.id)

    assert result['ok'] is False
    assert 'nao pode excluir' in result['message'].lower()
    assert session.get(Campaign, campaign.id) is not None


def test_build_results_payload_returns_aggregated_operational_summary():
    session = build_session()
    started_at = datetime.now(timezone.utc)
    finished_at = datetime.now(timezone.utc)
    campaign = Campaign(
        name='Resultados',
        message_template='Oi {{nome}}',
        status='completed',
        started_at=started_at,
        finished_at=finished_at,
    )
    session.add(campaign)
    session.commit()
    session.refresh(campaign)

    session.add_all(
        [
            Contact(campaign_id=campaign.id, name='Sent 1', phone_raw='1', phone_e164='+551', email='a@a', status='sent', sent_at=started_at),
            Contact(campaign_id=campaign.id, name='Sent 2', phone_raw='2', phone_e164='+552', email='b@b', status='sent', sent_at=started_at),
            Contact(campaign_id=campaign.id, name='Fail', phone_raw='3', phone_e164='+553', email='c@c', status='failed', error_message='bridge_unreachable'),
            Contact(campaign_id=campaign.id, name='Invalid', phone_raw='4', phone_e164=None, email='d@d', status='invalid', error_message='number_resolution_failed'),
        ]
    )
    session.commit()

    payload = build_results_payload(session, campaign.id)

    assert payload['headline'] == 'Campanha concluida'
    assert payload['processed'] == 3
    assert payload['distribution']['sent'] == 2
    assert payload['distribution']['failed'] == 1
    assert payload['distribution']['invalid'] == 1
    assert payload['success_rate'] > 60
    assert payload['coverage_rate'] > 0
    assert payload['top_failures']
    first_failure = payload['top_failures'][0]
    assert 'human_title' in first_failure
    assert 'recommended_action' in first_failure
    assert first_failure['technical_detail_available'] is True
    assert first_failure['fingerprint']


def test_build_results_payload_includes_failed_reprocessing_summary_after_completed_campaign_restart():
    session = build_session()
    completed_at = datetime.now(timezone.utc) - timedelta(hours=1)
    reprocess_started_at = datetime.now(timezone.utc) - timedelta(minutes=10)
    campaign = Campaign(
        name='Reprocessamento',
        message_template='Oi {{nome}}',
        status='ready',
        started_at=reprocess_started_at,
        finished_at=None,
    )
    session.add(campaign)
    session.commit()
    session.refresh(campaign)

    session.add_all(
        [
            Contact(campaign_id=campaign.id, name='Sent original', phone_raw='1', phone_e164='+551', email='a@a', status='sent', sent_at=completed_at),
            Contact(
                campaign_id=campaign.id,
                name='Sent reprocessado',
                phone_raw='2',
                phone_e164='+552',
                email='b@b',
                status='sent',
                sent_at=reprocess_started_at + timedelta(seconds=1),
            ),
            Contact(campaign_id=campaign.id, name='Failed pendente', phone_raw='3', phone_e164='+553', email='c@c', status='pending'),
        ]
    )
    session.flush()
    log_event(session, campaign.id, None, 'campaign_state_change', 'campaign completed')
    log_event(session, campaign.id, None, 'campaign_state_change', 'campaign restarted; mode=failed; reset=2')
    session.commit()

    payload = build_results_payload(session, campaign.id)

    assert payload['headline'] == 'Fila reaberta'
    assert payload['reprocessing'] == {
        'active': True,
        'mode': 'failed',
        'reset_contacts': 2,
        'queued_contacts': 1,
        'sent_in_reprocessing': 0,
        'failed_in_reprocessing': 0,
    }


def test_build_activity_payload_groups_high_volume_logs():
    session = build_session()
    campaign = Campaign(name='Atividade', message_template='Oi {{nome}}', status='completed')
    session.add(campaign)
    session.commit()
    session.refresh(campaign)

    log_event(session, campaign.id, None, 'campaign_state_change', 'campaign running')
    log_event(session, campaign.id, None, 'campaign_state_change', 'campaign paused')
    log_event(session, campaign.id, None, 'campaign_state_change', 'campaign resumed')
    log_event(session, campaign.id, None, 'campaign_state_change', 'campaign completed')
    for _ in range(3):
        log_event(session, campaign.id, None, 'retry_scheduled', 'temporary')
    for _ in range(12):
        log_event(session, campaign.id, None, 'send_failure', 'bridge_unreachable', 503, 'temporary')
    for _ in range(1000):
        log_event(session, campaign.id, None, 'send_success', 'delivered')
    session.commit()

    payload = build_activity_payload(session, campaign.id)

    assert payload['total_events'] == 1019
    assert any(card['label'] == 'Entregas confirmadas' and card['count'] == 1000 for card in payload['summary_cards'])
    assert any(item['summary'] == 'Sistema de envio indisponivel' and item['count'] == 12 for item in payload['incidents'])
    assert len(payload['milestones']) <= 6
    assert any(item['title'] == 'Campanha concluida' for item in payload['milestones'])
    assert any(item['title'] == 'Campanha iniciada' for item in payload['milestones'])
    assert any(item['title'] == 'Lote processado' and '1.000' in item['summary'] for item in payload['milestones'])
    assert any(item['title'] == 'Pico de falhas' for item in payload['milestones'])


def test_build_activity_payload_humanizes_incidents_and_groups_by_fingerprint():
    session = build_session()
    campaign = Campaign(name='Incidentes', message_template='Oi {{nome}}', status='paused')
    session.add(campaign)
    session.commit()
    session.refresh(campaign)

    log_event(
        session,
        campaign.id,
        None,
        'retry_scheduled',
        'Temporário: {"ok":false,"message":"Attempted to use detached Frame \\"frame-1\\".","state":"ready"}',
        502,
        'temporary',
    )
    log_event(
        session,
        campaign.id,
        None,
        'retry_scheduled',
        'Temporário: {"ok":false,"message":"Attempted to use detached Frame \\"frame-2\\".","state":"ready"}',
        502,
        'temporary',
    )
    log_event(
        session,
        campaign.id,
        None,
        'campaign_auto_paused_consecutive_failures',
        'A campanha foi pausada apos 5 falhas consecutivas.',
    )
    session.commit()

    payload = build_activity_payload(session, campaign.id)

    detached = next(item for item in payload['incidents'] if item['fingerprint'].endswith('bridge_session_detached:502'))
    assert detached['count'] == 2
    assert detached['human_title'] == 'Sessao do WhatsApp instavel'
    assert detached['technical_detail_available'] is True
    assert 'Reinicie a sessao do WhatsApp' in detached['recommended_action']

    paused = next(item for item in payload['incidents'] if item['fingerprint'].endswith('consecutive_failures_pause:-'))
    assert paused['human_summary'] == 'O sistema interrompeu a campanha apos uma sequencia anormal de falhas.'
