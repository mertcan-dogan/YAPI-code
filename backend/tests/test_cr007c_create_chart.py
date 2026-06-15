"""CR-007-C — create_chart tool + chart spec validation.

create_chart never touches the DB; it validates a spec the agent built from data
it already fetched, fills default palette colours, coerces numeric strings, and
rejects malformed/empty data (§4.1).
"""
import pytest

from app.schemas.chart import MAX_ROWS, MAX_SERIES, YAPI_PALETTE
from app.services import agent_tools as T


def _valid_spec(**over):
    spec = {
        "chart_type": "line",
        "title": "Aylık Harcama",
        "x_key": "month",
        "series": [
            {"key": "total", "label": "Toplam", "type": "line"},
            {"key": "beton", "label": "Beton", "type": "line"},
        ],
        "data": [
            {"month": "2026-01", "total": 1000, "beton": 600},
            {"month": "2026-02", "total": 1500, "beton": 700},
        ],
        "currency": "TRY",
        "source_note": "Kaynak: maliyet kayıtları",
    }
    spec.update(over)
    return spec


def test_create_chart_valid_passes():
    out = T.create_chart(**_valid_spec())
    assert out["chart_type"] == "line"
    assert len(out["data"]) == 2
    assert out["currency"] == "TRY"


def test_create_chart_defaults_palette_colours():
    out = T.create_chart(**_valid_spec())
    assert out["series"][0]["color"] == YAPI_PALETTE[0]
    assert out["series"][1]["color"] == YAPI_PALETTE[1]


def test_create_chart_keeps_explicit_colour():
    spec = _valid_spec()
    spec["series"][0]["color"] = "#123456"
    out = T.create_chart(**spec)
    assert out["series"][0]["color"] == "#123456"


def test_create_chart_coerces_numeric_strings():
    # The read-only tools emit money as strings; create_chart must accept them.
    spec = _valid_spec(data=[{"month": "2026-01", "total": "1234.56", "beton": "600.00"}])
    out = T.create_chart(**spec)
    assert out["data"][0]["total"] == 1234.56
    assert isinstance(out["data"][0]["total"], float)


def test_create_chart_rejects_empty_data():
    with pytest.raises(T.ToolError):
        T.create_chart(**_valid_spec(data=[]))


def test_create_chart_rejects_missing_series_key_in_row():
    spec = _valid_spec(data=[{"month": "2026-01", "total": 1000}])  # 'beton' missing
    with pytest.raises(T.ToolError):
        T.create_chart(**spec)


def test_create_chart_rejects_missing_x_key_in_row():
    spec = _valid_spec(data=[{"total": 1000, "beton": 600}])  # no 'month'
    with pytest.raises(T.ToolError):
        T.create_chart(**spec)


def test_create_chart_rejects_non_numeric_value():
    spec = _valid_spec(data=[{"month": "2026-01", "total": "abc", "beton": 600}])
    with pytest.raises(T.ToolError):
        T.create_chart(**spec)


def test_create_chart_rejects_boolean_value():
    spec = _valid_spec(data=[{"month": "2026-01", "total": True, "beton": 600}])
    with pytest.raises(T.ToolError):
        T.create_chart(**spec)


def test_create_chart_rejects_too_many_series():
    series = [{"key": f"s{i}", "label": f"S{i}", "type": "line"} for i in range(MAX_SERIES + 1)]
    row = {"month": "2026-01", **{f"s{i}": 1 for i in range(MAX_SERIES + 1)}}
    with pytest.raises(T.ToolError):
        T.create_chart(**_valid_spec(series=series, data=[row]))


def test_create_chart_rejects_too_many_rows():
    data = [{"month": str(i), "total": 1, "beton": 1} for i in range(MAX_ROWS + 1)]
    with pytest.raises(T.ToolError):
        T.create_chart(**_valid_spec(data=data))


def test_create_chart_rejects_duplicate_series_keys():
    series = [
        {"key": "total", "label": "Toplam", "type": "line"},
        {"key": "total", "label": "Tekrar", "type": "line"},
    ]
    with pytest.raises(T.ToolError):
        T.create_chart(**_valid_spec(series=series))


def test_create_chart_rejects_bad_chart_type():
    with pytest.raises(T.ToolError):
        T.create_chart(**_valid_spec(chart_type="pie"))


def test_create_chart_composed_with_bar_and_line():
    spec = _valid_spec(chart_type="composed")
    spec["series"] = [
        {"key": "total", "label": "Toplam", "type": "bar"},
        {"key": "beton", "label": "Beton", "type": "line"},
    ]
    out = T.create_chart(**spec)
    assert out["chart_type"] == "composed"
    assert {s["type"] for s in out["series"]} == {"bar", "line"}
