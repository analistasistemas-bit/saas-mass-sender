from __future__ import annotations

import csv
import io
import json
import re
from datetime import datetime, timezone
from typing import Iterable, Optional

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from models import Campaign, Contact, SendLog
from utils.csv_parser import parse_csv_bytes
from utils.daily_limit import daily_limit_reached
from utils.message_compose import render_campaign_message
from utils.phone import normalize_br_phone
from utils.speed_profiles import (
    DEFAULT_SPEED_PROFILE,
    SPEED_PROFILE_PRESETS,
    apply_speed_profile,
    campaign_profile_settings,
    normalize_speed_profile,
    resolve_speed_profile,
    runtime_profile_payload,
)

ALLOWED_STATUSES = {'draft', 'ready', 'running', 'paused', 'cancelled', 'completed'}
PERFORMANCE_WINDOW_SECONDS = 600
CONFIGURED_BATCH_PAUSE_MIN_SECONDS = SPEED_PROFILE_PRESETS[DEFAULT_SPEED_PROFILE]['batch_pause_min_seconds']
CONFIGURED_BATCH_PAUSE_MAX_SECONDS = SPEED_PROFILE_PRESETS[DEFAULT_SPEED_PROFILE]['batch_pause_max_seconds']
CONFIGURED_BATCH_SIZE_BASELINE = SPEED_PROFILE_PRESETS[DEFAULT_SPEED_PROFILE]['batch_size_initial']


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def ensure_aware_utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def to_iso_utc(value: Optional[datetime]) -> Optional[str]:
    aware = ensure_aware_utc(value)
    return aware.isoformat() if aware else None


def render_message(template: str, name: Optional[str]) -> str:
    safe_name = (name or '').strip() or 'cliente'
    return template.replace('{{nome}}', safe_name)


def create_campaign(db: Session, name: str) -> Campaign:
    campaign = Campaign(name=name.strip(), status='draft', message_template='Oi, {{nome}}')
    db.add(campaign)
    db.commit()
    db.refresh(campaign)
    return campaign


def delete_campaign(db: Session, campaign_id: int) -> dict:
    campaign = get_campaign_or_404(db, campaign_id)
    if campaign.status == 'running':
        return {'ok': False, 'message': 'Nao pode excluir uma campanha em envio ativo.'}

    db.delete(campaign)
    db.commit()
    return {'ok': True, 'message': 'Campanha excluida com sucesso.'}


def update_template(db: Session, campaign_id: int, message_template: str) -> Campaign:
    campaign = get_campaign_or_404(db, campaign_id)
    campaign.message_template = message_template
    if campaign.status == 'draft':
        campaign.status = 'ready'
    db.add(campaign)
    db.commit()
    db.refresh(campaign)
    log_event(db, campaign.id, None, 'campaign_state_change', f'template updated; status={campaign.status}')
    return campaign


def update_campaign_operational_settings(
    db: Session,
    campaign_id: int,
    send_delay_min_seconds: int,
    send_delay_max_seconds: int,
    daily_limit: int,
    speed_profile: str | None = None,
    batch_pause_min_seconds: int | None = None,
    batch_pause_max_seconds: int | None = None,
    send_window_start: str | None = None,
    send_window_end: str | None = None,
) -> tuple[bool, str, dict]:
    def parse_window_hour(value: str | None, label: str) -> tuple[int | None, str | None]:
        if value is None:
            return None, None
        raw = str(value).strip()
        parts = raw.split(':')
        if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
            return None, f'{label} deve estar no formato HH:MM.'
        hour = int(parts[0])
        minute = int(parts[1])
        if hour < 0 or hour > 23:
            return None, f'{label} deve estar entre 00:00 e 23:00.'
        if minute != 0:
            return None, f'{label} deve usar horas cheias (HH:00).'
        return hour, None

    if send_delay_min_seconds < 1:
        return False, 'Atraso minimo deve ser maior ou igual a 1 segundo.', {}
    if send_delay_max_seconds < send_delay_min_seconds:
        return False, 'Atraso maximo deve ser maior ou igual ao atraso minimo.', {}
    if send_delay_max_seconds > 3600:
        return False, 'Atraso maximo nao pode ultrapassar 3600 segundos.', {}
    if batch_pause_min_seconds is not None and batch_pause_min_seconds < 0:
        return False, 'Pausa minima entre lotes nao pode ser negativa.', {}
    if batch_pause_max_seconds is not None and batch_pause_min_seconds is not None and batch_pause_max_seconds < batch_pause_min_seconds:
        return False, 'Pausa maxima entre lotes deve ser maior ou igual a pausa minima.', {}
    if daily_limit < 0:
        return False, 'Limite diario nao pode ser negativo.', {}

    campaign = get_campaign_or_404(db, campaign_id)
    window_start_hour, start_error = parse_window_hour(send_window_start, 'Inicio da janela')
    if start_error:
        return False, start_error, {}
    window_end_hour, end_error = parse_window_hour(send_window_end, 'Fim da janela')
    if end_error:
        return False, end_error, {}
    if window_start_hour is None:
        window_start_hour = int(campaign.send_window_start_hour or 8)
    if window_end_hour is None:
        window_end_hour = int(campaign.send_window_end_hour or 20)
    if window_end_hour <= window_start_hour:
        return False, 'Fim da janela deve ser maior que o inicio da janela.', {}

    requested_profile = normalize_speed_profile(speed_profile)
    if requested_profile in SPEED_PROFILE_PRESETS:
        apply_speed_profile(campaign, requested_profile)
    campaign.send_delay_min_seconds = int(send_delay_min_seconds)
    campaign.send_delay_max_seconds = int(send_delay_max_seconds)
    if batch_pause_min_seconds is not None:
        campaign.batch_pause_min_seconds = int(batch_pause_min_seconds)
    if batch_pause_max_seconds is not None:
        campaign.batch_pause_max_seconds = int(batch_pause_max_seconds)
    campaign.send_window_start_hour = int(window_start_hour)
    campaign.send_window_end_hour = int(window_end_hour)
    campaign.daily_limit = int(daily_limit)
    campaign.speed_profile = resolve_speed_profile(campaign_profile_settings(campaign))
    db.add(campaign)
    db.commit()
    db.refresh(campaign)
    runtime_profile = runtime_profile_payload(campaign)
    log_event(
        db,
        campaign.id,
        None,
        'campaign_speed_profile_changed',
        (
            f'profile={campaign.speed_profile}; delay={campaign.send_delay_min_seconds}-{campaign.send_delay_max_seconds}; '
            f'batch_pause={campaign.batch_pause_min_seconds}-{campaign.batch_pause_max_seconds}; '
            f'window={campaign.send_window_start_hour:02d}:00-{campaign.send_window_end_hour:02d}:00; daily_limit={campaign.daily_limit}'
        ),
    )
    db.commit()
    return True, 'Configuracoes operacionais salvas.', {
        'speed_profile': campaign.speed_profile,
        'send_delay_min_seconds': campaign.send_delay_min_seconds,
        'send_delay_max_seconds': campaign.send_delay_max_seconds,
        'batch_pause_min_seconds': campaign.batch_pause_min_seconds,
        'batch_pause_max_seconds': campaign.batch_pause_max_seconds,
        'batch_size_initial': campaign.batch_size_initial,
        'batch_size_max': campaign.batch_size_max,
        'batch_growth_step': campaign.batch_growth_step,
        'batch_growth_streak_required': campaign.batch_growth_streak_required,
        'batch_shrink_step': campaign.batch_shrink_step,
        'batch_shrink_error_streak_required': campaign.batch_shrink_error_streak_required,
        'batch_size_floor': campaign.batch_size_floor,
        'send_window_start': f'{campaign.send_window_start_hour:02d}:00',
        'send_window_end': f'{campaign.send_window_end_hour:02d}:00',
        'daily_limit': campaign.daily_limit,
        'runtime_profile': runtime_profile,
    }


