"""CR-002-C: reminders colour rules."""
from app.api.reminders import _colours, _days_label


def test_overdue_is_red():
    border, bg = _colours(-3, paid=False)
    assert border == "#EF4444" and bg == "#FEF2F2"
    assert _days_label(-3) == "3 gün gecikti"


def test_due_today_is_red():
    border, bg = _colours(0, paid=False)
    assert border == "#EF4444" and bg == "#FEF2F2"
    assert _days_label(0) == "Bugün"


def test_within_7_days_amber():
    assert _colours(5, paid=False) == ("#F59E0B", "#FFFBEB")


def test_8_to_30_days_yellow():
    assert _colours(20, paid=False) == ("#EAB308", "#FEFCE8")


def test_31_to_60_days_blue():
    assert _colours(45, paid=False) == ("#93C5FD", "#EFF6FF")


def test_paid_green():
    assert _colours(10, paid=True) == ("#10B981", "#F0FDF4")
