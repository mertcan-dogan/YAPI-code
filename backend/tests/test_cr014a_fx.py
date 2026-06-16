"""CR-014-A: fx_rates + TCMB rate service.

All TCMB HTTP is MOCKED (no real network). Covers the core lookup
(``rate_as_of``) with weekend walk-back, lazy fetch+cache, the graceful
fallback on fetch failure, and the XML parsing / 404 boundary.
"""
from datetime import date
from decimal import Decimal

import pytest

from app.models.fx_rate import FxRate
from app.services import fx


# TCMB-style daily XML (period decimal separator, as the real feed uses).
SAMPLE_XML = """<?xml version="1.0" encoding="ISO-8859-9"?>
<Tarih_Date Tarih="16.06.2026" Date="06/16/2026" Bulten_No="2026/114">
  <Currency CrossOrder="0" Kod="USD" CurrencyCode="USD">
    <Unit>1</Unit>
    <Isim>ABD DOLARI</Isim>
    <CurrencyName>US DOLLAR</CurrencyName>
    <ForexBuying>32.1100</ForexBuying>
    <ForexSelling>32.2345</ForexSelling>
    <BanknoteBuying>32.0900</BanknoteBuying>
    <BanknoteSelling>32.2700</BanknoteSelling>
  </Currency>
  <Currency CrossOrder="1" Kod="AUD" CurrencyCode="AUD">
    <Unit>1</Unit>
    <ForexSelling>21.5000</ForexSelling>
  </Currency>
</Tarih_Date>
"""


def _seed(db, d: date, rate: str, source="TCMB"):
    db.add(FxRate(rate_date=d, usd_try=Decimal(rate), source=source))
    db.commit()


class _FakeResp:
    def __init__(self, status_code=200, text=""):
        self.status_code = status_code
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400 and self.status_code != 404:
            raise RuntimeError(f"HTTP {self.status_code}")


# --------------------------------------------------------------------------- #
# XML parsing (pure)
# --------------------------------------------------------------------------- #
def test_parse_usd_forex_selling_exact():
    assert fx.parse_usd_forex_selling(SAMPLE_XML) == Decimal("32.2345")


def test_parse_usd_forex_selling_missing_usd():
    assert fx.parse_usd_forex_selling("<Tarih_Date></Tarih_Date>") is None
    assert fx.parse_usd_forex_selling("not xml at all") is None


# --------------------------------------------------------------------------- #
# _fetch_tcmb_rate HTTP boundary (httpx mocked)
# --------------------------------------------------------------------------- #
def test_fetch_parses_200(monkeypatch):
    monkeypatch.setattr(fx.httpx, "get", lambda *a, **k: _FakeResp(200, SAMPLE_XML))
    assert fx._fetch_tcmb_rate(date(2026, 6, 16), today=date(2026, 6, 16)) == Decimal("32.2345")


def test_fetch_404_returns_none(monkeypatch):
    # Weekend/holiday — TCMB has no file for that day.
    monkeypatch.setattr(fx.httpx, "get", lambda *a, **k: _FakeResp(404, ""))
    assert fx._fetch_tcmb_rate(date(2026, 6, 14), today=date(2026, 6, 16)) is None


# --------------------------------------------------------------------------- #
# rate_as_of — core lookup
# --------------------------------------------------------------------------- #
def test_rate_as_of_exact_cached_does_not_fetch(db, monkeypatch):
    d = date(2026, 6, 16)
    _seed(db, d, "32.5000")

    def _boom(*a, **k):
        raise AssertionError("must not fetch when the date is already cached")

    monkeypatch.setattr(fx, "_fetch_tcmb_rate", _boom)
    assert fx.rate_as_of(db, d) == Decimal("32.5000")


def test_rate_as_of_lazy_fetch_and_cache(db, monkeypatch):
    d = date(2026, 6, 16)
    calls = {"n": 0}

    def _fetch(dd, today=None):
        calls["n"] += 1
        return Decimal("33.0000")

    monkeypatch.setattr(fx, "_fetch_tcmb_rate", _fetch)
    assert fx.rate_as_of(db, d) == Decimal("33.0000")
    # Persisted to fx_rates...
    assert db.get(FxRate, d).usd_try == Decimal("33.0000")
    # ...and a second lookup is served from cache (fetched at most once).
    assert fx.rate_as_of(db, d) == Decimal("33.0000")
    assert calls["n"] == 1


def test_rate_as_of_weekend_walk_back(db, monkeypatch):
    sunday = date(2026, 6, 14)
    saturday = date(2026, 6, 13)
    friday = date(2026, 6, 12)
    assert sunday.weekday() == 6 and saturday.weekday() == 5 and friday.weekday() == 4

    def _fetch(d, today=None):
        # Only the Friday business day has a published rate.
        return Decimal("31.7500") if d == friday else None

    monkeypatch.setattr(fx, "_fetch_tcmb_rate", _fetch)
    # Asking for Sunday walks back Sun -> Sat -> Fri.
    assert fx.rate_as_of(db, sunday) == Decimal("31.7500")
    # The resolved business-day rate is cached under its own (Friday) date,
    # and no spurious rows are created for the empty weekend days.
    assert db.get(FxRate, friday) is not None
    assert db.get(FxRate, saturday) is None
    assert db.get(FxRate, sunday) is None


def test_rate_as_of_graceful_fallback_on_fetch_failure(db, monkeypatch):
    # A last-known rate exists from a prior day.
    _seed(db, date(2026, 6, 10), "30.0000")

    def _boom(d, today=None):
        raise RuntimeError("TCMB unreachable")

    monkeypatch.setattr(fx, "_fetch_tcmb_rate", _boom)
    # Fetch fails for the requested day -> fall back to the last known rate,
    # never raising (so a save is never blocked).
    assert fx.rate_as_of(db, date(2026, 6, 16)) == Decimal("30.0000")


def test_rate_as_of_none_when_empty_and_unreachable(db, monkeypatch):
    def _boom(d, today=None):
        raise RuntimeError("TCMB unreachable")

    monkeypatch.setattr(fx, "_fetch_tcmb_rate", _boom)
    # No cached rates at all and the feed is down -> None (caller leaves USD null).
    assert fx.rate_as_of(db, date(2026, 6, 16)) is None


def test_fx_rates_is_global_no_company_id():
    # Global reference table — must not be company-scoped.
    assert "company_id" not in FxRate.__table__.columns
    assert "rate_date" in FxRate.__table__.primary_key.columns
