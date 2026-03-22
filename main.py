from __future__ import annotations

import asyncio
import os
from typing import Callable, Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from database import Base, engine, get_db
from models import Campaign, Contact, SendLog
from schemas import CampaignCreate, TemplateUpdate
from services.campaign_service import (
    add_manual_contact,
    build_activity_payload,
    build_results_payload,
    cancel_campaign,
    create_campaign,
    delete_campaign,
    delete_contact_from_campaign,
    delete_imported_contacts_from_campaign,
    dry_run,
    export_failures_csv,
    get_campaign_or_404,
    log_event,
    pause_campaign,
    refresh_campaign_counters,
    restart_campaign,
    resume_campaign,
    start_campaign,
    stats_payload,
    update_campaign_operational_settings,
    update_template,
    upload_contacts,
)
from services.send_engine import SendEngine
from services.whatsapp import WhatsAppClient, WhatsAppError
from utils.config import load_app_env
from utils.message_compose import render_test_run_message

load_app_env()

APP_PASSWORD = os.getenv('APP_ADMIN_PASSWORD', 'admin123')
SESSION_COOKIE = 'mass_sender_admin'

app = FastAPI(title='WhatsApp Campaign Sender MVP')
app.mount('/static', StaticFiles(directory='static'), name='static')
templates = Jinja2Templates(directory='templates')
engine_worker = SendEngine()


def start_engine_worker_task() -> asyncio.Task:
    return asyncio.create_task(engine_worker.run_forever())


async def supervise_operational_services() -> None:
    while True:
        worker_task = getattr(app.state, 'worker_task', None)
        if worker_task is None:
            app.state.worker_task = start_engine_worker_task()
            worker_task = app.state.worker_task

        if worker_task.done():
            failure_reason = 'Motor de envio interrompido inesperadamente. Recuperacao automatica iniciada.'
            await engine_worker.pause_campaigns_for_worker_recovery(failure_reason)
            try:
                await worker_task
            except BaseException:
                pass
            app.state.worker_task = start_engine_worker_task()
            await asyncio.sleep(1)
            await engine_worker.resume_campaigns_after_worker_recovery()
        elif engine_worker.worker_heartbeat_stale():
            failure_reason = 'Motor de envio sem resposta. Recuperacao automatica iniciada.'
            await engine_worker.pause_campaigns_for_worker_recovery(failure_reason)
            worker_task.cancel()
            try:
                await worker_task
            except BaseException:
                pass
            app.state.worker_task = start_engine_worker_task()
            await asyncio.sleep(1)
            await engine_worker.resume_campaigns_after_worker_recovery()

        await engine_worker.monitor_bridge_service()
        await asyncio.sleep(5)