def get_campaign_or_404(db: Session, campaign_id: int) -> Campaign:
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise ValueError('Campanha não encontrada')
    return campaign


def _friendly_failure_reason(reason: Optional[str]) -> str:
    text = (reason or '').strip()
    lowered = text.lower()
    mapping = {
        'number_resolution_failed': 'Numero nao disponivel no WhatsApp',
        'bridge_unreachable': 'Sistema de envio indisponivel',
        'temporary': 'Falha temporaria',
        'permanent': 'Falha permanente',
    }
    for key, label in mapping.items():
        if key in lowered:
            return label
    if not text:
        return 'Falha sem detalhe'
    return text[:90]


def _fingerprint_http_status(http_status: Optional[int]) -> str:
    return str(http_status) if http_status is not None else '-'


def _parse_raw_error_payload(payload_excerpt: Optional[str]) -> tuple[Optional[dict], str]:
    text = (payload_excerpt or '').strip()
    if not text:
        return None, ''

    brace_index = text.find('{')
    candidate = text[brace_index:] if brace_index >= 0 else text
    try:
        parsed = json.loads(candidate)
        if isinstance(parsed, dict):
            return parsed, text
    except Exception:
        pass
    return None, text


def _extract_technical_summary(payload_excerpt: Optional[str]) -> str:
    parsed, raw_text = _parse_raw_error_payload(payload_excerpt)
    if parsed:
        for key in ('message', 'detail', 'error', 'code'):
            value = parsed.get(key)
            if value:
                return str(value)[:200]
    return raw_text[:200]


def _normalize_operational_issue(
    event_type: str,
    payload_excerpt: Optional[str],
    error_class: Optional[str],
    http_status: Optional[int],
) -> dict:
    technical_summary = _extract_technical_summary(payload_excerpt)
    lowered = technical_summary.lower()
    tone = _activity_tone(event_type)
    http_status_label = _fingerprint_http_status(http_status)

    if 'no lid for user' in lowered or 'number_resolution_failed' in lowered:
        return {
            'label': 'Numero nao disponivel no WhatsApp',
            'human_title': 'Numero sem identificacao valida',
            'human_summary': 'O numero nao foi resolvido pela sessao atual do WhatsApp.',
            'recommended_action': 'Confirme o numero, DDI/DDDs e se o contato realmente possui WhatsApp.',
            'technical_summary': technical_summary,
            'technical_detail_available': bool(technical_summary),
            'fingerprint': f'{event_type}:number_resolution_failed:{http_status_label}',
            'tone': 'warn' if event_type == 'invalid_contact' else tone,
        }

    if 'attempted to use detached frame' in lowered:
        return {
            'label': 'Sessao do WhatsApp instavel',
            'human_title': 'Sessao do WhatsApp instavel',
            'human_summary': 'A sessao conectada perdeu contexto interno e o envio falhou temporariamente.',
            'recommended_action': 'Reinicie a sessao do WhatsApp antes de retomar o envio.',
            'technical_summary': technical_summary,
            'technical_detail_available': True,
            'fingerprint': f'{event_type}:bridge_session_detached:{http_status_label}',
            'tone': tone,
        }

    if 'all connection attempts failed' in lowered or 'bridge_unreachable' in lowered:
        return {
            'label': 'Sistema de envio indisponivel',
            'human_title': 'Bridge indisponivel',
            'human_summary': 'O servico de envio nao respondeu no momento da tentativa.',
            'recommended_action': 'Verifique o wa-bridge e a conectividade local.',
            'technical_summary': technical_summary,
            'technical_detail_available': bool(technical_summary),
            'fingerprint': f'{event_type}:bridge_unreachable:{http_status_label}',
            'tone': tone,
        }

    if http_status == 429:
        return {
            'label': 'Limite temporario atingido',
            'human_title': 'Limite temporario atingido',
            'human_summary': 'O provedor recusou a tentativa por excesso ou limite temporario.',
            'recommended_action': 'Aguarde alguns minutos antes de insistir no envio.',
            'technical_summary': technical_summary,
            'technical_detail_available': bool(technical_summary),
            'fingerprint': f'{event_type}:provider_rate_limit:{http_status_label}',
            'tone': 'warn',
        }

    if event_type == 'campaign_auto_paused_daily_limit':
        return {
            'label': 'Pausa automatica por limite diario',
            'human_title': 'Pausa por limite diario',
            'human_summary': 'A campanha foi pausada porque atingiu o limite diario configurado.',
            'recommended_action': 'Retome apenas no proximo dia ou ajuste o limite antes disso.',
            'technical_summary': technical_summary or 'Limite diario de envios atingido.',
            'technical_detail_available': bool(technical_summary),
            'fingerprint': f'{event_type}:daily_limit_reached:{http_status_label}',
            'tone': 'warn',
        }

    if event_type == 'campaign_auto_paused_consecutive_failures':
        return {
            'label': 'Pausa automatica por falhas consecutivas',
            'human_title': 'Pausa por falhas consecutivas',
            'human_summary': 'O sistema interrompeu a campanha apos uma sequencia anormal de falhas.',
            'recommended_action': 'Revise os incidentes recentes antes de retomar.',
            'technical_summary': technical_summary or 'A campanha foi pausada apos 5 falhas consecutivas.',
            'technical_detail_available': bool(technical_summary),
            'fingerprint': f'{event_type}:consecutive_failures_pause:{http_status_label}',
            'tone': 'warn',
        }

    if event_type == 'campaign_auto_paused_worker_recovery':
        return {
            'label': 'Pausa automatica por recuperacao do motor',
            'human_title': 'Motor de envio em recuperacao',
            'human_summary': 'O sistema pausou temporariamente a campanha para recuperar o motor de envio.',
            'recommended_action': 'Aguarde a recuperacao automatica; a campanha retoma sozinha quando o motor estabilizar.',
            'technical_summary': technical_summary or 'A campanha foi pausada para recuperar o motor de envio.',
            'technical_detail_available': bool(technical_summary),
            'fingerprint': f'{event_type}:worker_recovery_pause:{http_status_label}',
            'tone': 'warn',
        }

    if event_type == 'campaign_auto_paused_bridge_recovery':
        return {
            'label': 'Pausa inteligente para recuperar sessao',
            'human_title': 'Recuperacao automatica da sessao',
            'human_summary': 'O sistema pausou a campanha para reparar automaticamente a sessao do WhatsApp.',
            'recommended_action': 'Acompanhe a retomada automatica ou revise o bridge se a recuperacao demorar.',
            'technical_summary': technical_summary or 'A campanha entrou em pausa para recuperar a sessao do WhatsApp.',
            'technical_detail_available': bool(technical_summary),
            'fingerprint': f'{event_type}:bridge_recovery_pause:{http_status_label}',
            'tone': 'warn',
        }

    if event_type == 'campaign_auto_resumed_bridge_recovery':
        return {
            'label': 'Retomada automatica apos recuperar sessao',
            'human_title': 'Sessao recuperada automaticamente',
            'human_summary': 'O bridge voltou a ficar saudavel e a campanha retomou sozinha.',
            'recommended_action': 'Acompanhe os proximos envios para confirmar que a sessao permaneceu estavel.',
            'technical_summary': technical_summary or 'A campanha voltou a rodar apos recuperar a sessao do WhatsApp.',
            'technical_detail_available': bool(technical_summary),
            'fingerprint': f'{event_type}:bridge_recovery_resumed:{http_status_label}',
            'tone': 'success',
        }

    if event_type == 'campaign_auto_resumed_worker_recovery':
        return {
            'label': 'Retomada automatica apos recuperar motor',
            'human_title': 'Motor de envio recuperado',
            'human_summary': 'O motor de envio voltou a responder e a campanha retomou automaticamente.',
            'recommended_action': 'Acompanhe os proximos envios para confirmar que o ritmo voltou ao normal.',
            'technical_summary': technical_summary or 'A campanha voltou a rodar apos recuperar o motor de envio.',
            'technical_detail_available': bool(technical_summary),
            'fingerprint': f'{event_type}:worker_recovery_resumed:{http_status_label}',
            'tone': 'success',
        }

    if event_type == 'bridge_session_recovery_started':
        return {
            'label': 'Recuperacao automatica iniciada',
            'human_title': 'Sessao em recuperacao automatica',
            'human_summary': 'O sistema detectou uma falha de sessao e iniciou a recuperacao do WhatsApp.',
            'recommended_action': 'Aguarde a retomada automatica antes de interferir manualmente.',
            'technical_summary': technical_summary or 'Recuperacao automatica da sessao iniciada.',
            'technical_detail_available': bool(technical_summary),
            'fingerprint': f'{event_type}:bridge_recovery_started:{http_status_label}',
            'tone': 'warn',
        }

    if event_type == 'bridge_session_recovery_failed':
        return {
            'label': 'Recuperacao automatica falhou',
            'human_title': 'Falha ao recuperar a sessao',
            'human_summary': 'O sistema tentou reiniciar o bridge, mas a sessao ainda nao voltou ao estado saudavel.',
            'recommended_action': 'Verifique o bridge e a conexao do WhatsApp se a falha persistir.',
            'technical_summary': technical_summary or 'Nao foi possivel reiniciar a sessao automaticamente.',
            'technical_detail_available': bool(technical_summary),
            'fingerprint': f'{event_type}:bridge_recovery_failed:{http_status_label}',
            'tone': 'error',
        }

    if error_class == 'permanent' or (http_status is not None and 400 <= http_status < 500):
        return {
            'label': 'Falha permanente',
            'human_title': 'Requisicao recusada',
            'human_summary': 'O provedor rejeitou a tentativa por dado invalido ou restricao permanente.',
            'recommended_action': 'Revise os dados do contato e a configuracao antes de reenviar.',
            'technical_summary': technical_summary,
            'technical_detail_available': bool(technical_summary),
            'fingerprint': f'{event_type}:permanent_failure:{http_status_label}',
            'tone': 'error',
        }

    if event_type == 'retry_scheduled':
        return {
            'label': 'Nova tentativa agendada',
            'human_title': 'Falha temporaria com nova tentativa',
            'human_summary': 'O envio falhou agora, mas o sistema manteve o contato na fila para tentar novamente.',
            'recommended_action': 'Acompanhe se o mesmo incidente continua se repetindo.',
            'technical_summary': technical_summary,
            'technical_detail_available': bool(technical_summary),
            'fingerprint': f'{event_type}:temporary_retry:{http_status_label}',
            'tone': 'warn',
        }

    return {
        'label': 'Falha sem classificacao amigavel',
        'human_title': 'Falha sem classificacao amigavel',
        'human_summary': 'O envio falhou, mas o provedor nao retornou um motivo operacional claro.',
        'recommended_action': 'Abra os detalhes tecnicos para revisar a resposta completa.',
        'technical_summary': technical_summary,
        'technical_detail_available': bool(technical_summary),
        'fingerprint': f'{event_type}:unknown:{http_status_label}',
        'tone': tone,
    }


