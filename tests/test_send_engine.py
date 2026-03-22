from datetime import datetime, timedelta, timezone

import asyncio

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models import Campaign, Contact, SendLog
from services import send_engine
from services.send_engine import processing_is_stale


def test_processing_is_stale_when_missing_timestamp():
    assert processing_is_stale(None) is True


def test_processing_is_stale_after_threshold():
    now = datetime(2026, 3, 18, 12, 0, tzinfo=timezone.utc)
    last_attempt = now - timedelta(minutes=3)
    assert processing_is_stale(last_attempt, now=now) is True


def test_processing_is_not_stale_before_threshold():
    now = datetime(2026, 3, 18, 12, 0, tzinfo=timezone.utc)
    last_attempt = now - timedelta(seconds=30)
    assert processing_is_stale(last_attempt, now=now) is False


def test_process_campaign_sends_without_detached_instance(monkeypatch):
    engine = create_engine('sqlite:///:memory:', future=True)
    Session = sessionmaker(bind=engine, future=True)
    Base.metadata.create_all(engine)

    session = Session()
    campaign = Campaign(name='Teste', message_template='Oi, {{nome}}', status='running', is_test_required=0)
    session.add(campaign)
    session.commit()
    session.refresh(campaign)
    campaign_id = campaign.id

    contact = Contact(
        campaign_id=campaign_id,
        name='Contato',
        phone_raw='11999998888',
        phone_e164='+5511999998888',
        email='contato@teste.com',
        status='pending',
    )
    session.add(contact)
    session.commit()
    contact_id = contact.id
    session.close()

    class FakeClient:
        async def send_text(self, phone_e164: str, text: str) -> None:
            assert phone_e164 == '+5511999998888'
            assert 'Contato' in text

    monkeypatch.setattr(send_engine, 'SessionLocal', Session)
    monkeypatch.setattr(send_engine, 'now_local', lambda: datetime(2026, 3, 19, 10, 0, tzinfo=timezone.utc))
    monkeypatch.setattr(send_engine.random, 'uniform', lambda _a, _b: 0)

    async def fake_sleep(_seconds):
        return None

    monkeypatch.setattr(send_engine.asyncio, 'sleep', fake_sleep)

    engine_worker = send_engine.SendEngine()
    engine_worker.client = FakeClient()

    asyncio.run(engine_worker._process_campaign(campaign_id))

    check = Session()
    saved = check.get(Contact, contact_id)
    assert saved.status == 'sent'
    assert saved.sent_at is not None


def test_process_campaign_waits_outside_window_and_logs_once(monkeypatch):
    engine = create_engine('sqlite:///:memory:', future=True)
    Session = sessionmaker(bind=engine, future=True)
    Base.metadata.create_all(engine)

    session = Session()
    campaign = Campaign(name='Janela', message_template='Oi, {{nome}}', status='running', is_test_required=0)
    session.add(campaign)
    session.commit()
    session.refresh(campaign)
    campaign_id = campaign.id
    session.add(
        Contact(
            campaign_id=campaign_id,
            name='Contato',
            phone_raw='11999998888',
            phone_e164='+5511999998888',
            email='contato@teste.com',
            status='pending',
        )
    )
    session.commit()
    session.close()

    monkeypatch.setattr(send_engine, 'SessionLocal', Session)
    monkeypatch.setattr(send_engine, 'now_local', lambda: datetime(2026, 3, 19, 21, 0, tzinfo=timezone.utc))

    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(send_engine.asyncio, 'sleep', fake_sleep)

    engine_worker = send_engine.SendEngine()
    asyncio.run(engine_worker._process_campaign(campaign_id))
    asyncio.run(engine_worker._process_campaign(campaign_id))

    check = Session()
    logs = check.query(SendLog).filter(SendLog.campaign_id == campaign_id, SendLog.event_type == 'send_window_wait').all()
    contact = check.query(Contact).filter(Contact.campaign_id == campaign_id).one()

    assert len(logs) == 1
    assert contact.status == 'pending'
    assert sleeps