def ensure_campaign_operational_columns(target_engine: Engine) -> None:
    expected_columns = {
        'speed_profile': "ALTER TABLE campaigns ADD COLUMN speed_profile VARCHAR(20) NOT NULL DEFAULT 'conservative'",
        'send_delay_min_seconds': 'ALTER TABLE campaigns ADD COLUMN send_delay_min_seconds INTEGER NOT NULL DEFAULT 5',
        'send_delay_max_seconds': 'ALTER TABLE campaigns ADD COLUMN send_delay_max_seconds INTEGER NOT NULL DEFAULT 10',
        'batch_pause_min_seconds': 'ALTER TABLE campaigns ADD COLUMN batch_pause_min_seconds INTEGER NOT NULL DEFAULT 5',
        'batch_pause_max_seconds': 'ALTER TABLE campaigns ADD COLUMN batch_pause_max_seconds INTEGER NOT NULL DEFAULT 10',
        'batch_size_initial': 'ALTER TABLE campaigns ADD COLUMN batch_size_initial INTEGER NOT NULL DEFAULT 10',
        'batch_size_max': 'ALTER TABLE campaigns ADD COLUMN batch_size_max INTEGER NOT NULL DEFAULT 25',
        'batch_growth_step': 'ALTER TABLE campaigns ADD COLUMN batch_growth_step INTEGER NOT NULL DEFAULT 2',
        'batch_growth_streak_required': 'ALTER TABLE campaigns ADD COLUMN batch_growth_streak_required INTEGER NOT NULL DEFAULT 3',
        'batch_shrink_step': 'ALTER TABLE campaigns ADD COLUMN batch_shrink_step INTEGER NOT NULL DEFAULT 2',
        'batch_shrink_error_streak_required': 'ALTER TABLE campaigns ADD COLUMN batch_shrink_error_streak_required INTEGER NOT NULL DEFAULT 2',
        'batch_size_floor': 'ALTER TABLE campaigns ADD COLUMN batch_size_floor INTEGER NOT NULL DEFAULT 5',
        'send_window_start_hour': 'ALTER TABLE campaigns ADD COLUMN send_window_start_hour INTEGER NOT NULL DEFAULT 8',
        'send_window_end_hour': 'ALTER TABLE campaigns ADD COLUMN send_window_end_hour INTEGER NOT NULL DEFAULT 20',
        'daily_limit': 'ALTER TABLE campaigns ADD COLUMN daily_limit INTEGER NOT NULL DEFAULT 0',
        'sent_today': 'ALTER TABLE campaigns ADD COLUMN sent_today INTEGER NOT NULL DEFAULT 0',
        'last_send_date': 'ALTER TABLE campaigns ADD COLUMN last_send_date DATETIME',
        'pause_reason': 'ALTER TABLE campaigns ADD COLUMN pause_reason VARCHAR(80)',
    }
    with target_engine.begin() as conn:
        existing = {row[1] for row in conn.execute(text("PRAGMA table_info('campaigns')")).fetchall()}
        for name, ddl in expected_columns.items():
            if name not in existing:
                conn.execute(text(ddl))
        conn.execute(
            text(
                '''
                UPDATE campaigns
                SET speed_profile = COALESCE(speed_profile, 'conservative'),
                    send_delay_min_seconds = COALESCE(send_delay_min_seconds, 5),
                    send_delay_max_seconds = COALESCE(send_delay_max_seconds, 10),
                    batch_pause_min_seconds = COALESCE(batch_pause_min_seconds, 5),
                    batch_pause_max_seconds = COALESCE(batch_pause_max_seconds, 10),
                    batch_size_initial = COALESCE(batch_size_initial, 10),
                    batch_size_max = COALESCE(batch_size_max, 25),
                    batch_growth_step = COALESCE(batch_growth_step, 2),
                    batch_growth_streak_required = COALESCE(batch_growth_streak_required, 3),
                    batch_shrink_step = COALESCE(batch_shrink_step, 2),
                    batch_shrink_error_streak_required = COALESCE(batch_shrink_error_streak_required, 2),
                    batch_size_floor = COALESCE(batch_size_floor, 5),
                    send_window_start_hour = COALESCE(send_window_start_hour, 8),
                    send_window_end_hour = COALESCE(send_window_end_hour, 20),
                    daily_limit = COALESCE(daily_limit, 0),
                    sent_today = COALESCE(sent_today, 0)
                '''
            )
        )
        contact_rows = conn.execute(text("PRAGMA table_info('contacts')")).fetchall()
        if contact_rows:
            contact_columns = {row[1] for row in contact_rows}
            if 'source' not in contact_columns:
                conn.execute(text("ALTER TABLE contacts ADD COLUMN source VARCHAR(20) NOT NULL DEFAULT 'csv'"))
            conn.execute(text("UPDATE contacts SET source = COALESCE(source, 'csv')"))


def require_auth(request: Request):
    if request.url.path.startswith('/login') or request.url.path.startswith('/health'):
        return
    token = request.cookies.get(SESSION_COOKIE)
    if token != APP_PASSWORD:
        raise HTTPException(status_code=401, detail='Não autenticado')


def _expects_html_navigation(request: Request) -> bool:
    accept = (request.headers.get('accept') or '').lower()
    return request.method.upper() == 'GET' and 'text/html' in accept


@app.exception_handler(HTTPException)
async def custom_http_exception_handler(request: Request, exc: HTTPException):
    if exc.status_code == 401 and _expects_html_navigation(request):
        return RedirectResponse('/login', status_code=303)
    return await http_exception_handler(request, exc)