def _collect_cycle_event_times(db: Session, campaign: Campaign) -> list[datetime]:
    if not campaign.started_at:
        return []

    started_at = ensure_aware_utc(campaign.started_at)
    if started_at is None:
        return []

    sent_rows = db.scalars(
        select(Contact.sent_at).where(
            Contact.campaign_id == campaign.id,
            Contact.status == 'sent',
            Contact.sent_at.is_not(None),
            Contact.sent_at >= started_at,
        )
    ).all()
    failed_rows = db.scalars(
        select(Contact.last_attempt_at).where(
            Contact.campaign_id == campaign.id,
            Contact.status == 'failed',
            Contact.last_attempt_at.is_not(None),
            Contact.last_attempt_at >= started_at,
        )
    ).all()

    timestamps = [ensure_aware_utc(value) for value in [*sent_rows, *failed_rows]]
    return sorted(value for value in timestamps if value is not None)


def _average_interval_seconds(timestamps: list[datetime]) -> int:
    if len(timestamps) < 2:
        return 0
    deltas = [
        max(1, int((timestamps[index] - timestamps[index - 1]).total_seconds()))
        for index in range(1, len(timestamps))
    ]
    return max(1, int(round(sum(deltas) / len(deltas))))


def _format_contacts_per_minute(value: float) -> str:
    return f'{value:.1f}'.replace('.', ',') + ' contato/min'


def _build_performance_payload(campaign: Campaign, pending_count: int, event_times: list[datetime]) -> dict:
    now = now_utc()
    recent_window = [value for value in event_times if (now - value).total_seconds() <= PERFORMANCE_WINDOW_SECONDS]
    recent_sample = event_times[-12:]

    measurement_basis = 'warming_up'
    sample = []
    if len(recent_window) >= 3:
        sample = recent_window
        measurement_basis = 'recent_window'
    elif len(recent_sample) >= 3:
        sample = recent_sample
        measurement_basis = 'recent_sample'
    elif len(event_times) >= 3:
        sample = event_times
        measurement_basis = 'cycle_average'

    observed_seconds = _average_interval_seconds(sample)
    sample_size = len(sample) if sample else len(event_times)
    warming_up = len(sample) < 3 or observed_seconds <= 0
    if warming_up:
        measurement_basis = 'warming_up'

    observed_contacts_per_minute = 0.0 if warming_up else round(60 / observed_seconds, 1)
    last_activity_at = to_iso_utc(event_times[-1]) if event_times else None
    configured_midpoint = (campaign.send_delay_min_seconds + campaign.send_delay_max_seconds) / 2
    configured_penalty = ((campaign.batch_pause_min_seconds + campaign.batch_pause_max_seconds) / 2) / max(1, campaign.batch_size_initial)
    configured_floor = configured_midpoint + configured_penalty
    remaining_observed = 0 if warming_up else int(round(pending_count * observed_seconds))
    remaining_conservative = int(round(pending_count * max(observed_seconds or 0, configured_floor)))

    if warming_up:
        label_speed = 'Aquecendo medicao'
        label_eta = 'Calculando com base na execucao real'
    else:
        label_speed = _format_contacts_per_minute(observed_contacts_per_minute)
        label_eta = str(remaining_observed)

    return {
        'performance': {
            'observed_contacts_per_minute': observed_contacts_per_minute,
            'observed_seconds_per_contact': observed_seconds,
            'measurement_window_seconds': PERFORMANCE_WINDOW_SECONDS,
            'measurement_basis': measurement_basis,
            'last_activity_at': last_activity_at,
            'sample_size': sample_size,
            'warming_up': warming_up,
        },
        'estimates': {
            'remaining_seconds_observed': remaining_observed,
            'remaining_seconds_conservative': remaining_conservative,
            'configured_seconds_per_contact_min': campaign.send_delay_min_seconds,
            'configured_seconds_per_contact_max': campaign.send_delay_max_seconds,
            'configured_batch_pause_min': campaign.batch_pause_min_seconds,
            'configured_batch_pause_max': campaign.batch_pause_max_seconds,
            'label_speed': label_speed,
            'label_eta': label_eta,
            'label_configured_pace': (
                f'Config.: {campaign.send_delay_min_seconds}-{campaign.send_delay_max_seconds}s por envio + pausas operacionais'
            ),
        },
    }


