from __future__ import annotations

import asyncio
import random
from collections import deque
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from database import SessionLocal
from models import Campaign, Contact
from services.campaign_service import finalize_if_done, log_event, refresh_campaign_counters
from services.whatsapp import WhatsAppClient, WhatsAppError, is_bridge_session_healthy
from utils.daily_limit import daily_limit_reached, reset_daily_counters_if_needed
from utils.message_compose import render_campaign_message
from utils.schedule_guard import seconds_until_next_window, within_send_window


def processing_is_stale(last_attempt_at: datetime | None, now: datetime | None = None) -> bool:
    if last_attempt_at is None:
        return True

    current = now or datetime.now(timezone.utc)
    value = last_attempt_at
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return current - value > timedelta(minutes=2)


def now_local() -> datetime:
    return datetime.now(timezone.utc).astimezone()


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class SendEngine:
    def __init__(self) -> None:
        self._stop = False
        self._locks: set[int] = set()
        self._profiles: dict[int, dict] = {}
        self.client = WhatsAppClient()
        self._alert_sequence = 0
        self._latest_alert: dict | None = None
        self._worker_heartbeat_at: datetime | None = None
        self._bridge_last_check_at: datetime | None = None
        self._bridge_recovery_attempt_at: datetime | None = None
        self._service_status: dict[str, dict] = {
            'worker': {
                'key': 'worker',
                'label': 'Motor de envio',
                'state': 'operational',
                'message': 'Motor de envio operacional.',
                'checked_at': None,
            },
            'bridge': {
                'key': 'bridge',
                'label': 'WhatsApp / bridge',
                'state': 'unknown',
                'message': 'Verificando conectividade do WhatsApp.',
                'checked_at': None,
            },
        }

    def reset_campaign_runtime(self, campaign_id: int, hard: bool = False) -> None:
        if hard:
            self._profiles.pop(campaign_id, None)
            return

        profile = self._profiles.get(campaign_id)
        if profile is None:
            return
        profile['ok_streak'] = 0
        profile['err_streak'] = 0
        profile['consecutive_failures'] = 0
        profile['waiting_for_window'] = False
        profile['last_recovery_attempt_at'] = None
        profile['recovery_attempts'] = 0

    def has_active_campaigns(self) -> bool:
        with SessionLocal() as db:
            count = db.scalar(
                select(func.count(Campaign.id)).where(
                    (Campaign.status == 'running')
                    | ((Campaign.status == 'paused') & (Campaign.pause_reason == 'bridge_recovering'))
                )
            )
            return (count or 0) > 0

    async def run_forever(self) -> None:
        idle_backoff = 1.0
        max_idle_backoff = 15.0
        
        while not self._stop:
            self._mark_worker_heartbeat('Motor de envio operacional.')
            try:
                had_work = await self._run_once()
            except Exception as exc:
                self._set_service_status('worker', 'degraded', f'Falha interna no motor de envio: {str(exc)[:140]}')
                self._push_alert(
                    service='worker',
                    tone='warn',
                    title='Motor de envio instavel',
                    message='O motor de envio encontrou uma falha e sera reavaliado automaticamente.',
                )
                had_work = False

            if had_work:
                idle_backoff = 1.0
                await asyncio.sleep(1.0)
            else:
                await asyncio.sleep(idle_backoff)
                idle_backoff = min(idle_backoff * 1.5, max_idle_backoff)

    async def _run_once(self) -> bool:
        with SessionLocal() as db:
            running_campaigns = db.scalars(
                select(Campaign).where(
                    (Campaign.status == 'running')
                    | ((Campaign.status == 'paused') & (Campaign.pause_reason == 'bridge_recovering'))
                )
            ).all()
            ids = [c.id for c in running_campaigns if c.id not in self._locks]

        tasks = [asyncio.create_task(self._process_campaign(campaign_id)) for campaign_id in ids]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
            return True
        return False

    async def _process_campaign(self, campaign_id: int) -> None:
        self._locks.add(campaign_id)
        profile = self._profiles.setdefault(
            campaign_id,
            {
                'batch_size': None,
                'ok_streak': 0,
                'err_streak': 0,
                'consecutive_failures': 0,
                'waiting_for_window': False,
                'last_recovery_attempt_at': None,
                'recovery_attempts': 0,
            },
        )

        try:
            current_local = now_local()
            with SessionLocal() as db:
                campaign = db.get(Campaign, campaign_id)
                if campaign is None:
                    return
                self._sync_runtime_profile(profile, campaign)
                if campaign.status == 'paused' and campaign.pause_reason == 'bridge_recovering':
                    pass
                elif campaign.status != 'running':
                    return
                reset_daily_counters_if_needed(campaign, current_local)
                db.add(campaign)

                if campaign.status == 'paused' and campaign.pause_reason == 'bridge_recovering':
                    db.commit()
                    recovered = await self._recover_bridge_session(campaign_id, profile)
                    if not recovered:
                        return
                    return
                else:
                    db.commit()

                window_start = int(campaign.send_window_start_hour or 8)
                window_end = int(campaign.send_window_end_hour or 20)
                if not within_send_window(current_local, window_start, window_end):
                    if not profile['waiting_for_window']:
                        log_event(
                            db,
                            campaign_id,
                            None,
                            'send_window_wait',
                            f'Envio aguardando a janela operacional de {window_start:02d}h a {window_end:02d}h.',
                        )
                        profile['waiting_for_window'] = True
                    db.commit()
                    await asyncio.sleep(min(60, seconds_until_next_window(current_local, window_start, window_end)))
                    return
                profile['waiting_for_window'] = False

                if daily_limit_reached(campaign):
                    campaign.status = 'paused'
                    campaign.pause_reason = 'daily_limit_reached'
                    db.add(campaign)
                    log_event(db, campaign_id, None, 'campaign_auto_paused_daily_limit', 'Limite diario de envios atingido.')
                    db.commit()
                    return

                stuck_contacts = db.scalars(
                    select(Contact).where(Contact.campaign_id == campaign_id, Contact.status == 'processing')
                ).all()
                recovered = False
                for contact in stuck_contacts:
                    if processing_is_stale(contact.last_attempt_at):
                        contact.status = 'pending'
                        db.add(contact)
                        recovered = True
                if recovered:
                    self._mark_worker_heartbeat('Motor de envio operacional.')
                    db.commit()

                contacts = db.scalars(
                    select(Contact)
                    .where(Contact.campaign_id == campaign_id, Contact.status == 'pending')
                    .limit(profile['batch_size'])
                ).all()

                contact_ids = [contact.id for contact in contacts]
                for contact in contacts:
                    contact.status = 'processing'
                    db.add(contact)
                db.commit()

            if not contact_ids:
                with SessionLocal() as db:
                    finalize_if_done(db, campaign_id)
                    refresh_campaign_counters(db, campaign_id)
                    db.commit()
                self._mark_worker_heartbeat('Motor de envio operacional.')
                await asyncio.sleep(1)
                return

            sent_in_batch = 0
            failed_in_batch = 0
            recovery_interrupted_batch = False
            attempted_contact_ids: list[int] = []
            for contact_id in contact_ids:
                if profile['consecutive_failures'] >= 5:
                    break
                attempted_contact_ids.append(contact_id)
                result = await self._send_single(campaign_id, contact_id)
                if result == 'sent':
                    sent_in_batch += 1
                    profile['consecutive_failures'] = 0
                    self._mark_worker_heartbeat('Motor de envio operacional.')
                elif result == 'session_broken':
                    profile['consecutive_failures'] = 0
                    recovery_interrupted_batch = True
                    await self._pause_for_bridge_recovery(campaign_id)
                    recovered = await self._recover_bridge_session(campaign_id, profile)
                    if not recovered:
                        break
                    break
                else:
                    failed_in_batch += 1
                    profile['consecutive_failures'] += 1
                    self._mark_worker_heartbeat('Motor de envio operacional.')
                if profile['consecutive_failures'] >= 5:
                    with SessionLocal() as db:
                        campaign = db.get(Campaign, campaign_id)
                        if campaign is not None and campaign.status == 'running':
                            campaign.status = 'paused'
                            campaign.pause_reason = 'consecutive_failures'
                            db.add(campaign)
                            log_event(
                                db,
                                campaign_id,
                                None,
                                'campaign_auto_paused_consecutive_failures',
                                'A campanha foi pausada apos 5 falhas consecutivas.',
                            )
                            db.commit()
                    break
                with SessionLocal() as db:
                    campaign = db.get(Campaign, campaign_id)
                    if campaign is None or campaign.status != 'running':
                        break
                    current_local = now_local()
                    reset_daily_counters_if_needed(campaign, current_local)
                    db.add(campaign)
                    if daily_limit_reached(campaign):
                        campaign.status = 'paused'
                        campaign.pause_reason = 'daily_limit_reached'
                        db.add(campaign)
                        log_event(db, campaign_id, None, 'campaign_auto_paused_daily_limit', 'Limite diario de envios atingido.')
                        db.commit()
                        break
                    db.commit()
                    await asyncio.sleep(random.uniform(campaign.send_delay_min_seconds, campaign.send_delay_max_seconds))

            remaining_contact_ids = [contact_id for contact_id in contact_ids if contact_id not in attempted_contact_ids]
            if remaining_contact_ids:
                self._requeue_unattempted_contacts(campaign_id, remaining_contact_ids)

            if failed_in_batch == 0:
                profile['ok_streak'] += 1
                profile['err_streak'] = 0
                if (
                    profile['ok_streak'] >= int(profile['batch_growth_streak_required'])
                    and profile['batch_size'] < int(profile['batch_size_max'])
                ):
                    profile['batch_size'] = min(
                        int(profile['batch_size_max']),
                        int(profile['batch_size']) + int(profile['batch_growth_step']),
                    )
                    profile['ok_streak'] = 0
            else:
                profile['err_streak'] += 1
                profile['ok_streak'] = 0
                if profile['err_streak'] >= int(profile['batch_shrink_error_streak_required']):
                    profile['batch_size'] = max(
                        int(profile['batch_size_floor']),
                        int(profile['batch_size']) - int(profile['batch_shrink_step']),
                    )

            if recovery_interrupted_batch:
                await asyncio.sleep(1)
            else:
                with SessionLocal() as db:
                    campaign = db.get(Campaign, campaign_id)
                    if campaign is not None:
                        self._sync_runtime_profile(profile, campaign)
                        pause_min = int(campaign.batch_pause_min_seconds)
                        pause_max = int(campaign.batch_pause_max_seconds)
                    else:
                        pause_min = 25
                        pause_max = 40
                await asyncio.sleep(random.uniform(pause_min, pause_max))
        finally:
            self._locks.discard(campaign_id)

    def _requeue_unattempted_contacts(self, campaign_id: int, contact_ids: list[int]) -> None:
        if not contact_ids:
            return
        with SessionLocal() as db:
            contacts = db.scalars(
                select(Contact).where(Contact.campaign_id == campaign_id, Contact.id.in_(contact_ids), Contact.status == 'processing')
            ).all()
            for contact in contacts:
                contact.status = 'pending'
                db.add(contact)
            if contacts:
                refresh_campaign_counters(db, campaign_id)
                db.commit()

    def _sync_runtime_profile(self, profile: dict, campaign: Campaign) -> None:
        profile['batch_size_max'] = int(campaign.batch_size_max)
        profile['batch_growth_step'] = int(campaign.batch_growth_step)
        profile['batch_growth_streak_required'] = int(campaign.batch_growth_streak_required)
        profile['batch_shrink_step'] = int(campaign.batch_shrink_step)
        profile['batch_shrink_error_streak_required'] = int(campaign.batch_shrink_error_streak_required)
        profile['batch_size_floor'] = int(campaign.batch_size_floor)
        current_batch = profile.get('batch_size')
        if current_batch is None:
            profile['batch_size'] = int(campaign.batch_size_initial)
            return
        profile['batch_size'] = max(
            int(campaign.batch_size_floor),
            min(int(current_batch), int(campaign.batch_size_max)),
        )

    async def _pause_for_bridge_recovery(self, campaign_id: int) -> None:
        with SessionLocal() as db:
            campaign = db.get(Campaign, campaign_id)
            if campaign is None:
                return
            if campaign.status == 'paused' and campaign.pause_reason == 'bridge_recovering':
                return
            campaign.status = 'paused'
            campaign.pause_reason = 'bridge_recovering'
            db.add(campaign)
            log_event(
                db,
                campaign_id,
                None,
                'campaign_auto_paused_bridge_recovery',
                'A campanha entrou em pausa inteligente para recuperar a sessao do WhatsApp automaticamente.',
            )
            db.commit()

    async def _resume_after_bridge_recovery(self, campaign_id: int) -> None:
        with SessionLocal() as db:
            campaign = db.get(Campaign, campaign_id)
            if campaign is None:
                return
            if campaign.status == 'running' and campaign.pause_reason is None:
                return
            campaign.status = 'running'
            campaign.pause_reason = None
            db.add(campaign)
            log_event(
                db,
                campaign_id,
                None,
                'campaign_auto_resumed_bridge_recovery',
                'A sessao do WhatsApp voltou a ficar saudavel e a campanha retomou automaticamente.',
            )
            db.commit()

    async def _recover_bridge_session(self, campaign_id: int, profile: dict) -> bool:
        try:
            session = await self.client.bridge_session()
        except Exception:
            session = None

        if is_bridge_session_healthy(session):
            profile['last_recovery_attempt_at'] = None
            profile['recovery_attempts'] = 0
            await self._resume_after_bridge_recovery(campaign_id)
            return True

        current_time = datetime.now(timezone.utc)
        last_attempt = profile.get('last_recovery_attempt_at')
        should_restart = last_attempt is None or (current_time - last_attempt) >= timedelta(seconds=10)
        if should_restart:
            try:
                await self.client.bridge_restart()
                profile['last_recovery_attempt_at'] = current_time
                profile['recovery_attempts'] = int(profile.get('recovery_attempts') or 0) + 1
                with SessionLocal() as db:
                    log_event(
                        db,
                        campaign_id,
                        None,
                        'bridge_session_recovery_started',
                        'O sistema detectou uma sessao quebrada e iniciou uma recuperacao automatica do WhatsApp.',
                    )
                    db.commit()
            except Exception as exc:
                with SessionLocal() as db:
                    log_event(
                        db,
                        campaign_id,
                        None,
                        'bridge_session_recovery_failed',
                        f'Falha ao reiniciar a sessao automaticamente: {str(exc)[:180]}',
                    )
                    db.commit()
                await asyncio.sleep(5)
                return False

        await asyncio.sleep(2)
        try:
            session = await self.client.bridge_session()
        except Exception:
            session = None

        if is_bridge_session_healthy(session):
            profile['last_recovery_attempt_at'] = None
            profile['recovery_attempts'] = 0
            await self._resume_after_bridge_recovery(campaign_id)
            return True

        await asyncio.sleep(5)
        return False

    async def _send_single(self, campaign_id: int, contact_id: int) -> str:
        with SessionLocal() as db:
            campaign = db.get(Campaign, campaign_id)
            contact = db.get(Contact, contact_id)
            if campaign is None or contact is None:
                return 'failed'
            if campaign.status != 'running':
                contact.status = 'pending'
                db.add(contact)
                db.commit()
                return 'failed'

            contact.attempt_count += 1
            contact.last_attempt_at = datetime.now(timezone.utc)
            message = render_campaign_message(campaign.message_template, contact.name, contact.id)
            log_event(db, campaign_id, contact.id, 'send_attempt', message[:160])
            db.commit()
            self._mark_worker_heartbeat('Motor de envio operacional.')

        try:
            with SessionLocal() as db:
                contact = db.get(Contact, contact_id)
                if contact is None:
                    return 'failed'
                await self.client.send_text(contact.phone_e164 or '', message)
                contact.status = 'sent'
                contact.sent_at = datetime.now(timezone.utc)
                contact.error_message = None
                campaign = db.get(Campaign, campaign_id)
                if campaign is not None:
                    current_local = now_local()
                    reset_daily_counters_if_needed(campaign, current_local)
                    campaign.sent_today += 1
                    campaign.last_send_date = current_local
                    db.add(campaign)
                db.add(contact)
                log_event(db, campaign_id, contact.id, 'send_success', 'delivered')
                refresh_campaign_counters(db, campaign_id)
                db.commit()
                self._mark_worker_heartbeat('Motor de envio operacional.')
            return 'sent'
        except WhatsAppError as exc:
            with SessionLocal() as db:
                contact = db.get(Contact, contact_id)
                if contact is None:
                    return 'failed'

                if exc.error_class == 'session':
                    contact.status = 'pending'
                    contact.error_message = 'Sessao do WhatsApp em recuperacao automatica.'
                    log_event(db, campaign_id, contact.id, 'bridge_session_broken', str(exc)[:200], exc.http_status, exc.error_class)
                    db.add(contact)
                    refresh_campaign_counters(db, campaign_id)
                    db.commit()
                    self._mark_worker_heartbeat('Motor de envio operacional.')
                    return 'session_broken'

                max_attempts = 3
                temporary = exc.error_class == 'temporary'
                if temporary and contact.attempt_count < max_attempts:
                    contact.status = 'pending'
                    contact.error_message = f'Temporário: {str(exc)[:200]}'
                    log_event(db, campaign_id, contact.id, 'retry_scheduled', contact.error_message, exc.http_status, exc.error_class)
                else:
                    contact.status = 'failed'
                    contact.error_message = str(exc)[:200]
                    log_event(db, campaign_id, contact.id, 'send_failure', contact.error_message, exc.http_status, exc.error_class)

                db.add(contact)
                refresh_campaign_counters(db, campaign_id)
                db.commit()
                self._mark_worker_heartbeat('Motor de envio operacional.')
            return 'failed'

    async def stop(self) -> None:
        self._stop = True

    def _set_service_status(self, key: str, state: str, message: str, checked_at: datetime | None = None) -> None:
        target = self._service_status.setdefault(
            key,
            {'key': key, 'label': key, 'state': 'unknown', 'message': '', 'checked_at': None},
        )
        target['state'] = state
        target['message'] = message
        target['checked_at'] = (checked_at or now_utc()).isoformat()

    def _push_alert(self, service: str, tone: str, title: str, message: str) -> None:
        import hashlib
        alert_id = hashlib.md5(f"{service}-{title}-{message}".encode()).hexdigest()
        self._latest_alert = {
            'id': alert_id,
            'service': service,
            'tone': tone,
            'title': title,
            'message': message,
            'created_at': now_utc().isoformat(),
        }

    def _mark_worker_heartbeat(self, message: str) -> None:
        self._worker_heartbeat_at = now_utc()
        self._set_service_status('worker', 'operational', message, checked_at=self._worker_heartbeat_at)

    def worker_heartbeat_stale(self, now: datetime | None = None, threshold_seconds: int = 20) -> bool:
        heartbeat = self._worker_heartbeat_at
        if heartbeat is None:
            return False
        reference = now or now_utc()
        return (reference - heartbeat) > timedelta(seconds=threshold_seconds)

    def has_active_campaigns(self) -> bool:
        with SessionLocal() as db:
            running = db.scalar(
                select(Campaign.id).where(
                    (Campaign.status == 'running')
                    | ((Campaign.status == 'paused') & (Campaign.pause_reason.in_(['bridge_recovering', 'worker_recovering'])))
                ).limit(1)
            )
        return running is not None

    def service_health_snapshot(self) -> dict:
        services = {
            key: {
                'key': value.get('key', key),
                'label': value.get('label', key),
                'state': value.get('state', 'unknown'),
                'message': value.get('message', ''),
                'checked_at': value.get('checked_at'),
            }
            for key, value in self._service_status.items()
        }
        return {
            'services': services,
            'latest_alert': dict(self._latest_alert) if self._latest_alert else None,
        }

    async def pause_campaigns_for_worker_recovery(self, reason: str) -> int:
        paused = 0
        with SessionLocal() as db:
            campaigns = db.scalars(select(Campaign).where(Campaign.status == 'running')).all()
            for campaign in campaigns:
                processing_contacts = db.scalars(
                    select(Contact).where(Contact.campaign_id == campaign.id, Contact.status == 'processing')
                ).all()
                for contact in processing_contacts:
                    contact.status = 'pending'
                    db.add(contact)
                campaign.status = 'paused'
                campaign.pause_reason = 'worker_recovering'
                db.add(campaign)
                log_event(
                    db,
                    campaign.id,
                    None,
                    'campaign_auto_paused_worker_recovery',
                    reason[:200],
                )
                paused += 1
            if paused:
                db.commit()
        if paused:
            self._set_service_status('worker', 'recovering', 'Motor de envio em recuperacao automatica.')
            self._push_alert(
                service='worker',
                tone='warn',
                title='Motor de envio interrompido',
                message='O envio foi pausado automaticamente para recuperar o motor de envio.',
            )
        return paused

    async def resume_campaigns_after_worker_recovery(self) -> int:
        resumed = 0
        with SessionLocal() as db:
            campaigns = db.scalars(
                select(Campaign).where(Campaign.status == 'paused', Campaign.pause_reason == 'worker_recovering')
            ).all()
            for campaign in campaigns:
                campaign.status = 'running'
                campaign.pause_reason = None
                db.add(campaign)
                log_event(
                    db,
                    campaign.id,
                    None,
                    'campaign_auto_resumed_worker_recovery',
                    'O motor de envio foi recuperado e a campanha retomou automaticamente.',
                )
                resumed += 1
            if resumed:
                db.commit()
        if resumed:
            self._mark_worker_heartbeat('Motor de envio operacional.')
            self._push_alert(
                service='worker',
                tone='success',
                title='Motor recuperado',
                message='O motor de envio foi recuperado e a campanha retomou automaticamente.',
            )
        return resumed

    async def monitor_bridge_service(self) -> None:
        if getattr(self.client, 'provider', '') != 'bridge':
            self._set_service_status('bridge', 'operational', 'Provider ativo nao depende de wa-bridge.')
            return

        has_active_campaigns = self.has_active_campaigns()

        reachable, reason = await self.client.healthcheck()
        self._bridge_last_check_at = now_utc()
        if not reachable:
            self._set_service_status('bridge', 'recovering', reason, checked_at=self._bridge_last_check_at)
            if has_active_campaigns:
                await self._pause_running_campaigns_for_bridge_recovery(reason)
                await self._attempt_bridge_restart()
            return

        try:
            session = await self.client.bridge_session()
        except Exception as exc:
            self._set_service_status('bridge', 'recovering', f'Bridge instavel: {str(exc)[:140]}', checked_at=self._bridge_last_check_at)
            if has_active_campaigns:
                await self._pause_running_campaigns_for_bridge_recovery('Bridge instavel. O sistema iniciou recuperacao automatica.')
                await self._attempt_bridge_restart()
            return

        if is_bridge_session_healthy(session):
            self._set_service_status('bridge', 'operational', 'WhatsApp conectado e pronto para envio.', checked_at=self._bridge_last_check_at)
            resumed = await self._resume_campaigns_after_bridge_recovery()
            if resumed:
                self._push_alert(
                    service='bridge',
                    tone='success',
                    title='WhatsApp recuperado',
                    message='O servico do WhatsApp voltou a responder e a campanha retomou automaticamente.',
                )
            return

        self._set_service_status('bridge', 'recovering', 'Sessao do WhatsApp instavel. Tentando recuperar automaticamente.', checked_at=self._bridge_last_check_at)
        if has_active_campaigns:
            await self._pause_running_campaigns_for_bridge_recovery('Sessao do WhatsApp instavel. Recuperacao automatica em andamento.')
            await self._attempt_bridge_restart()

    async def _pause_running_campaigns_for_bridge_recovery(self, reason: str) -> int:
        paused = 0
        with SessionLocal() as db:
            campaigns = db.scalars(select(Campaign).where(Campaign.status == 'running')).all()
            for campaign in campaigns:
                processing_contacts = db.scalars(
                    select(Contact).where(Contact.campaign_id == campaign.id, Contact.status == 'processing')
                ).all()
                for contact in processing_contacts:
                    contact.status = 'pending'
                    db.add(contact)
                campaign.status = 'paused'
                campaign.pause_reason = 'bridge_recovering'
                db.add(campaign)
                log_event(db, campaign.id, None, 'campaign_auto_paused_bridge_recovery', reason[:200])
                paused += 1
            if paused:
                db.commit()
        if paused:
            self._push_alert(
                service='bridge',
                tone='warn',
                title='WhatsApp indisponivel',
                message='O envio foi pausado automaticamente porque o servico do WhatsApp ficou indisponivel.',
            )
        return paused

    async def _resume_campaigns_after_bridge_recovery(self) -> int:
        resumed = 0
        with SessionLocal() as db:
            campaigns = db.scalars(
                select(Campaign).where(Campaign.status == 'paused', Campaign.pause_reason == 'bridge_recovering')
            ).all()
            for campaign in campaigns:
                campaign.status = 'running'
                campaign.pause_reason = None
                db.add(campaign)
                log_event(
                    db,
                    campaign.id,
                    None,
                    'campaign_auto_resumed_bridge_recovery',
                    'A sessao do WhatsApp voltou a responder e a campanha retomou automaticamente.',
                )
                resumed += 1
            if resumed:
                db.commit()
        return resumed

    async def _attempt_bridge_restart(self) -> bool:
        current = now_utc()
        last_attempt = self._bridge_recovery_attempt_at
        if last_attempt is not None and (current - last_attempt) < timedelta(seconds=10):
            return False
        self._bridge_recovery_attempt_at = current
        try:
            await self.client.bridge_restart()
            self._set_service_status('bridge', 'recovering', 'Bridge respondeu ao comando de recuperacao automatica.', checked_at=current)
            self._push_alert(
                service='bridge',
                tone='warn',
                title='Recuperando WhatsApp',
                message='O sistema detectou a falha e esta tentando recuperar o servico do WhatsApp.',
            )
            return True
        except Exception as exc:
            local_restart = False
            if hasattr(self.client, 'bridge_restart_local_process'):
                try:
                    local_restart = bool(await self.client.bridge_restart_local_process())
                except Exception:
                    local_restart = False
            if local_restart:
                self._set_service_status(
                    'bridge',
                    'recovering',
                    'O processo local do wa-bridge foi reiniciado automaticamente.',
                    checked_at=current,
                )
                self._push_alert(
                    service='bridge',
                    tone='warn',
                    title='Recuperando WhatsApp',
                    message='O wa-bridge caiu, foi reiniciado automaticamente e a campanha sera retomada quando a conexao estabilizar.',
                )
                return True
            self._set_service_status('bridge', 'down', f'Falha ao recuperar bridge: {str(exc)[:140]}', checked_at=current)
            self._push_alert(
                service='bridge',
                tone='error',
                title='Falha ao recuperar WhatsApp',
                message='A tentativa automatica de recuperar o servico do WhatsApp falhou.',
            )
            return False