def bridge_error_response(exc: WhatsAppError, operation: str) -> JSONResponse:
    raw_message = str(exc)
    lowered = raw_message.lower()
    hint = 'Verifique os logs do wa-bridge e tente novamente.'
    message = f'Falha ao acessar o bridge durante {operation}.'

    if 'connection refused' in lowered or 'connecterror' in lowered or 'failed to establish a new connection' in lowered:
        message = 'wa-bridge indisponível. O serviço não está aceitando conexões.'
        hint = 'Suba o wa-bridge (`cd wa-bridge && npm start`) e atualize a página.'
    elif 'timed out' in lowered or 'timeout' in lowered:
        message = 'wa-bridge demorou para responder.'
        hint = 'Aguarde alguns segundos e clique em "Atualizar status".'
    elif 'browser is already running' in lowered:
        message = 'Conflito de sessão detectado no navegador interno do wa-bridge.'
        hint = 'O bridge tenta autorecuperação. Aguarde alguns segundos e atualize o status.'

    return JSONResponse(
        {
            'ok': False,
            'message': message,
            'hint': hint,
            'operation': operation,
            'detail': raw_message[:500],
        },
        status_code=502,
    )


def classify_test_run_failure(exc: Exception) -> tuple[str, str]:
    raw = str(exc).strip() or exc.__class__.__name__
    lowered = raw.lower()

    if (
        'connection refused' in lowered
        or 'connecterror' in lowered
        or 'all connection attempts failed' in lowered
        or 'failed to establish a new connection' in lowered
    ):
        return (
            'bridge_unreachable',
            'wa-bridge indisponível. Suba o serviço (`cd wa-bridge && npm start`) e tente novamente.',
        )
    if 'timed out' in lowered or 'timeout' in lowered:
        return ('bridge_timeout', 'wa-bridge demorou para responder. Aguarde alguns segundos e tente de novo.')
    if 'no lid for user' in lowered:
        return (
            'number_resolution_failed',
            'O WhatsApp Web não conseguiu resolver esse número no momento (No LID for user).',
        )
    return ('send_failed', raw[:160])


async def resolve_test_run_destination(client: WhatsAppClient) -> tuple[Optional[str], Optional[str]]:
    if client.provider != 'bridge':
        return None, None
    try:
        session = await client.bridge_session()
    except WhatsAppError:
        return None, None
    phone = str(session.get('phone') or '').strip()
    if not phone:
        return None, None
    return phone, 'amostras enviadas para o numero conectado no Painel WhatsApp'


@app.on_event('startup')
async def startup_event() -> None:
    Base.metadata.create_all(bind=engine)
    ensure_campaign_operational_columns(engine)
    app.state.worker_task = start_engine_worker_task()
    app.state.supervisor_task = asyncio.create_task(supervise_operational_services())


@app.on_event('shutdown')
async def shutdown_event() -> None:
    await engine_worker.stop()
    task = getattr(app.state, 'worker_task', None)
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    supervisor_task = getattr(app.state, 'supervisor_task', None)
    if supervisor_task:
        supervisor_task.cancel()
        try:
            await supervisor_task
        except asyncio.CancelledError:
            pass


@app.get('/health')
async def health() -> dict:
    client = WhatsAppClient()
    configured = client.configured
    reachable, reason = await client.healthcheck()
    return {
        'ok': True,
        'provider': client.provider,
        'backend_configured': configured,
        'backend_reachable': reachable,
        'backend_message': reason,
        'evolution_configured': configured if client.provider == 'evolution' else False,
        'evolution_reachable': reachable if client.provider == 'evolution' else False,
        'evolution_message': reason if client.provider == 'evolution' else 'Provider ativo nao e Evolution',
    }


@app.get('/bridge/session', dependencies=[Depends(require_auth)])
async def bridge_session() -> JSONResponse:
    client = WhatsAppClient()
    if client.provider != 'bridge':
        return JSONResponse({'ok': False, 'message': 'Provider ativo não é bridge'}, status_code=400)
    try:
        payload = await client.bridge_session()
        return JSONResponse({'ok': True, 'session': payload})
    except WhatsAppError as exc:
        return bridge_error_response(exc, 'session')