def _friendly_event_title(event_type: str) -> str:
    mapping = {
        'campaign_state_change': 'Mudanca de estado',
        'campaign_speed_profile_changed': 'Perfil de velocidade atualizado',
        'campaign_auto_paused_worker_recovery': 'Pausa automatica por recuperacao do motor',
        'campaign_auto_resumed_worker_recovery': 'Retomada automatica apos recuperar motor',
        'retry_scheduled': 'Nova tentativa agendada',
        'send_failure': 'Falha de envio',
        'send_success': 'Envio concluido',
        'send_attempt': 'Tentativa de envio',
        'send_window_wait': 'Aguardando janela de envio',
        'campaign_auto_paused_daily_limit': 'Pausa automatica por limite diario',
        'campaign_auto_paused_consecutive_failures': 'Pausa automatica por falhas consecutivas',
        'campaign_auto_paused_bridge_recovery': 'Pausa inteligente para recuperar sessao',
        'campaign_auto_resumed_bridge_recovery': 'Retomada automatica apos recuperar sessao',
        'bridge_session_recovery_started': 'Recuperacao automatica iniciada',
        'bridge_session_recovery_failed': 'Recuperacao automatica falhou',
        'bridge_session_broken': 'Sessao do WhatsApp quebrada',
    }
    return mapping.get(event_type, event_type.replace('_', ' ').capitalize())


def _friendly_event_summary(log: SendLog) -> str:
    if log.event_type == 'campaign_state_change':
        text = (log.payload_excerpt or '').strip()
        if not text:
            return 'Campanha atualizada.'
        return text[:140]
    if log.event_type == 'campaign_speed_profile_changed':
        return 'O perfil de velocidade da campanha foi atualizado.'
    if log.event_type == 'campaign_auto_paused_worker_recovery':
        return 'A campanha foi pausada automaticamente para recuperar o motor de envio.'
    if log.event_type == 'campaign_auto_resumed_worker_recovery':
        return 'A campanha retomou automaticamente depois que o motor de envio foi recuperado.'
    if log.event_type == 'retry_scheduled':
        return 'Houve uma falha temporaria e o sistema programou nova tentativa.'
    if log.event_type == 'send_failure':
        return _friendly_failure_reason(log.payload_excerpt)
    if log.event_type == 'send_success':
        return 'Mensagem entregue com sucesso.'
    if log.event_type == 'send_window_wait':
        return 'O envio aguardou a janela operacional permitida.'
    if log.event_type == 'campaign_auto_paused_daily_limit':
        return 'A campanha foi pausada ao atingir o limite diario configurado.'
    if log.event_type == 'campaign_auto_paused_consecutive_failures':
        return 'A campanha foi pausada apos 5 falhas consecutivas.'
    if log.event_type == 'campaign_auto_paused_bridge_recovery':
        return 'A campanha entrou em pausa inteligente para recuperar a sessao do WhatsApp.'
    if log.event_type == 'campaign_auto_resumed_bridge_recovery':
        return 'A campanha retomou automaticamente apos recuperar a sessao do WhatsApp.'
    if log.event_type == 'bridge_session_recovery_started':
        return 'O sistema iniciou a recuperacao automatica da sessao do WhatsApp.'
    if log.event_type == 'bridge_session_recovery_failed':
        return 'A recuperacao automatica da sessao falhou nesta tentativa.'
    if log.event_type == 'bridge_session_broken':
        return 'A sessao do WhatsApp falhou internamente e o envio foi devolvido para a fila.'
    return (log.payload_excerpt or 'Sem detalhes adicionais.')[:140]


def _activity_tone(event_type: str) -> str:
    if event_type == 'send_failure':
        return 'error'
    if event_type == 'retry_scheduled':
        return 'warn'
    if event_type == 'send_success':
        return 'success'
    if event_type in {
        'campaign_auto_paused_daily_limit',
        'campaign_auto_paused_consecutive_failures',
        'campaign_auto_paused_bridge_recovery',
        'campaign_auto_paused_worker_recovery',
        'bridge_session_recovery_started',
    }:
        return 'warn'
    if event_type in {'campaign_auto_resumed_bridge_recovery', 'campaign_auto_resumed_worker_recovery'}:
        return 'success'
    if event_type in {'bridge_session_recovery_failed', 'bridge_session_broken'}:
        return 'error'
    return 'info'


def _campaign_milestone_from_state(payload_excerpt: Optional[str]) -> Optional[dict]:
    text = (payload_excerpt or '').strip().lower()
    mapping = [
        ('campaign completed', {'title': 'Campanha concluida', 'summary': 'A campanha terminou e encerrou a fila atual.', 'tone': 'success'}),
        ('campaign resumed', {'title': 'Campanha retomada', 'summary': 'O envio voltou a processar a fila a partir do ponto de pausa.', 'tone': 'info'}),
        ('campaign paused', {'title': 'Campanha pausada', 'summary': 'A operacao foi interrompida temporariamente pelo operador.', 'tone': 'warn'}),
        ('campaign cancelled', {'title': 'Campanha cancelada', 'summary': 'A fila foi interrompida antes da conclusao.', 'tone': 'error'}),
        ('campaign running', {'title': 'Campanha iniciada', 'summary': 'O envio real foi liberado e a campanha entrou em execucao.', 'tone': 'info'}),
        ('campaign restarted', {'title': 'Campanha reiniciada', 'summary': 'A fila foi recriada para uma nova tentativa operacional.', 'tone': 'warn'}),
    ]
    for key, item in mapping:
        if key in text:
            return item
    return None