def test_process_campaign_pauses_after_five_consecutive_failures(monkeypatch):
    engine = create_engine('sqlite:///:memory:', future=True)
    Session = sessionmaker(bind=engine, future=True)
    Base.metadata.create_all(engine)

    session = Session()
    campaign = Campaign(name='Falhas', message_template='Oi, {{nome}}', status='running', is_test_required=0)
    session.add(campaign)
    session.commit()
    session.refresh(campaign)
    campaign_id = campaign.id

    for index in range(5):
        session.add(
            Contact(
                campaign_id=campaign_id,
                name=f'Contato {index}',
                phone_raw=f'1199999888{index}',
                phone_e164=f'+551199999888{index}',
                email=f'contato{index}@teste.com',
                status='pending',
            )
        )
    session.commit()
    session.close()

    class FakeClient:
        async def send_text(self, phone_e164: str, text: str) -> None:
            raise send_engine.WhatsAppError('falha temporaria', 503, 'temporary')

    monkeypatch.setattr(send_engine, 'SessionLocal', Session)
    monkeypatch.setattr(send_engine, 'now_local', lambda: datetime(2026, 3, 19, 10, 0, tzinfo=timezone.utc))

    async def fake_sleep(_seconds):
        return None

    monkeypatch.setattr(send_engine.asyncio, 'sleep', fake_sleep)
    monkeypatch.setattr(send_engine.random, 'uniform', lambda _a, _b: 0)

    engine_worker = send_engine.SendEngine()
    engine_worker.client = FakeClient()
    engine_worker._profiles[campaign_id] = {'batch_size': 5, 'ok_streak': 0, 'err_streak': 0, 'consecutive_failures': 0, 'waiting_for_window': False}

    asyncio.run(engine_worker._process_campaign(campaign_id))

    check = Session()
    refreshed_campaign = check.get(Campaign, campaign_id)
    logs = check.query(SendLog).filter(
        SendLog.campaign_id == campaign_id,
        SendLog.event_type == 'campaign_auto_paused_consecutive_failures',
    ).all()

    assert refreshed_campaign.status == 'paused'
    assert refreshed_campaign.pause_reason == 'consecutive_failures'
    assert len(logs) == 1


def test_process_campaign_requeues_unattempted_contacts_after_auto_pause(monkeypatch):
    engine = create_engine('sqlite:///:memory:', future=True)
    Session = sessionmaker(bind=engine, future=True)
    Base.metadata.create_all(engine)

    session = Session()
    campaign = Campaign(name='Falhas em lote', message_template='Oi, {{nome}}', status='running', is_test_required=0)
    session.add(campaign)
    session.commit()
    session.refresh(campaign)
    campaign_id = campaign.id

    for index in range(10):
        session.add(
            Contact(
                campaign_id=campaign_id,
                name=f'Contato {index}',
                phone_raw=f'1199999888{index}',
                phone_e164=f'+551199999888{index}',
                email=f'contato{index}@teste.com',
                status='pending',
            )
        )
    session.commit()
    session.close()

    class FakeClient:
        async def send_text(self, phone_e164: str, text: str) -> None:
            raise send_engine.WhatsAppError('falha temporaria', 503, 'temporary')

    monkeypatch.setattr(send_engine, 'SessionLocal', Session)
    monkeypatch.setattr(send_engine, 'now_local', lambda: datetime(2026, 3, 19, 10, 0, tzinfo=timezone.utc))

    async def fake_sleep(_seconds):
        return None

    monkeypatch.setattr(send_engine.asyncio, 'sleep', fake_sleep)
    monkeypatch.setattr(send_engine.random, 'uniform', lambda _a, _b: 0)

    engine_worker = send_engine.SendEngine()
    engine_worker.client = FakeClient()
    engine_worker._profiles[campaign_id] = {'batch_size': 10, 'ok_streak': 0, 'err_streak': 0, 'consecutive_failures': 0, 'waiting_for_window': False}

    asyncio.run(engine_worker._process_campaign(campaign_id))

    check = Session()
    processing_count = check.query(Contact).filter(Contact.campaign_id == campaign_id, Contact.status == 'processing').count()
    pending_count = check.query(Contact).filter(Contact.campaign_id == campaign_id, Contact.status == 'pending').count()

    assert processing_count == 0
    assert pending_count == 10


