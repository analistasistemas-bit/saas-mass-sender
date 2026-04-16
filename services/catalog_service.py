from __future__ import annotations

import re
from typing import Any


def _normalize(value: Any) -> str:
    return re.sub(r'\s+', ' ', str(value or '').strip().lower())


class CatalogService:
    def find_product(self, rows: list[dict], query: str) -> dict | None:
        tokens = [token for token in re.split(r'[^a-zA-Z0-9]+', _normalize(query)) if token]
        if not tokens:
            return None

        best_row = None
        best_score = 0
        for row in rows:
            haystack = ' '.join(_normalize(v) for v in row.values())
            score = sum(1 for token in tokens if token in haystack)
            if score > best_score:
                best_score = score
                best_row = row
        if not best_row or best_score <= 0:
            return None
        return {
            'name': str(best_row.get('name') or best_row.get('nome') or '').strip(),
            'code': str(best_row.get('code') or best_row.get('codigo') or '').strip(),
            'description': str(best_row.get('description') or best_row.get('descricao') or '').strip(),
            'price': str(best_row.get('price') or best_row.get('preco') or '').strip(),
            'stock': str(best_row.get('stock') or best_row.get('estoque') or '').strip(),
            'category': str(best_row.get('category') or best_row.get('categoria') or '').strip(),
        }