def upload_contacts(db: Session, campaign_id: int, payload: bytes) -> dict:
    campaign = get_campaign_or_404(db, campaign_id)
    parsed = parse_csv_bytes(payload)
    replaced_contacts = int(
        db.scalar(select(func.count(Contact.id)).where(Contact.campaign_id == campaign.id, Contact.source == 'csv'))
        or 0
    )
    db.execute(delete(Contact).where(Contact.campaign_id == campaign.id, Contact.source == 'csv'))
    db.flush()

    inserted = 0
    for row in parsed.rows:
        status = 'pending' if row.valid else 'invalid'

        contact = Contact(
            campaign_id=campaign.id,
            name=row.nome,
            phone_raw=row.telefone,
            phone_e164=row.phone_e164,
            email=row.email,
            source='csv',
            status=status,
            error_message=row.error,
        )
        db.add(contact)
        try:
            db.commit()
            inserted += 1
        except IntegrityError:
            db.rollback()

    refresh_campaign_counters(db, campaign.id)
    if campaign.status in {'draft', 'completed', 'cancelled'} and campaign.pending_count > 0:
        campaign.status = 'ready'
    if campaign.status == 'ready':
        campaign.finished_at = None
        if campaign.sent_count > 0 or campaign.failed_count > 0:
            campaign.started_at = None
    db.add(campaign)
    db.commit()

    return {
        'summary': {
            'total': parsed.summary.total,
            'valid': parsed.summary.valid,
            'invalid': parsed.summary.invalid,
            'inserted': inserted,
            'duplicates_skipped': max(0, parsed.summary.total - inserted),
            'replaced_previous_csv_contacts': replaced_contacts,
        }
    }


def add_manual_contact(db: Session, campaign_id: int, name: str, phone: str, email: str = '') -> dict:
    campaign = get_campaign_or_404(db, campaign_id)

    safe_name = (name or '').strip()
    safe_phone = (phone or '').strip()
    safe_email = (email or '').strip()

    if not safe_name:
        return {'ok': False, 'message': 'Informe o nome do cliente.'}
    if not safe_phone:
        return {'ok': False, 'message': 'Informe o telefone do cliente.'}

    ok, phone_e164, error = normalize_br_phone(safe_phone)
    if not ok or not phone_e164:
        return {'ok': False, 'message': error or 'Telefone inválido para o padrão do Brasil (+55).'}

    contact = Contact(
        campaign_id=campaign.id,
        name=safe_name,
        phone_raw=safe_phone,
        phone_e164=phone_e164,
        email=safe_email,
        source='manual',
        status='pending',
        error_message=None,
    )
    db.add(contact)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return {'ok': False, 'message': 'Este telefone já existe nesta campanha.'}

    refresh_campaign_counters(db, campaign.id)
    if campaign.status in {'draft', 'completed', 'cancelled'}:
        campaign.status = 'ready'
    if campaign.status == 'ready':
        campaign.finished_at = None
        if campaign.sent_count > 0 or campaign.failed_count > 0:
            campaign.started_at = None
    db.add(campaign)
    db.commit()
    db.refresh(contact)

    return {
        'ok': True,
        'contact': {
            'id': contact.id,
            'name': contact.name or '',
            'phone_raw': contact.phone_raw or '',
            'phone_e164': contact.phone_e164 or '',
            'email': contact.email or '',
            'status': contact.status or '',
        },
    }


def delete_contact_from_campaign(db: Session, campaign_id: int, contact_id: int) -> dict:
    campaign = get_campaign_or_404(db, campaign_id)
    if campaign.status not in {'draft', 'ready', 'paused'}:
        return {'ok': False, 'message': 'Nao pode remover contato com a campanha em envio ou finalizada.'}

    contact = db.get(Contact, contact_id)
    if contact is None or contact.campaign_id != campaign.id:
        return {'ok': False, 'message': 'Contato nao encontrado nesta campanha.'}

    db.delete(contact)
    db.flush()
    refresh_campaign_counters(db, campaign.id)
    db.commit()

    return {'ok': True, 'message': 'Contato removido da campanha com sucesso.'}


def delete_imported_contacts_from_campaign(db: Session, campaign_id: int) -> dict:
    campaign = get_campaign_or_404(db, campaign_id)
    if campaign.status not in {'draft', 'ready', 'paused'}:
        return {'ok': False, 'message': 'Nao pode limpar contatos importados com a campanha em envio ou finalizada.'}

    deleted_count = int(
        db.scalar(select(func.count(Contact.id)).where(Contact.campaign_id == campaign.id, Contact.source == 'csv')) or 0
    )
    if deleted_count == 0:
        return {'ok': True, 'message': 'Nao havia contatos importados por CSV para limpar.', 'deleted_count': 0}

    db.execute(delete(Contact).where(Contact.campaign_id == campaign.id, Contact.source == 'csv'))
    db.flush()
    refresh_campaign_counters(db, campaign.id)
    db.commit()

    return {
        'ok': True,
        'message': 'Contatos importados removidos com sucesso.',
        'deleted_count': deleted_count,
    }


def refresh_campaign_counters(db: Session, campaign_id: int) -> None:
    campaign = get_campaign_or_404(db, campaign_id)

    total = db.scalar(select(func.count(Contact.id)).where(Contact.campaign_id == campaign_id)) or 0
    valid = db.scalar(select(func.count(Contact.id)).where(Contact.campaign_id == campaign_id, Contact.status != 'invalid')) or 0
    invalid = db.scalar(select(func.count(Contact.id)).where(Contact.campaign_id == campaign_id, Contact.status == 'invalid')) or 0
    sent = db.scalar(select(func.count(Contact.id)).where(Contact.campaign_id == campaign_id, Contact.status == 'sent')) or 0
    failed = db.scalar(select(func.count(Contact.id)).where(Contact.campaign_id == campaign_id, Contact.status == 'failed')) or 0
    pending = db.scalar(select(func.count(Contact.id)).where(Contact.campaign_id == campaign_id, Contact.status.in_(['pending', 'processing']))) or 0

    campaign.total_contacts = int(total)
    campaign.valid_contacts = int(valid)
    campaign.invalid_contacts = int(invalid)
    campaign.sent_count = int(sent)
    campaign.failed_count = int(failed)
    campaign.pending_count = int(pending)

    # Self-heal inconsistent states: any campaign with a pending queue should be actionable.
    if campaign.pending_count > 0 and campaign.status in {'draft', 'completed', 'cancelled'}:
        campaign.status = 'ready'
        campaign.finished_at = None
        if campaign.sent_count > 0 or campaign.failed_count > 0:
            campaign.started_at = None
    elif (
        campaign.pending_count == 0
        and campaign.status in {'ready', 'paused'}
        and (campaign.sent_count + campaign.failed_count) > 0
        and (campaign.sent_count + campaign.failed_count) >= campaign.valid_contacts
    ):
        campaign.status = 'completed'
        if campaign.finished_at is None:
            campaign.finished_at = now_utc()

    db.add(campaign)


def dry_run(db: Session, campaign_id: int) -> dict:
    campaign = get_campaign_or_404(db, campaign_id)
    refresh_campaign_counters(db, campaign.id)
    db.commit()
    db.refresh(campaign)

    sample_q = select(Contact).where(Contact.campaign_id == campaign.id, Contact.status == 'pending').limit(5)
    sample_contacts: Iterable[Contact] = db.scalars(sample_q).all()
    preview = [
        {
            'name': c.name,
            'phone': c.phone_e164,
            'message': render_campaign_message(campaign.message_template, c.name, c.id),
        }
        for c in sample_contacts
    ]

    eta_seconds = campaign.pending_count * 7
    if campaign.pending_count == 0:
        message = 'Não há contatos pendentes nesta campanha.'
        empty_reason = 'no_pending_contacts'
        if campaign.status == 'completed':
            message = 'Esta campanha já foi concluída. Use "Reiniciar campanha" para executar novamente.'
            empty_reason = 'campaign_completed'
    else:
        message = f'Esta ação não envia mensagens reais. Existem {campaign.pending_count} contatos prontos para envio.'
        empty_reason = None

    return {
        'ok': True,
        'message': message,
        'pending_count': campaign.pending_count,
        'summary': {
            'valid': campaign.valid_contacts,
            'invalid': campaign.invalid_contacts,
            'total': campaign.total_contacts,
        },
        'preview': preview,
        'estimated_seconds': eta_seconds,
        'empty_reason': empty_reason,
    }


