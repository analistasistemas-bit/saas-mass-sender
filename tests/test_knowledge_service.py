import base64
import csv
import datetime as dt
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models import AgentSpreadsheetUpload


def _write_csv(path: Path):
    with path.open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=['nome', 'codigo', 'descricao', 'preco', 'estoque', 'categoria'])
        writer.writeheader()
        writer.writerow(
            {
                'nome': 'Tricoline Floral',
                'codigo': 'TEC-001',
                'descricao': 'Tecido leve para artesanato',
                'preco': '29.90',
                'estoque': '12',
                'categoria': 'Tecidos',
            }
        )


def test_knowledge_service_respects_manual_priority(monkeypatch, tmp_path):
    monkeypatch.setenv('OPENROUTER_MODEL', 'google/gemini-3.1-flash-lite-preview')
    monkeypatch.setenv('AGENT_SETTINGS_ENCRYPTION_KEY', base64.urlsafe_b64encode(b'4' * 32).decode())

    from services.agent_settings_service import ensure_agent_settings_schema, save_agent_settings_tab
    from services.knowledge_service import KnowledgeService

    engine = create_engine('sqlite:///:memory:', future=True)
    Session = sessionmaker(bind=engine, future=True)
    Base.metadata.create_all(engine)
    ensure_agent_settings_schema(engine)

    db = Session()
    save_agent_settings_tab(
        db,
        'manual',
        {
            'manual_knowledge_enabled': True,
            'manual_knowledge_text': 'A Avil trabalha com tecidos, aviamentos e atendimento comercial consultivo.',
        },
    )
    save_agent_settings_tab(db, 'priority', {'knowledge_priority': ['manual', 'spreadsheet', 'database']})

    service = KnowledgeService(storage_dir=tmp_path)
    result = service.resolve(
        db,
        customer_message='Vocês trabalham com tecidos?',
    )

    assert result['source'] == 'manual'
    assert 'aviamentos' in result['answer_context'].lower()


def test_knowledge_service_uses_spreadsheet_when_prioritized(monkeypatch, tmp_path):
    monkeypatch.setenv('OPENROUTER_MODEL', 'google/gemini-3.1-flash-lite-preview')
    monkeypatch.setenv('AGENT_SETTINGS_ENCRYPTION_KEY', base64.urlsafe_b64encode(b'5' * 32).decode())

    from services.agent_settings_service import ensure_agent_settings_schema, save_agent_settings_tab
    from services.knowledge_service import KnowledgeService

    engine = create_engine('sqlite:///:memory:', future=True)
    Session = sessionmaker(bind=engine, future=True)
    Base.metadata.create_all(engine)
    ensure_agent_settings_schema(engine)

    file_path = tmp_path / 'catalogo.csv'
    _write_csv(file_path)

    db = Session()
    save_agent_settings_tab(db, 'priority', {'knowledge_priority': ['spreadsheet', 'manual', 'database']})

    service = KnowledgeService(storage_dir=tmp_path)
    upload = service.register_spreadsheet_upload(
        db,
        file_name='catalogo.csv',
        stored_path=str(file_path),
        file_size_bytes=file_path.stat().st_size,
        columns=['nome', 'codigo', 'descricao', 'preco', 'estoque', 'categoria'],
        preview_rows=[
            {
                'nome': 'Tricoline Floral',
                'codigo': 'TEC-001',
                'descricao': 'Tecido leve para artesanato',
                'preco': '29.90',
                'estoque': '12',
                'categoria': 'Tecidos',
            }
        ],
        mapping={'name': 'nome', 'code': 'codigo', 'description': 'descricao', 'price': 'preco', 'stock': 'estoque', 'category': 'categoria'},
        activate=True,
    )

    result = service.resolve(db, customer_message='Quero saber o preço da Tricoline Floral')

    assert upload.is_active == 1
    assert result['source'] == 'spreadsheet'
    assert result['matched_product']['name'] == 'Tricoline Floral'
    assert '29.90' in result['answer_context']


