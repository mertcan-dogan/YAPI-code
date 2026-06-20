"""TCMB daily USD/TRY rate service (CR-014-A).

FEED CHOICE — **TCMB daily XML, no API key required.**
  - Today:      https://www.tcmb.gov.tr/kurlar/today.xml
  - Historical: https://www.tcmb.gov.tr/kurlar/YYYYMM/DDMMYYYY.xml
We read the USD **"ForexSelling" (Döviz Satış)** field consistently — that is the
official selling rate a buyer of USD pays, the right basis for valuing TRY
obligations in USD. (EVDS offers richer history but needs a free API key; if we
ever switch we must add the key to config — we do NOT hardcode one here.)

Design (CR-014 §1.2):
  - ``rate_as_of(db, d)`` is the core lookup: return the USD/TRY rate for ``d``;
    if that day has no rate (weekend / holiday / not yet published) walk back to
    the most recent prior business-day rate.
  - Lazy fetch + cache: every fetched rate is persisted in ``fx_rates`` so each
    date is fetched at most once.
  - Graceful degradation: a fetch FAILURE (network/HTTP error) never raises to
    the caller — we fall back to the last known cached rate and log it, so a save
    is never blocked. A legitimately empty day (404) just continues the walk-back.

TRY is the system of record; USD is a derived view (§0.2). This module only
sources the rate; per-row USD snapshots are CR-014-B.
"""
import logging
from datetime import date, timedelta
from decimal import Decimal
from xml.etree import ElementTree as ET

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.calculations.money import D, money
from app.config import settings
from app.models.fx_rate import FxRate

logger = logging.getLogger(__name__)

TCMB_TODAY_URL = "https://www.tcmb.gov.tr/kurlar/today.xml"
TCMB_BASE_URL = "https://www.tcmb.gov.tr/kurlar"
_FOUR_PLACES = Decimal("0.0001")
# How many days to walk back looking for a business-day rate before giving up
# (covers long public-holiday stretches; bayram closures are well under this).
MAX_WALK_BACK_DAYS = 10


def _q4(value) -> Decimal:
    return Decimal(str(value)).quantize(_FOUR_PLACES)


def _tcmb_url(d: date, today: date | None = None) -> str:
    """today.xml for the current day, the dated historical file otherwise."""
    if d == (today or date.today()):
        return TCMB_TODAY_URL
    return f"{TCMB_BASE_URL}/{d:%Y%m}/{d:%d%m%Y}.xml"