def restart_campaign(db: Session, campaign_id: int, mode: str) -> tuple[bool, str, int, str]:
    campaign = get_campaign_or_404(db, campaign_id)
    normalized_mode = (mode or '').strip().lower()
    if normalized_mode not in {'all', 'failed'}:
        return False, 'Modo de reinício inválido', 0, campaign.status

    if normalized_mode == 'all':
        statuses_to_reset = {'sent', 'failed', 'processing'}
        success_message = 'Fila recriada para reenviar toda a campanha.'
    else:
        statuses_to_reset = {'failed', 'processing'}
        success_message = 'Fila recriada para reenviar só as falhas.'

    contacts = db.scalars(
        select(Contact).where(Contact.campaign_id == campaign.id, Contact.status.in_(statuses_to_reset))
    ).all()

    for contact in contacts:
        contact.status = 'pending'
        contact.error_message = None
        contact.attempt_count = 0
        contact.last_attempt_at = None
        contact.sent_at = None
        db.add(contact)

    campaign.status = 'ready'
    campaign.test_completed_at = None
    campaign.started_at = None
    campaign.finished_at = None
    db.add(campaign)
    refresh_campaign_counters(db, campaign.id)
    log_event(db, campaign.id, None, 'campaign_state_change', f'campaign restarted; mode={normalized_mode}; reset={len(contacts)}')
    db.commit()
    return True, success_message, len(contacts), campaign.status


def start_campaign(db: Session, campaign_id: int) -> tuple[bool, str]:
    campaign = get_campaign_or_404(db, campaign_id)
    refresh_campaign_counters(db, campaign.id)
    db.flush()

    if campaign.status not in {'ready', 'paused'}:
        return False, f'Campanha no status {campaign.status} não pode iniciar'

    already_executed = campaign.sent_count > 0 or campaign.failed_count > 0
    if campaign.is_test_required and campaign.test_completed_at is None and not already_executed:
        return False, 'Campanha exige o envio de uma amostra para seu WhatsApp antes do envio real'
    if daily_limit_reached(campaign) and campaign.pause_reason == 'daily_limit_reached' and campaign.last_send_date is not None:
        if campaign.last_send_date.date() == now_utc().date():
            return False, 'Campanha atingiu o limite diario de hoje. Retome manualmente no proximo dia.'

    campaign.status = 'running'
    if campaign.started_at is None:
        campaign.started_at = now_utc()
    campaign.finished_at = None
    campaign.pause_reason = None
    db.add(campaign)
    log_event(db, campaign.id, None, 'campaign_state_change', 'campaign running')
    db.commit()
    return True, 'Campanha iniciada'


def pause_campaign(db: Session, campaign_id: int) -> tuple[bool, str]:
    campaign = get_campaign_or_404(db, campaign_id)
    if campaign.status != 'running':
        return False, 'Apenas campanha running pode ser pausada'
    campaign.status = 'paused'
    campaign.pause_reason = 'manual'
    db.add(campaign)
    log_event(db, campaign.id, None, 'campaign_state_change', 'campaign paused')
    db.commit()
    return True, 'Campanha pausada'


def resume_campaign(db: Session, campaign_id: int) -> tuple[bool, str]:
    campaign = get_campaign_or_404(db, campaign_id)
    if campaign.status != 'paused':
        return False, 'Apenas campanha paused pode ser retomada'
    if daily_limit_reached(campaign) and campaign.pause_reason == 'daily_limit_reached' and campaign.last_send_date is not None:
        if campaign.last_send_date.date() == now_utc().date():
            return False, 'Campanha atingiu o limite diario de hoje. Retome manualmente no proximo dia.'
    campaign.status = 'running'
    campaign.pause_reason = None
    db.add(campaign)
    log_event(db, campaign.id, None, 'campaign_state_change', 'campaign resumed')
    db.commit()
    return True, 'Campanha retomada'


def cancel_campaign(db: Session, campaign_id: int) -> tuple[bool, str]:
    campaign = get_campaign_or_404(db, campaign_id)
    if campaign.status in {'cancelled', 'completed'}:
        return False, 'Campanha já finalizada'
    campaign.status = 'cancelled'
    campaign.finished_at = now_utc()
    db.add(campaign)
    log_event(db, campaign.id, None, 'campaign_state_change', 'campaign cancelled')
    db.commit()
    return True, 'Campanha cancelada'


def finalize_if_done(db: Session, campaign_id: int) -> None:
    campaign = get_campaign_or_404(db, campaign_id)
    pending = db.scalar(
        select(func.count(Contact.id)).where(
            Contact.campaign_id == campaign.id,
            Contact.status.in_(['pending', 'processing']),
        )
    )
    if campaign.status == 'running' and (pending or 0) == 0:
        campaign.status = 'completed'
        campaign.finished_at = now_utc()
        db.add(campaign)
        log_event(db, campaign.id, None, 'campaign_state_change', 'campaign completed')


def log_event(
    db: Session,
    campaign_id: int,
    contact_id: Optional[int],
    event_type: str,
    payload_excerpt: Optional[str],
    http_status: Optional[int] = None,
    error_class: Optional[str] = None,
) -> None:
    item = SendLog(
        campaign_id=campaign_id,
        contact_id=contact_id,
        event_type=event_type,
        payload_excerpt=payload_excerpt,
        http_status=http_status,
        error_class=error_class,
    )
    db.add(item)


def export_failures_csv(db: Session, campaign_id: int) -> bytes:
    contacts = db.scalars(
        select(Contact).where(Contact.campaign_id == campaign_id, Contact.status.in_(['failed', 'invalid']))
    ).all()

    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(['nome', 'telefone_original', 'telefone_normalizado', 'email', 'status', 'erro', 'tentativas'])
    for c in contacts:
        writer.writerow([c.name, c.phone_raw, c.phone_e164 or '', c.email, c.status, c.error_message or '', c.attempt_count])
    return stream.getvalue().encode('utf-8')


def _read_campaign_counts(db: Session, campaign_id: int) -> dict:
    total = db.scalar(select(func.count(Contact.id)).where(Contact.campaign_id == campaign_id)) or 0
    valid = db.scalar(select(func.count(Contact.id)).where(Contact.campaign_id == campaign_id, Contact.status != 'invalid')) or 0
    invalid = db.scalar(select(func.count(Contact.id)).where(Contact.campaign_id == campaign_id, Contact.status == 'invalid')) or 0
    sent = db.scalar(select(func.count(Contact.id)).where(Contact.campaign_id == campaign_id, Contact.status == 'sent')) or 0
    failed = db.scalar(select(func.count(Contact.id)).where(Contact.campaign_id == campaign_id, Contact.status == 'failed')) or 0
    pending = db.scalar(select(func.count(Contact.id)).where(Contact.campaign_id == campaign_id, Contact.status.in_(['pending', 'processing']))) or 0
    return {
        'total': int(total),
        'valid': int(valid),
        'invalid': int(invalid),
        'sent': int(sent),
        'failed': int(failed),
        'pending': int(pending),
    }


