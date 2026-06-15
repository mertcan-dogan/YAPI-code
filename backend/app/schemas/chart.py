"""CR-007-C — Chart spec schema + strict validation.

The agent's ``create_chart`` tool (agent_tools.py) emits a chart spec from data
it has ALREADY fetched via the read-only tools. This schema is the guard rail:
it rejects malformed/empty data so the model cannot invent chart points. The
frontend (CR-007-G) renders these specs verbatim with Recharts.
"""
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, model_validator

# Yapı palette (§4.1): navy / amber / green / red, then the CR-004 chart colours.
# Series missing a `color` are assigned from this list, cycling.
YAPI_PALETTE = [
    "#1B2B4B",  # navy
    "#F59E0B",  # amber
    "#10B981",  # green
    "#EF4444",  # red
    "#2563EB",  # brand (CR-004)
    "#06B6D4",  # brand2 (CR-004)
    "#0E1525",  # primary (CR-004)
    "#93C5FD",  # light blue (CR-004)
]

MAX_SERIES = 8
MAX_ROWS = 60


def _coerce_numeric(val, idx: int, key: str) -> float:
    """Return val as a float, or raise. Booleans are not numeric here."""
    if isinstance(val, bool):
        raise ValueError(f"{idx}. satırda '{key}' sayısal değil")
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        try:
            return float(val)
        except ValueError:
            pass
    raise ValueError(f"{idx}. satırda '{key}' sayısal değil")


class ChartSeries(BaseModel):
    key: str = Field(min_length=1)
    label: str = Field(min_length=1)
    type: Literal["line", "bar"]
    color: str | None = None


class ChartSpec(BaseModel):
    chart_type: Literal["line", "bar", "composed"]
    title: str = Field(min_length=1)
    x_key: str = Field(min_length=1)
    series: list[ChartSeries]
    data: list[dict]
    currency: Literal["TRY", "EUR", "USD"] | None = None
    source_note: str = ""

    @model_validator(mode="after")
    def _validate(self) -> "ChartSpec":
        if not self.series:
            raise ValueError("En az bir seri gerekli")
        if len(self.series) > MAX_SERIES:
            raise ValueError(f"En fazla {MAX_SERIES} seri olabilir")
        if not self.data:
            raise ValueError("Grafik verisi boş olamaz")
        if len(self.data) > MAX_ROWS:
            raise ValueError(f"En fazla {MAX_ROWS} satır olabilir")

        # Reject duplicate series keys (would silently overwrite on the client).
        keys = [s.key for s in self.series]
        if len(set(keys)) != len(keys):
            raise ValueError("Seri anahtarları benzersiz olmalı")

        for idx, row in enumerate(self.data):
            if self.x_key not in row:
                raise ValueError(f"{idx}. satırda x ekseni anahtarı '{self.x_key}' eksik")
            for s in self.series:
                if s.key not in row:
                    raise ValueError(f"{idx}. satırda '{s.key}' değeri eksik")
                # The read-only tools return money as strings ('12345.67'), so the
                # agent will pass numeric strings — accept and coerce them to float
                # so the frontend receives a number, but reject genuine non-numerics.
                row[s.key] = _coerce_numeric(row[s.key], idx, s.key)

        # Fill missing series colours from the Yapı palette, cycling.
        for i, s in enumerate(self.series):
            if not s.color:
                s.color = YAPI_PALETTE[i % len(YAPI_PALETTE)]
        return self


__all__ = ["ChartSpec", "ChartSeries", "YAPI_PALETTE", "MAX_SERIES", "MAX_ROWS", "ValidationError"]
