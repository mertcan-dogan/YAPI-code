"""fx_rates — global daily USD/TRY reference rates (CR-014-A).

A GLOBAL reference table: exchange rates are universal, so there is **no
company_id** and no company RLS filter — it is read-only to clients and written
only by the backend (service role). ``rate_date`` is the natural primary key
(one row per calendar day). Structure leaves room for ``eur_try`` later; v1 is
USD-only (CR-014 §1.1, §0.2).
"""
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class FxRate(Base):
    __tablename__ = "fx_rates"

    rate_date: Mapped[date] = mapped_column(Date, primary_key=True)
    usd_try: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="TCMB", server_default="TCMB")
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