def _build_failed_reprocessing_payload(db: Session, campaign: Campaign) -> Optional[dict]:
    restart_log = db.scalar(
        select(SendLog)
        .where(
            SendLog.campaign_id == campaign.id,
            SendLog.event_type == 'campaign_state_change',
            SendLog.payload_excerpt.is_not(None),
            SendLog.payload_excerpt.like('campaign restarted;%'),
        )
        .order_by(SendLog.created_at.desc())
        .limit(1)
    )
    if restart_log is None:
        return None

    payload_excerpt = restart_log.payload_excerpt or ''
    mode_match = re.search(r'mode=([a-z_]+)', payload_excerpt)
    if mode_match is None or mode_match.group(1) != 'failed':
        return None

    completed_log = db.scalar(
        select(SendLog)
        .where(
            SendLog.campaign_id == campaign.id,
            SendLog.event_type == 'campaign_state_change',
            SendLog.payload_excerpt == 'campaign completed',
        )
        .order_by(SendLog.created_at.desc())
        .limit(1)
    )
    if completed_log is None or ensure_aware_utc(restart_log.created_at) <= ensure_aware_utc(completed_log.created_at):
        return None

    reset_match = re.search(r'reset=(\d+)', payload_excerpt)
    restart_started_at = ensure_aware_utc(restart_log.created_at)
    sent_in_reprocessing = int(
        db.scalar(
            select(func.count(Contact.id)).where(
                Contact.campaign_id == campaign.id,
                Contact.status == 'sent',
                Contact.sent_at.is_not(None),
                Contact.sent_at >= restart_started_at,
            )
        )
        or 0
    )
    failed_in_reprocessing = int(
        db.scalar(
            select(func.count(Contact.id)).where(
                Contact.campaign_id == campaign.id,
                Contact.status == 'failed',
                Contact.last_attempt_at.is_not(None),
                Contact.last_attempt_at >= restart_started_at,
            )
        )
        or 0
    )
    queued_contacts = int(
        db.scalar(
            select(func.count(Contact.id)).where(
                Contact.campaign_id == campaign.id,
                Contact.status.in_(['pending', 'processing']),
            )
        )
        or 0
    )

    return {
        'active': campaign.status != 'completed',
        'mode': 'failed',
        'reset_contacts': int(reset_match.group(1)) if reset_match else 0,
        'queued_contacts': queued_contacts,
        'sent_in_reprocessing': sent_in_reprocessing,
        'failed_in_reprocessing': failed_in_reprocessing,
    }


def build_results_payload(db: Session, campaign_id: int) -> dict:
    campaign = get_campaign_or_404(db, campaign_id)
    counts = _read_campaign_counts(db, campaign.id)

    processed = int(counts['sent'] + counts['failed'])
    success_rate = round((counts['sent'] / processed) * 100, 1) if processed else 0.0
    failure_rate = round((counts['failed'] / processed) * 100, 1) if processed else 0.0
    coverage_rate = round((processed / counts['valid']) * 100, 1) if counts['valid'] else 0.0

    duration_seconds = 0
    if campaign.started_at:
        started_at = ensure_aware_utc(campaign.started_at)
        end_at = ensure_aware_utc(campaign.finished_at) or now_utc()
        if started_at is not None:
            duration_seconds = max(0, int((end_at - started_at).total_seconds()))

    failure_contacts = db.scalars(
        select(Contact).where(Contact.campaign_id == campaign.id, Contact.status.in_(['failed', 'invalid']))
    ).all()
    grouped_failures: dict[str, dict] = {}
    for contact in failure_contacts:
        normalized = _normalize_operational_issue(
            'invalid_contact' if contact.status == 'invalid' else 'send_failure',
            contact.error_message,
            None,
            None,
        )
        item = grouped_failures.setdefault(
            normalized['fingerprint'],
            {
                'label': normalized['label'],
                'count': 0,
                'tone': normalized['tone'],
                'human_title': normalized['human_title'],
                'human_summary': normalized['human_summary'],
                'recommended_action': normalized['recommended_action'],
                'technical_summary': normalized['technical_summary'],
                'technical_detail_available': normalized['technical_detail_available'],
                'fingerprint': normalized['fingerprint'],
            },
        )
        item['count'] += 1
    top_failures = sorted(grouped_failures.values(), key=lambda item: item['count'], reverse=True)[:4]
    reprocessing_payload = _build_failed_reprocessing_payload(db, campaign)

    if campaign.status == 'completed':
        headline = 'Campanha concluida'
        summary = (
            'Resultado final sem incidentes relevantes.'
            if counts['failed'] == 0
            else 'A campanha terminou, mas houve contatos com falha que pedem revisao.'
        )
    elif campaign.status == 'running':
        headline = 'Campanha em andamento'
        summary = 'A execucao segue ativa. Use esta secao para acompanhar cobertura e falhas sem abrir os detalhes tecnicos.'
    elif counts['pending'] > 0 and processed > 0:
        headline = 'Fila reaberta'
        summary = 'Os contatos ja processados permanecem no historico, enquanto a nova fila aguarda o proximo envio.'
    else:
        headline = 'Resultados parciais'
        summary = 'Os indicadores abaixo ajudam a decidir o proximo passo da operacao.'

    return {
        'headline': headline,
        'summary': summary,
        'processed': processed,
        'success_rate': success_rate,
        'failure_rate': failure_rate,
        'coverage_rate': coverage_rate,
        'duration_seconds': duration_seconds,
        'distribution': {
            'sent': counts['sent'],
            'failed': counts['failed'],
            'pending': counts['pending'],
            'invalid': counts['invalid'],
            'valid': counts['valid'],
            'total': counts['total'],
        },
        'top_failures': top_failures,
        'started_at': to_iso_utc(campaign.started_at),
        'finished_at': to_iso_utc(campaign.finished_at),
        'reprocessing': reprocessing_payload,
    }