def parse_usd_forex_selling(xml_text: str) -> Decimal | None:
    """Pull the USD ForexSelling value out of a TCMB kurlar XML document.

    Returns the rate as a Decimal, or None if the document has no USD/ForexSelling
    (e.g. an unexpected payload). Pure + side-effect free so it is unit-testable
    without the network. TCMB uses a '.' decimal separator; we normalise a stray
    ',' just in case.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None
    node = root.find(".//Currency[@Kod='USD']/ForexSelling")
    if node is None or not (node.text or "").strip():
        return None
    raw = node.text.strip().replace(",", ".")
    try:
        return _q4(raw)
    except (ArithmeticError, ValueError):
        return None


def _fetch_tcmb_rate(d: date, today: date | None = None) -> Decimal | None:
    """Fetch the USD ForexSelling rate for ``d`` from TCMB.

    Returns the rate, or None when that day legitimately has no published file
    (404 — weekend / holiday / future). Raises on transport/HTTP errors so the
    caller can treat a genuine FAILURE differently from an empty day. This is the
    single network boundary — tests monkeypatch it.
    """
    url = _tcmb_url(d, today)
    resp = httpx.get(url, timeout=10, headers={"User-Agent": "yapi-fx/1.0"})
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return parse_usd_forex_selling(resp.text)


def _get_cached(db: Session, d: date) -> Decimal | None:
    row = db.get(FxRate, d)
    return row.usd_try if row is not None else None


def _cache(db: Session, d: date, rate: Decimal, source: str = "TCMB") -> Decimal:
    """Persist a fetched rate, tolerating a concurrent insert of the same day."""
    try:
        with db.begin_nested():
            db.add(FxRate(rate_date=d, usd_try=_q4(rate), source=source))
    except IntegrityError:
        # Another path cached this date first — use the existing row.
        pass
    cached = _get_cached(db, d)
    return cached if cached is not None else _q4(rate)


def _last_known(db: Session, on_or_before: date | None = None) -> Decimal | None:
    """Most recent cached rate (optionally on/before a date) — the fallback."""
    stmt = select(FxRate).order_by(FxRate.rate_date.desc())
    if on_or_before is not None:
        stmt = stmt.where(FxRate.rate_date <= on_or_before)
    row = db.execute(stmt.limit(1)).scalar_one_or_none()
    return row.usd_try if row is not None else None


def rate_as_of(db: Session, d: date, *, today: date | None = None) -> Decimal | None:
    """Return the USD/TRY rate effective for ``d`` (CR-014 §1.2, the core lookup).

    Walks back from ``d`` to the most recent business-day rate, fetching+caching
    lazily. On a fetch FAILURE, falls back to the last known cached rate and logs
    it — never raises, so callers' saves are never blocked. Returns None only when
    nothing is available at all (empty table + no reachable feed).
    """
    cur = d
    for _ in range(MAX_WALK_BACK_DAYS + 1):
        cached = _get_cached(db, cur)
        if cached is not None:
            return cached
        # Live fetch is gated so tests never hit the network; the cache-based
        # walk-back above still resolves seeded rates with it off.
        if settings.fx_live_fetch:
            try:
                fetched = _fetch_tcmb_rate(cur, today)
            except Exception as exc:  # noqa: BLE001 — degrade on ANY transport/parse error
                fallback = _last_known(db, on_or_before=d)
                logger.warning(
                    "TCMB rate fetch failed for %s (%s); falling back to last known rate %s",
                    cur, exc, fallback,
                )
                return fallback
            if fetched is not None:
                return _cache(db, cur, fetched)
        cur -= timedelta(days=1)  # empty day (weekend/holiday) — keep walking back

    # Walked the whole window with no published rate — use the last known cache.
    fallback = _last_known(db, on_or_before=d)
    logger.warning("No TCMB rate within %s days of %s; using last known %s",
                   MAX_WALK_BACK_DAYS, d, fallback)
    return fallback


# --------------------------------------------------------------------------- #
# CR-014-B — per-row USD snapshots (the relevant-date rule)
# --------------------------------------------------------------------------- #
def relevant_date_for_cost(cost) -> date:
    """Cost relevant date: the payment date once paid (LOCK), else entry_date
    (PROVISIONAL) (CR-014 §2.2)."""
    if cost.payment_status == "paid" and cost.date_paid is not None:
        return cost.date_paid
    return cost.entry_date


def relevant_date_for_invoice(inv) -> date:
    """Hakediş relevant date: the receipt date once paid (LOCK), else invoice_date
    (PROVISIONAL) (CR-014 §2.2)."""
    if inv.payment_status == "paid" and inv.date_received is not None:
        return inv.date_received
    return inv.invoice_date


def _apply_usd_snapshot(db: Session, obj, relevant: date) -> bool:
    """Set ``fx_rate_usd`` (the rate used) + ``amount_usd`` (= amount_try / rate,
    exact to the cent) from the rate at ``relevant``. If no rate is available
    (pre-history / total fetch failure), leave the USD fields untouched (null on a
    fresh row) and DO NOT raise — a save is never blocked (§2.2). Returns True when
    a snapshot was applied."""
    rate = rate_as_of(db, relevant)
    if rate is None or rate == 0:
        return False
    obj.fx_rate_usd = _q4(rate)
    obj.amount_usd = money(D(obj.amount_try) / rate)
    return True


def snapshot_cost_usd(db: Session, cost) -> bool:
    """(Re)compute a cost entry's USD snapshot at its relevant date. Provisional
    until paid; re-snapshots at the payment-date rate once paid (the lock)."""
    return _apply_usd_snapshot(db, cost, relevant_date_for_cost(cost))


def snapshot_invoice_usd(db: Session, inv) -> bool:
    """(Re)compute a hakediş's USD snapshot at its relevant date. Provisional until
    paid; re-snapshots at the receipt-date rate once paid (the lock)."""
    return _apply_usd_snapshot(db, inv, relevant_date_for_invoice(inv))


def _apply_usd_snapshot_fields(
    db: Session, obj, relevant: date, *, try_field: str, usd_field: str
) -> bool:
    """Like ``_apply_usd_snapshot`` but for rows whose TRY/USD columns are not the
    cost/invoice ``amount_try``/``amount_usd`` pair (e.g. a unit sale's
    ``sale_price_try``/``sale_price_usd``). Same rule: derive USD = TRY ÷ rate at
    ``relevant``; leave USD untouched + never raise when no rate is available."""
    rate = rate_as_of(db, relevant)
    if rate is None or rate == 0:
        return False
    obj.fx_rate_usd = _q4(rate)
    setattr(obj, usd_field, money(D(getattr(obj, try_field)) / rate))
    return True


def snapshot_unit_sale_usd(db: Session, sale) -> bool:
    """(Re)compute a unit sale's USD snapshot at its ``sale_date`` (CR-031-A,
    CR-014 pattern). A sale is a point-in-time event, so the rate is fixed at the
    sale date (no later 'lock' like cost/invoice payment)."""
    return _apply_usd_snapshot_fields(
        db, sale, sale.sale_date, try_field="sale_price_try", usd_field="sale_price_usd"
    )


def snapshot_landowner_payment_usd(db: Session, payment) -> bool:
    """(Re)compute a landowner payment's USD snapshot at its ``payment_date``
    (CR-031-B). Its TRY/USD columns are the ``amount_try``/``amount_usd`` pair, so
    the cost/invoice helper applies directly."""
    return _apply_usd_snapshot(db, payment, payment.payment_date)