@app.get('/bridge/qr', dependencies=[Depends(require_auth)])
async def bridge_qr() -> JSONResponse:
    client = WhatsAppClient()
    if client.provider != 'bridge':
        return JSONResponse({'ok': False, 'message': 'Provider ativo não é bridge'}, status_code=400)
    try:
        payload = await client.bridge_qr()
        return JSONResponse({'ok': True, 'qr': payload})
    except WhatsAppError as exc:
        code = 404 if exc.http_status == 404 else 502
        if code == 404:
            return JSONResponse({'ok': False, 'message': 'QR ainda não está disponível. Atualize o status e tente novamente.'}, status_code=404)
        return bridge_error_response(exc, 'qr')


@app.post('/bridge/restart', dependencies=[Depends(require_auth)])
async def bridge_restart() -> JSONResponse:
    client = WhatsAppClient()
    if client.provider != 'bridge':
        return JSONResponse({'ok': False, 'message': 'Provider ativo não é bridge'}, status_code=400)
    try:
        payload = await client.bridge_restart()
        return JSONResponse({'ok': True, 'result': payload})
    except WhatsAppError as exc:
        return bridge_error_response(exc, 'restart')


@app.post('/bridge/reset', dependencies=[Depends(require_auth)])
async def bridge_reset() -> JSONResponse:
    client = WhatsAppClient()
    if client.provider != 'bridge':
        return JSONResponse({'ok': False, 'message': 'Provider ativo não é bridge'}, status_code=400)
    try:
        payload = await client.bridge_reset()
        return JSONResponse({'ok': True, 'result': payload})
    except WhatsAppError as exc:
        return bridge_error_response(exc, 'reset')