def build_activity_payload(db: Session, campaign_id: int) -> dict:
    get_campaign_or_404(db, campaign_id)

    grouped_rows = db.execute(
        select(SendLog.event_type, func.count(SendLog.id))
        .where(SendLog.campaign_id == campaign_id)
        .group_by(SendLog.event_type)
    ).all()
    event_counts = {event_type: int(count or 0) for event_type, count in grouped_rows}
    total_events = int(sum(event_counts.values()))

    summary_cards = [
        {'key': 'state', 'label': 'Mudancas de estado', 'count': int(event_counts.get('campaign_state_change', 0)), 'tone': 'info'},
        {'key': 'success', 'label': 'Entregas confirmadas', 'count': int(event_counts.get('send_success', 0)), 'tone': 'success'},
        {'key': 'retry', 'label': 'Novas tentativas', 'count': int(event_counts.get('retry_scheduled', 0)), 'tone': 'warn'},
        {
            'key': 'failure',
            'label': 'Falhas tecnicas',
            'count': int(event_counts.get('send_failure', 0))
            + int(event_counts.get('campaign_auto_paused_daily_limit', 0))
            + int(event_counts.get('campaign_auto_paused_consecutive_failures', 0))
            + int(event_counts.get('campaign_auto_paused_bridge_recovery', 0))
            + int(event_counts.get('campaign_auto_paused_worker_recovery', 0)),
            'tone': 'error',
        },
    ]

    milestone_logs = db.scalars(
        select(SendLog)
        .where(SendLog.campaign_id == campaign_id, SendLog.event_type == 'campaign_state_change')
        .order_by(SendLog.created_at.desc())
        .limit(20)
    ).all()
    milestones = []
    seen_titles = set()
    for log in milestone_logs:
        milestone = _campaign_milestone_from_state(log.payload_excerpt)
        if milestone is None or milestone['title'] in seen_titles:
            continue
        seen_titles.add(milestone['title'])
        milestones.append(
            {
                'title': milestone['title'],
                'summary': milestone['summary'],
                'time': to_iso_utc(log.created_at),
                'tone': milestone['tone'],
            }
        )

    incident_logs = db.scalars(
        select(SendLog)
        .where(
            SendLog.campaign_id == campaign_id,
            SendLog.event_type.in_(
                [
                    'send_failure',
                    'retry_scheduled',
                    'campaign_auto_paused_daily_limit',
                    'campaign_auto_paused_consecutive_failures',
                    'campaign_auto_paused_bridge_recovery',
                    'campaign_auto_paused_worker_recovery',
                    'campaign_auto_resumed_bridge_recovery',
                    'campaign_auto_resumed_worker_recovery',
                ]
            ),
        )
        .order_by(SendLog.created_at.desc())
        .limit(200)
    ).all()
    grouped_incidents: dict[str, dict] = {}
    for log in incident_logs:
        normalized = _normalize_operational_issue(log.event_type, log.payload_excerpt, log.error_class, log.http_status)
        item = grouped_incidents.setdefault(
            normalized['fingerprint'],
            {
                'title': _friendly_event_title(log.event_type),
                'summary': normalized['label'],
                'tone': normalized['tone'],
                'count': 0,
                'time': to_iso_utc(log.created_at),
                'error_class': log.error_class or '-',
                'http_status': log.http_status or '-',
                'human_title': normalized['human_title'],
                'human_summary': normalized['human_summary'],
                'recommended_action': normalized['recommended_action'],
                'technical_summary': normalized['technical_summary'],
                'technical_detail_available': normalized['technical_detail_available'],
                'fingerprint': normalized['fingerprint'],
            },
        )
        item['count'] += 1
        if ensure_aware_utc(log.created_at) and ensure_aware_utc(datetime.fromisoformat(item['time'])):
            if ensure_aware_utc(log.created_at) > ensure_aware_utc(datetime.fromisoformat(item['time'])):
                item['time'] = to_iso_utc(log.created_at)
    incidents = sorted(grouped_incidents.values(), key=lambda item: (-item['count'], item['time']))[:8]

    processed_count = int(event_counts.get('send_success', 0) + event_counts.get('send_failure', 0))
    batch_size = 1000 if processed_count >= 1000 else 500 if processed_count >= 500 else 0
    if batch_size:
        processed_marker = (processed_count // batch_size) * batch_size
        processed_at = db.scalar(
            select(func.max(SendLog.created_at)).where(
                SendLog.campaign_id == campaign_id,
                SendLog.event_type.in_(['send_success', 'send_failure']),
            )
        )
        if processed_at is not None and processed_marker > 0:
            milestones.append(
                {
                    'title': 'Lote processado',
                    'summary': f'Lote de {processed_marker:,} contatos processado.'.replace(',', '.'),
                    'time': to_iso_utc(processed_at),
                    'tone': 'success',
                }
            )

    failed_count = int(event_counts.get('send_failure', 0))
    if failed_count >= 10:
        failure_peak_at = db.scalar(
            select(func.max(SendLog.created_at)).where(
                SendLog.campaign_id == campaign_id,
                SendLog.event_type == 'send_failure',
            )
        )
        if failure_peak_at is not None:
            milestones.append(
                {
                    'title': 'Pico de falhas',
                    'summary': f'{failed_count} falhas acumuladas pedem revisao operacional.',
                    'time': failure_peak_at.isoformat(),
                    'tone': 'error',
                }
            )

    milestones = sorted(milestones, key=lambda item: item['time'], reverse=True)[:6]

    return {
        'total_events': total_events,
        'summary_cards': summary_cards,
        'milestones': milestones,
        'incidents': incidents,
    }


def stats_payload(
    db: Session,
    campaign_id: int,
    runtime_batch_size: int | None = None,
    service_health: dict | None = None,
) -> dict:
    campaign = get_campaign_or_404(db, campaign_id)
    refresh_campaign_counters(db, campaign.id)
    db.commit()
    db.refresh(campaign)

    current_cycle_sent = 0
    current_cycle_failed = 0
    current_cycle_pending = campaign.pending_count
    if campaign.started_at:
        current_cycle_sent = int(
            db.scalar(
                select(func.count(Contact.id)).where(
                    Contact.campaign_id == campaign.id,
                    Contact.status == 'sent',
                    Contact.sent_at.is_not(None),
                    Contact.sent_at >= campaign.started_at,
                )
            )
            or 0
        )
        current_cycle_failed = int(
            db.scalar(
                select(func.count(Contact.id)).where(
                    Contact.campaign_id == campaign.id,
                    Contact.status == 'failed',
                    Contact.last_attempt_at.is_not(None),
                    Contact.last_attempt_at >= campaign.started_at,
                )
            )
            or 0
        )
    current_cycle_total = current_cycle_sent + current_cycle_failed + current_cycle_pending
    performance_payload = _build_performance_payload(campaign, current_cycle_pending, _collect_cycle_event_times(db, campaign))

    return {
        'campaign_id': campaign.id,
        'status': campaign.status,
        'sent': campaign.sent_count,
        'failed': campaign.failed_count,
        'pending': campaign.pending_count,
        'valid': campaign.valid_contacts,
        'invalid': campaign.invalid_contacts,
        'total': campaign.total_contacts,
        'test_completed_at': to_iso_utc(campaign.test_completed_at),
        'started_at': to_iso_utc(campaign.started_at),
        'finished_at': to_iso_utc(campaign.finished_at),
        'updated_at': to_iso_utc(campaign.updated_at),
        'sent_today': campaign.sent_today,
        'daily_limit': campaign.daily_limit,
        'pause_reason': campaign.pause_reason,
        'speed_profile': campaign.speed_profile,
        'send_delay_min_seconds': campaign.send_delay_min_seconds,
        'send_delay_max_seconds': campaign.send_delay_max_seconds,
        'batch_pause_min_seconds': campaign.batch_pause_min_seconds,
        'batch_pause_max_seconds': campaign.batch_pause_max_seconds,
        'batch_size_initial': campaign.batch_size_initial,
        'batch_size_max': campaign.batch_size_max,
        'batch_growth_step': campaign.batch_growth_step,
        'batch_growth_streak_required': campaign.batch_growth_streak_required,
        'batch_shrink_step': campaign.batch_shrink_step,
        'batch_shrink_error_streak_required': campaign.batch_shrink_error_streak_required,
        'batch_size_floor': campaign.batch_size_floor,
        'send_window_start': f'{int(campaign.send_window_start_hour or 8):02d}:00',
        'send_window_end': f'{int(campaign.send_window_end_hour or 20):02d}:00',
        'current_cycle': {
            'sent': current_cycle_sent,
            'failed': current_cycle_failed,
            'pending': current_cycle_pending,
            'total': current_cycle_total,
        },
        'runtime_profile': runtime_profile_payload(campaign, batch_size_current=runtime_batch_size),
        'service_health': service_health or {'services': {}, 'latest_alert': None},
        **performance_payload,
    }