def test_register_spreadsheet_upload_serializes_datetime_preview_rows(monkeypatch, tmp_path):
    monkeypatch.setenv('OPENROUTER_MODEL', 'google/gemini-3.1-flash-lite-preview')
    monkeypatch.setenv('AGENT_SETTINGS_ENCRYPTION_KEY', base64.urlsafe_b64encode(b'6' * 32).decode())

    from services.agent_settings_service import ensure_agent_settings_schema
    from services.knowledge_service import KnowledgeService

    engine = create_engine('sqlite:///:memory:', future=True)
    Session = sessionmaker(bind=engine, future=True)
    Base.metadata.create_all(engine)
    ensure_agent_settings_schema(engine)

    db = Session()
    service = KnowledgeService(storage_dir=tmp_path)

    upload = service.register_spreadsheet_upload(
        db,
        file_name='catalogo.xlsx',
        stored_path=str(tmp_path / 'catalogo.xlsx'),
        file_size_bytes=123,
        columns=['produto', 'atualizado_em'],
        preview_rows=[{'produto': 'Tricoline Floral', 'atualizado_em': dt.datetime(2026, 3, 29, 20, 5, 27)}],
        mapping={},
        activate=False,
    )

    payload = service.latest_spreadsheet_payload(db, upload.id)
    assert payload is not None
    assert payload['preview_rows'][0]['atualizado_em'] == '2026-03-29T20:05:27'


def test_validate_upload_bytes_suggests_mapping_for_inventory_columns(monkeypatch, tmp_path):
    monkeypatch.setenv('OPENROUTER_MODEL', 'google/gemini-3.1-flash-lite-preview')
    monkeypatch.setenv('AGENT_SETTINGS_ENCRYPTION_KEY', base64.urlsafe_b64encode(b'7' * 32).decode())

    from services.knowledge_service import KnowledgeService

    file_path = tmp_path / 'estoque.csv'
    with file_path.open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=['COD_ITEM', 'REFERENCIA', 'DESCRICAO', 'CUSTO_PRODUTO', 'ESTOQUE', 'LOJA'],
        )
        writer.writeheader()
        writer.writerow(
            {
                'COD_ITEM': '1202650',
                'REFERENCIA': '01670-05244',
                'DESCRICAO': 'T.CHARMOUSE ESTAMPADO EST.100/1',
                'CUSTO_PRODUTO': '1159.152',
                'ESTOQUE': '381.3',
                'LOJA': 'CDA',
            }
        )

    service = KnowledgeService(storage_dir=tmp_path)
    result = service.validate_upload_bytes(file_path.name, file_path.read_bytes())

    assert result['mapping'] == {
        'name': 'DESCRICAO',
        'code': 'COD_ITEM',
        'description': 'DESCRICAO',
        'price': 'CUSTO_PRODUTO',
        'stock': 'ESTOQUE',
        'category': '',
    }


def test_delete_spreadsheet_upload_removes_file_and_record(monkeypatch, tmp_path):
    monkeypatch.setenv('OPENROUTER_MODEL', 'google/gemini-3.1-flash-lite-preview')
    monkeypatch.setenv('AGENT_SETTINGS_ENCRYPTION_KEY', base64.urlsafe_b64encode(b'8' * 32).decode())

    from services.agent_settings_service import ensure_agent_settings_schema
    from services.knowledge_service import KnowledgeService

    engine = create_engine('sqlite:///:memory:', future=True)
    Session = sessionmaker(bind=engine, future=True)
    Base.metadata.create_all(engine)
    ensure_agent_settings_schema(engine)

    db = Session()
    file_path = tmp_path / 'catalogo.csv'
    file_path.write_text('nome,codigo\nTeste,1\n', encoding='utf-8')

    service = KnowledgeService(storage_dir=tmp_path)
    upload = service.register_spreadsheet_upload(
        db,
        file_name='catalogo.csv',
        stored_path=str(file_path),
        file_size_bytes=file_path.stat().st_size,
        columns=['nome', 'codigo'],
        preview_rows=[{'nome': 'Teste', 'codigo': '1'}],
        mapping={'name': 'nome', 'code': 'codigo'},
        activate=True,
    )
    duplicate_path = tmp_path / 'catalogo-copia.csv'
    duplicate_path.write_text('nome,codigo\nTeste,2\n', encoding='utf-8')
    duplicate = service.register_spreadsheet_upload(
        db,
        file_name='catalogo.csv',
        stored_path=str(duplicate_path),
        file_size_bytes=duplicate_path.stat().st_size,
        columns=['nome', 'codigo'],
        preview_rows=[{'nome': 'Teste', 'codigo': '2'}],
        mapping={'name': 'nome', 'code': 'codigo'},
        activate=False,
    )

    result = service.delete_upload(db, upload.id)

    assert result['deleted_upload_id'] == upload.id
    assert file_path.exists() is False
    assert duplicate_path.exists() is False
    assert db.get(AgentSpreadsheetUpload, upload.id) is None
    assert db.get(AgentSpreadsheetUpload, duplicate.id) is None
    assert service.active_spreadsheet_payload(db) is None