@app.get('/login', response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse('login.html', {'request': request, 'error': None})


@app.post('/login', response_class=HTMLResponse)
def login_action(request: Request, password: str = Form(...)):
    if password != APP_PASSWORD:
        return templates.TemplateResponse('login.html', {'request': request, 'error': 'Senha inválida'}, status_code=401)

    response = RedirectResponse(url='/', status_code=303)
    response.set_cookie(SESSION_COOKIE, APP_PASSWORD, httponly=True, samesite='lax')
    return response


@app.post('/logout')
def logout():
    response = RedirectResponse(url='/login', status_code=303)
    response.delete_cookie(SESSION_COOKIE)
    return response


@app.get('/', response_class=HTMLResponse, dependencies=[Depends(require_auth)])
def index(request: Request, db: Session = Depends(get_db)):
    campaigns = db.scalars(select(Campaign).order_by(Campaign.created_at.desc())).all()
    return templates.TemplateResponse('index.html', {'request': request, 'campaigns': campaigns})


@app.post('/campaigns', dependencies=[Depends(require_auth)])
def create_campaign_route(name: str = Form(...), db: Session = Depends(get_db)):
    item = create_campaign(db, name=name)
    return RedirectResponse(f'/campaigns/{item.id}', status_code=303)


@app.post('/campaigns/{campaign_id}/delete', dependencies=[Depends(require_auth)])
def delete_campaign_route(campaign_id: int, db: Session = Depends(get_db)):
    result = delete_campaign(db, campaign_id)
    payload = {**result}
    if result.get('ok'):
        payload['redirect_url'] = '/'
    return JSONResponse(payload, status_code=200 if result.get('ok') else 400)


@app.get('/campaigns/{campaign_id}', response_class=HTMLResponse, dependencies=[Depends(require_auth)])
def campaign_page(
    campaign_id: int,
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(10),
    status: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    campaign = get_campaign_or_404(db, campaign_id)
    runtime_profile = engine_worker._profiles.get(campaign_id, {})
    stats = stats_payload(
        db,
        campaign_id,
        runtime_batch_size=runtime_profile.get('batch_size'),
        service_health=engine_worker.service_health_snapshot(),
    )
    page_size = per_page if per_page in {10, 25, 50} else 10
    status_filter = (status or '').strip().lower()
    allowed_status = {'pending', 'processing', 'sent', 'failed', 'invalid'}
    if status_filter not in allowed_status:
        status_filter = ''

    contacts_query = select(Contact).where(Contact.campaign_id == campaign_id)
    count_query = select(func.count(Contact.id)).where(Contact.campaign_id == campaign_id)
    if status_filter:
        contacts_query = contacts_query.where(Contact.status == status_filter)
        count_query = count_query.where(Contact.status == status_filter)

    total_contacts = db.scalar(count_query) or 0
    total_pages = max(1, (int(total_contacts) + page_size - 1) // page_size)
    page = min(page, total_pages)
    offset = (page - 1) * page_size
    contacts = db.scalars(contacts_query.order_by(Contact.id.asc()).offset(offset).limit(page_size)).all()

    return templates.TemplateResponse(
        'campaign.html',
        {
            'request': request,
            'campaign': campaign,
            'stats': stats,
            'contacts': contacts,
            'contacts_page': page,
            'contacts_total_pages': total_pages,
            'contacts_total': int(total_contacts),
            'contacts_page_size': page_size,
            'contacts_status_filter': status_filter,
        },
    )


@app.get('/campaigns/{campaign_id}/contacts', dependencies=[Depends(require_auth)])
def campaign_contacts_route(
    campaign_id: int,
    page: int = Query(1, ge=1),
    per_page: int = Query(10),
    status: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    get_campaign_or_404(db, campaign_id)
    page_size = per_page if per_page in {10, 25, 50} else 10
    status_filter = (status or '').strip().lower()
    allowed_status = {'pending', 'processing', 'sent', 'failed', 'invalid'}
    if status_filter not in allowed_status:
        status_filter = ''

    contacts_query = select(Contact).where(Contact.campaign_id == campaign_id)
    count_query = select(func.count(Contact.id)).where(Contact.campaign_id == campaign_id)
    if status_filter:
        contacts_query = contacts_query.where(Contact.status == status_filter)
        count_query = count_query.where(Contact.status == status_filter)

    total_contacts = int(db.scalar(count_query) or 0)
    total_pages = max(1, (total_contacts + page_size - 1) // page_size)
    current_page = min(page, total_pages)
    offset = (current_page - 1) * page_size
    contacts = db.scalars(contacts_query.order_by(Contact.id.asc()).offset(offset).limit(page_size)).all()

    return JSONResponse(
        {
            'items': [
                {
                    'id': c.id,
                    'name': c.name or '',
                    'phone_raw': c.phone_raw or '',
                    'phone_e164': c.phone_e164 or '',
                    'email': c.email or '',
                    'status': c.status or '',
                    'error_message': c.error_message or '',
                }
                for c in contacts
            ],
            'pagination': {
                'page': current_page,
                'total_pages': total_pages,
                'total': total_contacts,
                'page_size': page_size,
            },
            'status_filter': status_filter,
        }
    )


@app.post('/campaigns/{campaign_id}/template', dependencies=[Depends(require_auth)])
def update_template_route(campaign_id: int, message_template: str = Form(...), db: Session = Depends(get_db)):
    update_template(db, campaign_id, message_template)
    return RedirectResponse(f'/campaigns/{campaign_id}', status_code=303)


@app.post('/campaigns/{campaign_id}/settings', dependencies=[Depends(require_auth)])
def update_campaign_settings_route(
    campaign_id: int,
    speed_profile: str = Form('conservative'),
    send_delay_min_seconds: int = Form(...),
    send_delay_max_seconds: int = Form(...),
    batch_pause_min_seconds: int = Form(5),
    batch_pause_max_seconds: int = Form(10),
    send_window_start: str = Form('08:00'),
    send_window_end: str = Form('20:00'),
    daily_limit: int = Form(...),
    db: Session = Depends(get_db),
):
    ok, message, settings = update_campaign_operational_settings(
        db,
        campaign_id,
        send_delay_min_seconds,
        send_delay_max_seconds,
        daily_limit,
        speed_profile=speed_profile,
        batch_pause_min_seconds=batch_pause_min_seconds,
        batch_pause_max_seconds=batch_pause_max_seconds,
        send_window_start=send_window_start,
        send_window_end=send_window_end,
    )
    return JSONResponse({'ok': ok, 'message': message, 'settings': settings}, status_code=200 if ok else 400)


@app.post('/campaigns/{campaign_id}/contacts/upload', dependencies=[Depends(require_auth)])
async def upload_contacts_route(campaign_id: int, csv_file: UploadFile = File(...), db: Session = Depends(get_db)):
    content = await csv_file.read()
    result = upload_contacts(db, campaign_id, content)
    return JSONResponse(result)


@app.post('/campaigns/{campaign_id}/contacts/manual', dependencies=[Depends(require_auth)])
def add_manual_contact_route(
    campaign_id: int,
    name: str = Form(...),
    phone: str = Form(...),
    email: str = Form(''),
    db: Session = Depends(get_db),
):
    result = add_manual_contact(db, campaign_id, name=name, phone=phone, email=email)
    return JSONResponse(result, status_code=200 if result.get('ok') else 400)


@app.post('/campaigns/{campaign_id}/contacts/{contact_id}/delete', dependencies=[Depends(require_auth)])
def delete_contact_route(campaign_id: int, contact_id: int, db: Session = Depends(get_db)):
    result = delete_contact_from_campaign(db, campaign_id, contact_id)
    return JSONResponse(result, status_code=200 if result.get('ok') else 400)


@app.post('/campaigns/{campaign_id}/contacts/delete-imported', dependencies=[Depends(require_auth)])
def delete_imported_contacts_route(campaign_id: int, db: Session = Depends(get_db)):
    result = delete_imported_contacts_from_campaign(db, campaign_id)
    return JSONResponse(result, status_code=200 if result.get('ok') else 400)


@app.post('/campaigns/{campaign_id}/dry-run', dependencies=[Depends(require_auth)])
def dry_run_route(campaign_id: int, db: Session = Depends(get_db)):
    return JSONResponse(dry_run(db, campaign_id))


@app.post('/campaigns/{campaign_id}/test-run', dependencies=[Depends(require_auth)])
async def test_run_route(campaign_id: int, sample_size: int = Form(1), db: Session = Depends(get_db)):
    campaign = get_campaign_or_404(db, campaign_id)
    refresh_campaign_counters(db, campaign_id)
    db.refresh(campaign)

    contacts = campaign.contacts
    candidates = [c for c in contacts if c.status == 'pending'][: max(1, min(20, sample_size))]
    if not candidates:
        message = 'Não há contatos pendentes para enviar como amostra. Reinicie a campanha para gerar uma nova fila.'
        if campaign.status == 'completed':
            message = 'Esta campanha já foi concluída. Use "Reiniciar campanha" para executar uma nova amostra.'
        return JSONResponse({'ok': False, 'message': message, 'empty_reason': 'no_pending_contacts'}, status_code=400)

    client = WhatsAppClient()
    if not client.configured:
        return JSONResponse({'ok': False, 'message': 'Backend WhatsApp não configurado'}, status_code=400)

    test_destination, destination_note = await resolve_test_run_destination(client)
    prior_test_attempts = int(
        db.scalar(
            select(func.count(SendLog.id)).where(
                SendLog.campaign_id == campaign.id,
                SendLog.event_type == 'test_run_attempt',
            )
        )
        or 0
    )
    sent = 0
    failures = 0
    failure_reasons: dict[str, int] = {}
    failure_details: list[str] = []
    for index, c in enumerate(candidates):
        rendered = render_test_run_message(campaign.message_template, c.name, c.id, prior_test_attempts + index)
        target_phone = test_destination or (c.phone_e164 or '')
        msg = rendered
        if test_destination:
            msg = (
                f'[Amostra para meu WhatsApp] Contato original: {(c.name or "Sem nome").strip() or "cliente"} '
                f'({c.phone_e164 or c.phone_raw or "-"})\n\n{rendered}'
            )
        try:
            log_event(db, campaign.id, c.id, 'test_run_attempt', rendered[:160])
            db.commit()
            await client.send_text(target_phone, msg)
            sent += 1
            log_event(db, campaign.id, c.id, 'test_run_sent', rendered[:160])
        except WhatsAppError as exc:
            failures += 1
            code, detail = classify_test_run_failure(exc)
            failure_reasons[code] = failure_reasons.get(code, 0) + 1
            if len(failure_details) < 3:
                failure_details.append(detail)
            log_event(db, campaign.id, c.id, 'test_run_failure', detail[:160], exc.http_status, exc.error_class)
        except Exception as exc:
            failures += 1
            code, detail = classify_test_run_failure(exc)
            failure_reasons[code] = failure_reasons.get(code, 0) + 1
            if len(failure_details) < 3:
                failure_details.append(detail)
            log_event(db, campaign.id, c.id, 'test_run_failure', detail[:160])

    db.commit()

    if failures == 0:
        from datetime import datetime, timezone

        campaign.test_completed_at = datetime.now(timezone.utc)
        db.add(campaign)
        db.commit()

    hint = ''
    if failures > 0:
        if failure_reasons.get('bridge_unreachable'):
            hint = 'Inicie o wa-bridge e valide em http://127.0.0.1:3010/health antes de enviar uma amostra para seu WhatsApp.'
        elif failure_reasons.get('number_resolution_failed'):
            hint = 'Tente novamente em 30-60 segundos. Se persistir, gere novo QR no bridge e reconecte a sessão.'

    return {
        'ok': failures == 0,
        'sent': sent,
        'failures': failures,
        'message': 'Amostra enviada',
        'destination_note': destination_note,
        'failure_reasons': failure_reasons,
        'failure_details': failure_details,
        'hint': hint,
    }


@app.post('/campaigns/{campaign_id}/restart', dependencies=[Depends(require_auth)])
def restart_route(campaign_id: int, mode: str = Form(...), db: Session = Depends(get_db)):
    ok, message, reset_contacts, new_status = restart_campaign(db, campaign_id, mode)
    if ok:
        engine_worker.reset_campaign_runtime(campaign_id, hard=True)
    code = 200 if ok else 400
    return JSONResponse(
        {'ok': ok, 'message': message, 'reset_contacts': reset_contacts, 'new_status': new_status},
        status_code=code,
    )


@app.post('/campaigns/{campaign_id}/start', dependencies=[Depends(require_auth)])
def start_route(campaign_id: int, db: Session = Depends(get_db)):
    ok, message = start_campaign(db, campaign_id)
    if ok:
        engine_worker.reset_campaign_runtime(campaign_id)
    code = 200 if ok else 400
    return JSONResponse({'ok': ok, 'message': message}, status_code=code)


@app.post('/campaigns/{campaign_id}/pause', dependencies=[Depends(require_auth)])
def pause_route(campaign_id: int, db: Session = Depends(get_db)):
    ok, message = pause_campaign(db, campaign_id)
    code = 200 if ok else 400
    return JSONResponse({'ok': ok, 'message': message}, status_code=code)


@app.post('/campaigns/{campaign_id}/resume', dependencies=[Depends(require_auth)])
def resume_route(campaign_id: int, db: Session = Depends(get_db)):
    ok, message = resume_campaign(db, campaign_id)
    if ok:
        engine_worker.reset_campaign_runtime(campaign_id)
    code = 200 if ok else 400
    return JSONResponse({'ok': ok, 'message': message}, status_code=code)


@app.post('/campaigns/{campaign_id}/cancel', dependencies=[Depends(require_auth)])
def cancel_route(campaign_id: int, db: Session = Depends(get_db)):
    ok, message = cancel_campaign(db, campaign_id)
    code = 200 if ok else 400
    return JSONResponse({'ok': ok, 'message': message}, status_code=code)


@app.get('/campaigns/{campaign_id}/stats', dependencies=[Depends(require_auth)])
def stats_route(campaign_id: int, db: Session = Depends(get_db)):
    runtime_profile = engine_worker._profiles.get(campaign_id, {})
    return JSONResponse(
        stats_payload(
            db,
            campaign_id,
            runtime_batch_size=runtime_profile.get('batch_size'),
            service_health=engine_worker.service_health_snapshot(),
        )
    )


@app.get('/campaigns/{campaign_id}/overview', dependencies=[Depends(require_auth)])
def campaign_overview_route(campaign_id: int, db: Session = Depends(get_db)):
    return JSONResponse(
        {
            'results': build_results_payload(db, campaign_id),
            'activity': build_activity_payload(db, campaign_id),
        }
    )


@app.get('/campaigns/{campaign_id}/failures/export', dependencies=[Depends(require_auth)])
def export_failures_route(campaign_id: int, db: Session = Depends(get_db)):
    content = export_failures_csv(db, campaign_id)
    return Response(
        content=content,
        media_type='text/csv',
        headers={'Content-Disposition': f'attachment; filename="campaign-{campaign_id}-failures.csv"'},
    )
