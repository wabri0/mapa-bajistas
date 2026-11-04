from pathlib import Path

import pytest

RAW = Path(__file__).parents[1] / "data" / "raw"
# El Excel más reciente que haya en data/raw (en GitHub Actions se descarga antes de las pruebas)
_excels = sorted(RAW.rglob("NetShortPositions_*.xls"), key=lambda p: p.name)
EXCEL = _excels[-1] if _excels else None

requiere_excel = pytest.mark.skipif(EXCEL is None, reason="falta un Excel de la CNMV en data/raw")