def test_reset_campaign_runtime_clears_consecutive_failures():
    engine_worker = send_engine.SendEngine()
    engine_worker._profiles[99] = {
        'batch_size': 12,
        'ok_streak': 1,
        'err_streak': 2,
        'consecutive_failures': 5,
        'waiting_for_window': True,
    }

    engine_worker.reset_campaign_runtime(99)

    assert engine_worker._profiles[99]['batch_size'] == 12
    assert engine_worker._profiles[99]['ok_streak'] == 0
    assert engine_worker._profiles[99]['err_streak'] == 0
    assert engine_worker._profiles[99]['consecutive_failures'] == 0
    assert engine_worker._profiles[99]['waiting_for_window'] is False


def test_process_campaign_increments_sent_today_and_pauses_at_daily_limit(monkeypatch):
    engine = create_engine('sqlite:///:memory:', future=True)
    Session = sessionmaker(bind=engine, future=True)
    Base.metadata.create_all(engine)

    session = Session()
    campaign = Campaign(
        name='Limite',
        message_template='Oi, {{nome}}',
        status='running',
        is_test_required=0,
        daily_limit=2,
        sent_today=1,
        last_send_date=datetime(2026, 3, 19, 9, 0, tzinfo=timezone.utc),
    )
    session.add(campaign)
    session.commit()
    session.refresh(campaign)
    campaign_id = campaign.id

    session.add(
        Contact(
            campaign_id=campaign_id,
            name='Contato',
            phone_raw='11999998888',
            phone_e164='+5511999998888',
            email='contato@teste.com',
            status='pending',
        )
    )
    session.commit()
    session.close()

    class FakeClient:
        async def send_text(self, phone_e164: str, text: str) -> None:
            return None

    monkeypatch.setattr(send_engine, 'SessionLocal', Session)
    monkeypatch.setattr(send_engine, 'now_local', lambda: datetime(2026, 3, 19, 10, 0, tzinfo=timezone.utc))

    async def fake_sleep(_seconds):
        return None

    monkeypatch.setattr(send_engine.asyncio, 'sleep', fake_sleep)
    monkeypatch.setattr(send_engine.random, 'uniform', lambda _a, _b: 0)

    engine_worker = send_engine.SendEngine()
    engine_worker.client = FakeClient()
    asyncio.run(engine_worker._process_campaign(campaign_id))

    check = Session()
    refreshed_campaign = check.get(Campaign, campaign_id)
    logs = check.query(SendLog).filter(
        SendLog.campaign_id == campaign_id,
        SendLog.event_type == 'campaign_auto_paused_daily_limit',
    ).all()

    assert refreshed_campaign.sent_today == 2
    assert refreshed_campaign.status == 'paused'
    assert refreshed_campaign.pause_reason == 'daily_limit_reached'
    assert len(logs) == 1


def test_process_campaign_uses_campaign_batch_defaults_and_pause_window(monkeypatch):
    engine = create_engine('sqlite:///:memory:', future=True)
    Session = sessionmaker(bind=engine, future=True)
    Base.metadata.create_all(engine)

    session = Session()
    campaign = Campaign(
        name='Agressiva',
        message_template='Oi, {{nome}}',
        status='running',
        is_test_required=0,
        batch_size_initial=15,
        batch_size_max=30,
        batch_growth_step=5,
        batch_growth_streak_required=2,
        batch_shrink_step=3,
        batch_shrink_error_streak_required=1,
        batch_size_floor=8,
        batch_pause_min_seconds=5,
        batch_pause_max_seconds=10,
    )
    session.add(campaign)
    session.commit()
    session.refresh(campaign)
    campaign_id = campaign.id

    for index in range(3):
        session.add(
            Contact(
                campaign_id=campaign_id,
                name=f'Contato {index}',
                phone_raw=f'1199999888{index}',
                phone_e164=f'+551199999888{index}',
                email=f'contato{index}@teste.com',
                status='pending',
            )
        )
    session.commit()
    session.close()

    class FakeClient:
        async def send_text(self, phone_e164: str, text: str) -> None:
            return None

    uniform_calls = []

    def fake_uniform(a, b):
        uniform_calls.append((a, b))
        return 0

    async def fake_sleep(_seconds):
        return None

    monkeypatch.setattr(send_engine, 'SessionLocal', Session)
    monkeypatch.setattr(send_engine, 'now_local', lambda: datetime(2026, 3, 19, 10, 0, tzinfo=timezone.utc))
    monkeypatch.setattr(send_engine.asyncio, 'sleep', fake_sleep)
    monkeypatch.setattr(send_engine.random, 'uniform', fake_uniform)

    engine_worker = send_engine.SendEngine()
    engine_worker.client = FakeClient()
    asyncio.run(engine_worker._process_campaign(campaign_id))

    runtime = engine_worker._profiles[campaign_id]
    assert runtime['batch_size'] == 15
    assert (5, 10) in uniform_calls


