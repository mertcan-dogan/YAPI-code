"""CR-001-B: 'Kontenjan' replaced with 'Öngörülemeyen Giderler' in UI strings."""
from app.constants import COST_CATEGORIES


def test_contingency_label_updated():
    assert COST_CATEGORIES["contingency"] == "Öngörülemeyen Giderler"


def test_no_kontenjan_in_category_labels():
    for label in COST_CATEGORIES.values():
        assert "Kontenjan" not in label
        assert "Beklenmedik" not in label


def test_db_column_name_unchanged():
    # CR-001-B must NOT rename DB columns / Python identifiers.
    from app.models.project import Project

    assert hasattr(Project, "contingency_pct")
