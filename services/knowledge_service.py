from __future__ import annotations

import csv
import datetime as dt
import io
import json
import os
import re
import time
from pathlib import Path
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from models import AgentSpreadsheetUpload
from services.agent_settings_service import DEFAULT_PRIORITY, get_agent_settings
from services.catalog_service import CatalogService

try:
    import openpyxl
except Exception:  # pragma: no cover
    openpyxl = None

try:
    import oracledb
except Exception:  # pragma: no cover
    oracledb = None


def _safe_identifier(value: str) -> bool:
    return bool(re.fullmatch(r'[A-Za-z0-9_$.]+', str(value or '').strip()))


def _json_safe(value: Any) -> Any:
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _normalize_header(value: Any) -> str:
    normalized = str(value or '').strip().lower()
    normalized = re.sub(r'[^a-z0-9]+', '_', normalized)
    return normalized.strip('_')


class KnowledgeService:
    def __init__(self, storage_dir: str | Path | None = None) -> None:
        self.storage_dir = Path(storage_dir or os.getenv('AGENT_SPREADSHEET_DIR', 'data/agent-spreadsheets'))
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.catalog = CatalogService()

    def register_spreadsheet_upload(
        self,
        db: Session,
        *,
        file_name: str,
        stored_path: str,
        file_size_bytes: int,
        columns: list[str],
        preview_rows: list[dict],
        mapping: dict[str, str],
        activate: bool,
    ) -> AgentSpreadsheetUpload:
        if activate:
            db.execute(update(AgentSpreadsheetUpload).values(is_active=False))
        item = AgentSpreadsheetUpload(
            file_name=file_name,
            stored_path=stored_path,
            file_size_bytes=int(file_size_bytes or 0),
            file_extension=Path(file_name).suffix.lower(),
            columns_json=json.dumps(_json_safe(columns), ensure_ascii=False),
            preview_rows_json=json.dumps(_json_safe(preview_rows), ensure_ascii=False),
            mapping_json=json.dumps(_json_safe(mapping), ensure_ascii=False),
            is_active=bool(activate),
            validation_status='valid',
            validation_message='Arquivo validado.',
        )
        db.add(item)
        db.commit()
        db.refresh(item)
        return item

    def validate_upload_bytes(self, file_name: str, payload: bytes, max_size_bytes: int = 5 * 1024 * 1024) -> dict[str, Any]:
        name = str(file_name or '').strip()
        if not name:
            raise ValueError('Arquivo inválido.')
        extension = Path(name).suffix.lower()
        if extension not in {'.csv', '.xlsx'}:
            raise ValueError('Formato não suportado. Use CSV ou XLSX.')
        if not payload:
            raise ValueError('Arquivo vazio.')
        if len(payload) > max_size_bytes:
            raise ValueError('Arquivo excede o limite permitido.')

        if extension == '.csv':
            decoded = payload.decode('utf-8-sig')
            reader = csv.DictReader(decoded.splitlines())
            columns = reader.fieldnames or []
            preview_rows = []
            for index, row in enumerate(reader):
                preview_rows.append(row)
                if index >= 9:
                    break
            return {'columns': columns, 'preview_rows': preview_rows, 'mapping': self.suggest_mapping(columns)}

        if openpyxl is None:
            raise ValueError('Leitura de XLSX indisponível no ambiente.')
        workbook = openpyxl.load_workbook(io.BytesIO(payload), read_only=True, data_only=True)
        sheet = workbook.active
        values = list(sheet.values)
        if not values:
            raise ValueError('Planilha vazia.')
        columns = [str(value or '').strip() for value in values[0]]
        preview_rows = []
        for row_index, raw in enumerate(values[1:]):
            preview_rows.append({columns[index]: raw[index] if index < len(raw) else '' for index in range(len(columns))})
            if row_index >= 9:
                break
        return {'columns': columns, 'preview_rows': preview_rows, 'mapping': self.suggest_mapping(columns)}

    def suggest_mapping(self, columns: list[str]) -> dict[str, str]:
        aliases = {
            'name': (
                'nome',
                'produto',
                'descricao',
                'descrição',
                'descricao_pai',
                'descrição_pai',
                'item',
                'name',
            ),
            'code': (
                'codigo',
                'código',
                'cod_item',
                'sku',
                'referencia',
                'referência',
                'code',
                'id_produto',
            ),
            'description': (
                'descricao',
                'descrição',
                'descricao_pai',
                'descrição_pai',
                'detalhe',
                'observacao',
                'observação',
                'description',
            ),
            'price': (
                'preco',
                'preço',
                'valor',
                'custo_produto',
                'custo_medio',
                'custo_médio',
                'price',
            ),
            'stock': (
                'estoque',
                'saldo',
                'qtd',
                'quantidade',
                'nro_pecas',
                'nro_peças',
                'stock',
            ),
            'category': (
                'categoria',
                'grupo',
                'familia',
                'família',
                'departamento',
                'category',
            ),
        }

        original_by_normalized = {_normalize_header(column): column for column in columns}
        mapping: dict[str, str] = {}
        for target, candidates in aliases.items():
            selected = ''
            for candidate in candidates:
                selected = original_by_normalized.get(_normalize_header(candidate), '')
                if selected:
                    break
            mapping[target] = selected
        return mapping

    def persist_upload_file(self, file_name: str, payload: bytes) -> Path:
        target = self.storage_dir / f'{int(time.time() * 1000)}-{Path(file_name).name}'
        target.write_bytes(payload)
        return target

    def active_spreadsheet_payload(self, db: Session) -> dict[str, Any] | None:
        item = db.scalar(
            select(AgentSpreadsheetUpload)
            .where(AgentSpreadsheetUpload.is_active.is_(True))
            .order_by(AgentSpreadsheetUpload.updated_at.desc(), AgentSpreadsheetUpload.id.desc())
        )
        if item is None:
            return None
        return {
            'id': item.id,
            'file_name': item.file_name,
            'stored_path': item.stored_path,
            'columns': json.loads(item.columns_json or '[]'),
            'preview_rows': json.loads(item.preview_rows_json or '[]'),
            'mapping': json.loads(item.mapping_json or '{}'),
            'is_active': bool(item.is_active),
            'validation_status': item.validation_status,
            'validation_message': item.validation_message,
        }

    def latest_spreadsheet_payload(self, db: Session, upload_id: int | None = None) -> dict[str, Any] | None:
        stmt = select(AgentSpreadsheetUpload)
        if upload_id:
            stmt = stmt.where(AgentSpreadsheetUpload.id == upload_id)
        stmt = stmt.order_by(AgentSpreadsheetUpload.updated_at.desc(), AgentSpreadsheetUpload.id.desc())
        item = db.scalar(stmt)
        if item is None:
            return None
        return {
            'id': item.id,
            'file_name': item.file_name,
            'stored_path': item.stored_path,
            'columns': json.loads(item.columns_json or '[]'),
            'preview_rows': json.loads(item.preview_rows_json or '[]'),
            'mapping': json.loads(item.mapping_json or '{}'),
            'is_active': bool(item.is_active),
            'validation_status': item.validation_status,
            'validation_message': item.validation_message,
        }

    def activate_upload(self, db: Session, upload_id: int, mapping: dict[str, str]) -> dict[str, Any]:
        item = db.get(AgentSpreadsheetUpload, upload_id)
        if item is None:
            raise ValueError('Planilha não encontrada.')
        db.execute(update(AgentSpreadsheetUpload).values(is_active=False))
        item.mapping_json = json.dumps(mapping or {}, ensure_ascii=False)
        item.is_active = True
        item.validation_status = 'active'
        item.validation_message = 'Planilha ativa para consulta.'
        db.add(item)
        db.commit()
        db.refresh(item)
        return self.latest_spreadsheet_payload(db, upload_id)

    def delete_upload(self, db: Session, upload_id: int) -> dict[str, Any]:
        item = db.get(AgentSpreadsheetUpload, upload_id)
        if item is None:
            raise ValueError('Planilha não encontrada.')
        same_name_uploads = db.scalars(
            select(AgentSpreadsheetUpload).where(AgentSpreadsheetUpload.file_name == item.file_name)
        ).all()

        for upload in same_name_uploads:
            stored_path = Path(str(upload.stored_path or '')).expanduser()
            if stored_path.exists() and stored_path.is_file():
                stored_path.unlink()
            db.delete(upload)
        db.commit()
        return {
            'deleted_upload_id': upload_id,
            'deleted_count': len(same_name_uploads),
            'active_upload': self.active_spreadsheet_payload(db),
            'latest_upload': self.latest_spreadsheet_payload(db),
        }

    def resolve(self, db: Session, *, customer_message: str) -> dict[str, Any]:
        settings = get_agent_settings(db)
        try:
            priority = json.loads(settings.knowledge_priority_json or '[]')
        except Exception:
            priority = DEFAULT_PRIORITY
        priority = [item for item in priority if item in {'manual', 'spreadsheet', 'database'}] or DEFAULT_PRIORITY

        for source in priority:
            if source == 'manual':
                result = self._from_manual(settings.manual_knowledge_enabled, settings.manual_knowledge_text, customer_message)
            elif source == 'spreadsheet':
                result = self._from_spreadsheet(db, customer_message)
            else:
                result = self._from_database(settings, customer_message)
            if result is not None:
                return result

        return {
            'source': 'none',
            'matched_product': None,
            'answer_context': '',
            'confidence_hint': 0.0,
        }

    def _from_manual(self, enabled: bool, text_value: str, customer_message: str) -> dict[str, Any] | None:
        if not enabled or not str(text_value or '').strip():
            return None
        return {
            'source': 'manual',
            'matched_product': None,
            'answer_context': str(text_value).strip(),
            'confidence_hint': 0.72 if customer_message else 0.5,
        }

    def _mapped_rows(self, upload_payload: dict[str, Any]) -> list[dict]:
        mapping = upload_payload.get('mapping') or {}
        preview_rows = upload_payload.get('preview_rows') or []
        if preview_rows:
            return [self._apply_mapping(row, mapping) for row in preview_rows]
        stored_path = Path(str(upload_payload.get('stored_path') or ''))
        if not stored_path.exists():
            return []
        if stored_path.suffix.lower() == '.csv':
            with stored_path.open('r', encoding='utf-8-sig', newline='') as handle:
                reader = csv.DictReader(handle)
                return [self._apply_mapping(row, mapping) for row in reader]
        if stored_path.suffix.lower() == '.xlsx' and openpyxl is not None:
            workbook = openpyxl.load_workbook(stored_path, read_only=True, data_only=True)
            sheet = workbook.active
            values = list(sheet.values)
            if not values:
                return []
            headers = [str(value or '').strip() for value in values[0]]
            rows: list[dict] = []
            for raw in values[1:]:
                row = {headers[index]: raw[index] if index < len(raw) else '' for index in range(len(headers))}
                rows.append(self._apply_mapping(row, mapping))
            return rows
        return []

    def _apply_mapping(self, row: dict[str, Any], mapping: dict[str, str]) -> dict[str, Any]:
        mapped = {}
        for target in ('name', 'code', 'description', 'price', 'stock', 'category'):
            source = str(mapping.get(target) or '').strip()
            mapped[target] = row.get(source, '') if source else ''
        return mapped

    def _from_spreadsheet(self, db: Session, customer_message: str) -> dict[str, Any] | None:
        upload = self.active_spreadsheet_payload(db)
        if upload is None:
            return None
        rows = self._mapped_rows(upload)
        product = self.catalog.find_product(rows, customer_message)
        if product is None:
            return None
        context = self._build_product_context(product)
        return {
            'source': 'spreadsheet',
            'matched_product': product,
            'answer_context': context,
            'confidence_hint': 0.88,
        }

    def _from_database(self, settings, customer_message: str) -> dict[str, Any] | None:
        if not settings.db_enabled:
            return None
        if settings.db_type != 'oracle':
            return None
        if oracledb is None:
            return None
        if not settings.db_host or not settings.db_service or not settings.db_user or not settings.db_password_encrypted:
            return None
        if not _safe_identifier(settings.db_view_name):
            return None

        password = ''
        try:
            from services.agent_settings_service import decrypt_secret

            password = decrypt_secret(settings.db_password_encrypted)
        except Exception:
            return None

        dsn = f'{settings.db_host}:{settings.db_port}/{settings.db_service}'
        try:
            with oracledb.connect(user=settings.db_user, password=password, dsn=dsn, expire_time=1) as connection:
                connection.call_timeout = int(settings.db_timeout_seconds or 5) * 1000
                cursor = connection.cursor()
                cursor.execute(f'SELECT * FROM {settings.db_view_name} FETCH FIRST 50 ROWS ONLY')
                columns = [str(col[0]).lower() for col in cursor.description or []]
                rows = []
                for raw in cursor.fetchmany(50):
                    row = {columns[index]: raw[index] if index < len(raw) else '' for index in range(len(columns))}
                    rows.append(row)
        except Exception:
            return None

        product = self.catalog.find_product(rows, customer_message)
        if product is None:
            return None
        return {
            'source': 'database',
            'matched_product': product,
            'answer_context': self._build_product_context(product),
            'confidence_hint': 0.91,
        }

    def test_database_connection(self, settings) -> dict[str, Any]:
        if not settings.db_enabled:
            return {'ok': False, 'message': 'Fonte de banco está desativada.'}
        if settings.db_type != 'oracle':
            return {'ok': False, 'message': 'Tipo de banco não suportado no v1.'}
        if oracledb is None:
            return {'ok': False, 'message': 'Driver Oracle indisponível no ambiente.'}
        if not _safe_identifier(settings.db_view_name):
            return {'ok': False, 'message': 'Nome da view inválido.'}

        try:
            from services.agent_settings_service import decrypt_secret

            password = decrypt_secret(settings.db_password_encrypted)
            dsn = f'{settings.db_host}:{settings.db_port}/{settings.db_service}'
            with oracledb.connect(user=settings.db_user, password=password, dsn=dsn, expire_time=1) as connection:
                connection.call_timeout = int(settings.db_timeout_seconds or 5) * 1000
                cursor = connection.cursor()
                cursor.execute(f'SELECT * FROM {settings.db_view_name} FETCH FIRST 1 ROWS ONLY')
                cursor.fetchone()
            return {'ok': True, 'message': 'Conexão validada.'}
        except Exception:
            return {'ok': False, 'message': 'Não foi possível validar a fonte.'}

    def _build_product_context(self, product: dict[str, Any]) -> str:
        chunks = []
        if product.get('name'):
            chunks.append(f"Produto: {product['name']}.")
        if product.get('code'):
            chunks.append(f"Código: {product['code']}.")
        if product.get('description'):
            chunks.append(f"Descrição: {product['description']}.")
        if product.get('price'):
            chunks.append(f"Preço: {product['price']}.")
        if product.get('stock'):
            chunks.append(f"Estoque: {product['stock']}.")
        if product.get('category'):
            chunks.append(f"Categoria: {product['category']}.")
        return ' '.join(chunks)