def test_process_campaign_pauses_for_bridge_recovery_when_session_breaks(monkeypatch):
    engine = create_engine('sqlite:///:memory:', future=True)
    Session = sessionmaker(bind=engine, future=True)
    Base.metadata.create_all(engine)

    session = Session()
    campaign = Campaign(name='Recuperacao', message_template='Oi, {{nome}}', status='running', is_test_required=0)
    session.add(campaign)
    session.commit()
    session.refresh(campaign)
    campaign_id = campaign.id

    session.add(
        Contact(
            campaign_id=campaign_id,
            name='Contato',
            phone_raw='11999998888',
            phone_e164='+5511999998888',
            email='contato@teste.com',
            status='pending',
        )
    )
    session.commit()
    session.close()

    class FakeClient:
        async def send_text(self, _phone_e164: str, _text: str) -> None:
            raise send_engine.WhatsAppError('Attempted to use detached Frame "frame-1".', 502, 'session')

        async def bridge_restart(self) -> dict:
            return {'ok': True}

        async def bridge_session(self) -> dict:
            return {'connected': True, 'state': 'ready', 'lastError': 'Attempted to use detached Frame "frame-1".'}

    monkeypatch.setattr(send_engine, 'SessionLocal', Session)
    monkeypatch.setattr(send_engine, 'now_local', lambda: datetime(2026, 3, 19, 10, 0, tzinfo=timezone.utc))
    monkeypatch.setattr(send_engine.random, 'uniform', lambda _a, _b: 0)

    async def fake_sleep(_seconds):
        return None

    monkeypatch.setattr(send_engine.asyncio, 'sleep', fake_sleep)

    engine_worker = send_engine.SendEngine()
    engine_worker.client = FakeClient()

    asyncio.run(engine_worker._process_campaign(campaign_id))

    check = Session()
    refreshed_campaign = check.get(Campaign, campaign_id)
    contact = check.query(Contact).filter(Contact.campaign_id == campaign_id).one()
    pause_logs = check.query(SendLog).filter(
        SendLog.campaign_id == campaign_id,
        SendLog.event_type == 'campaign_auto_paused_bridge_recovery',
    ).all()
    failure_pause_logs = check.query(SendLog).filter(
        SendLog.campaign_id == campaign_id,
        SendLog.event_type == 'campaign_auto_paused_consecutive_failures',
    ).all()

    assert refreshed_campaign.status == 'paused'
    assert refreshed_campaign.pause_reason == 'bridge_recovering'
    assert contact.status == 'pending'
    assert len(pause_logs) == 1
    assert len(failure_pause_logs) == 0


def test_process_campaign_auto_resumes_after_bridge_recovers(monkeypatch):
    engine = create_engine('sqlite:///:memory:', future=True)
    Session = sessionmaker(bind=engine, future=True)
    Base.metadata.create_all(engine)

    session = Session()
    campaign = Campaign(name='Recupera e envia', message_template='Oi, {{nome}}', status='running', is_test_required=0)
    session.add(campaign)
    session.commit()
    session.refresh(campaign)
    campaign_id = campaign.id

    session.add(
        Contact(
            campaign_id=campaign_id,
            name='Contato',
            phone_raw='11999998888',
            phone_e164='+5511999998888',
            email='contato@teste.com',
            status='pending',
        )
    )
    session.commit()
    session.close()

    class FakeClient:
        def __init__(self) -> None:
            self.send_calls = 0
            self.restart_calls = 0
            self.session_checks = 0

        async def send_text(self, _phone_e164: str, _text: str) -> None:
            self.send_calls += 1
            if self.send_calls == 1:
                raise send_engine.WhatsAppError('Attempted to use detached Frame "frame-1".', 502, 'session')
            return None

        async def bridge_restart(self) -> dict:
            self.restart_calls += 1
            return {'ok': True}

        async def bridge_session(self) -> dict:
            self.session_checks += 1
            if self.session_checks == 1:
                return {'connected': True, 'state': 'ready', 'lastError': 'Attempted to use detached Frame "frame-1".'}
            return {'connected': True, 'state': 'ready', 'lastError': ''}

    monkeypatch.setattr(send_engine, 'SessionLocal', Session)
    monkeypatch.setattr(send_engine, 'now_local', lambda: datetime(2026, 3, 19, 10, 0, tzinfo=timezone.utc))
    monkeypatch.setattr(send_engine.random, 'uniform', lambda _a, _b: 0)

    async def fake_sleep(_seconds):
        return None

    monkeypatch.setattr(send_engine.asyncio, 'sleep', fake_sleep)

    engine_worker = send_engine.SendEngine()
    fake_client = FakeClient()
    engine_worker.client = fake_client

    asyncio.run(engine_worker._process_campaign(campaign_id))
    asyncio.run(engine_worker._process_campaign(campaign_id))

    check = Session()
    refreshed_campaign = check.get(Campaign, campaign_id)
    contact = check.query(Contact).filter(Contact.campaign_id == campaign_id).one()
    pause_logs = check.query(SendLog).filter(
        SendLog.campaign_id == campaign_id,
        SendLog.event_type == 'campaign_auto_paused_bridge_recovery',
    ).all()
    resume_logs = check.query(SendLog).filter(
        SendLog.campaign_id == campaign_id,
        SendLog.event_type == 'campaign_auto_resumed_bridge_recovery',
    ).all()

    assert refreshed_campaign.status == 'running'
    assert refreshed_campaign.pause_reason is None
    assert contact.status == 'sent'
    assert fake_client.restart_calls >= 1
    assert len(pause_logs) == 1
    assert len(resume_logs) == 1


def test_worker_recovery_requeues_processing_contacts_and_auto_resumes(monkeypatch):
    engine = create_engine('sqlite:///:memory:', future=True)
    Session = sessionmaker(bind=engine, future=True)
    Base.metadata.create_all(engine)

    session = Session()
    campaign = Campaign(name='Motor', message_template='Oi, {{nome}}', status='running', is_test_required=0)
    session.add(campaign)
    session.commit()
    session.refresh(campaign)
    campaign_id = campaign.id

    session.add_all(
        [
            Contact(
                campaign_id=campaign_id,
                name='Travado',
                phone_raw='11999998888',
                phone_e164='+5511999998888',
                email='travado@teste.com',
                status='processing',
                last_attempt_at=datetime.now(timezone.utc),
            ),
            Contact(
                campaign_id=campaign_id,
                name='Pendente',
                phone_raw='11999998889',
                phone_e164='+5511999998889',
                email='pendente@teste.com',
                status='pending',
            ),
        ]
    )
    session.commit()
    session.close()

    monkeypatch.setattr(send_engine, 'SessionLocal', Session)

    engine_worker = send_engine.SendEngine()

    asyncio.run(engine_worker.pause_campaigns_for_worker_recovery('Motor de envio sem heartbeat.'))

    check = Session()
    refreshed_campaign = check.get(Campaign, campaign_id)
    contacts = check.query(Contact).filter(Contact.campaign_id == campaign_id).all()
    pause_logs = check.query(SendLog).filter(
        SendLog.campaign_id == campaign_id,
        SendLog.event_type == 'campaign_auto_paused_worker_recovery',
    ).all()

    assert refreshed_campaign.status == 'paused'
    assert refreshed_campaign.pause_reason == 'worker_recovering'
    assert all(contact.status == 'pending' for contact in contacts)
    assert len(pause_logs) == 1

    asyncio.run(engine_worker.resume_campaigns_after_worker_recovery())

    check.expire_all()
    resumed_campaign = check.get(Campaign, campaign_id)
    resume_logs = check.query(SendLog).filter(
        SendLog.campaign_id == campaign_id,
        SendLog.event_type == 'campaign_auto_resumed_worker_recovery',
    ).all()

    assert resumed_campaign.status == 'running'
    assert resumed_campaign.pause_reason is None
    assert len(resume_logs) == 1


def test_monitor_bridge_service_pauses_and_recovers_running_campaign(monkeypatch):
    engine = create_engine('sqlite:///:memory:', future=True)
    Session = sessionmaker(bind=engine, future=True)
    Base.metadata.create_all(engine)

    session = Session()
    campaign = Campaign(name='Bridge', message_template='Oi, {{nome}}', status='running', is_test_required=0)
    session.add(campaign)
    session.commit()
    session.refresh(campaign)
    campaign_id = campaign.id
    session.close()

    monkeypatch.setattr(send_engine, 'SessionLocal', Session)

    async def fake_sleep(_seconds):
        return None

    monkeypatch.setattr(send_engine.asyncio, 'sleep', fake_sleep)

    class FlappingClient:
        def __init__(self):
            self.calls = 0
            self.restart_calls = 0
            self.provider = 'bridge'
            self.configured = True

        async def healthcheck(self):
            self.calls += 1
            if self.calls == 1:
                return False, 'Bridge indisponivel (503)'
            return True, 'Bridge acessivel (ready)'

        async def bridge_session(self):
            if self.calls <= 1:
                return {'connected': False, 'state': 'disconnected'}
            return {'connected': True, 'state': 'ready', 'lastError': ''}

        async def bridge_restart(self):
            self.restart_calls += 1
            return {'ok': True}

    engine_worker = send_engine.SendEngine()
    engine_worker.client = FlappingClient()

    asyncio.run(engine_worker.monitor_bridge_service())

    check = Session()
    paused_campaign = check.get(Campaign, campaign_id)
    pause_logs = check.query(SendLog).filter(
        SendLog.campaign_id == campaign_id,
        SendLog.event_type == 'campaign_auto_paused_bridge_recovery',
    ).all()
    assert paused_campaign.status == 'paused'
    assert paused_campaign.pause_reason == 'bridge_recovering'
    assert len(pause_logs) == 1

    asyncio.run(engine_worker.monitor_bridge_service())

    check.expire_all()
    resumed_campaign = check.get(Campaign, campaign_id)
    resume_logs = check.query(SendLog).filter(
        SendLog.campaign_id == campaign_id,
        SendLog.event_type == 'campaign_auto_resumed_bridge_recovery',
    ).all()
    assert resumed_campaign.status == 'running'
    assert resumed_campaign.pause_reason is None
    assert len(resume_logs) == 1
    assert engine_worker.client.restart_calls == 1


def test_monitor_bridge_service_restarts_local_bridge_process_when_http_restart_fails(monkeypatch):
    engine = create_engine('sqlite:///:memory:', future=True)
    Session = sessionmaker(bind=engine, future=True)
    Base.metadata.create_all(engine)

    session = Session()
    campaign = Campaign(name='Bridge local', message_template='Oi, {{nome}}', status='running', is_test_required=0)
    session.add(campaign)
    session.commit()
    session.refresh(campaign)
    campaign_id = campaign.id
    session.close()

    monkeypatch.setattr(send_engine, 'SessionLocal', Session)

    async def fake_sleep(_seconds):
        return None

    monkeypatch.setattr(send_engine.asyncio, 'sleep', fake_sleep)

    class LocalRestartClient:
        def __init__(self):
            self.calls = 0
            self.restart_calls = 0
            self.local_restart_calls = 0
            self.provider = 'bridge'
            self.configured = True

        async def healthcheck(self):
            self.calls += 1
            if self.calls == 1:
                return False, 'Bridge indisponivel (503)'
            return True, 'Bridge acessivel (ready)'

        async def bridge_session(self):
            if self.calls <= 1:
                return {'connected': False, 'state': 'disconnected'}
            return {'connected': True, 'state': 'ready', 'lastError': ''}

        async def bridge_restart(self):
            self.restart_calls += 1
            raise RuntimeError('bridge offline')

        async def bridge_restart_local_process(self):
            self.local_restart_calls += 1
            return True

    engine_worker = send_engine.SendEngine()
    engine_worker.client = LocalRestartClient()

    asyncio.run(engine_worker.monitor_bridge_service())

    check = Session()
    paused_campaign = check.get(Campaign, campaign_id)
    assert paused_campaign.status == 'paused'
    assert paused_campaign.pause_reason == 'bridge_recovering'

    asyncio.run(engine_worker.monitor_bridge_service())

    check.expire_all()
    resumed_campaign = check.get(Campaign, campaign_id)
    assert resumed_campaign.status == 'running'
    assert resumed_campaign.pause_reason is None
    assert engine_worker.client.restart_calls == 1
    assert engine_worker.client.local_restart_calls == 1
