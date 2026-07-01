"""CR-056 — plan critique (structural, at compile). ADVISORY ONLY: this module
DETECTS issues in a proposed report/pano/beceri plan; it NEVER mutates the plan.

The founder's chosen behavior is *always ask with options* — so the agent surfaces
what it noticed and the user's click (client-side, deterministic) is what trims or
retitles the draft. Nothing here changes a widget; ``build_critique`` reads the
widgets and returns findings the ``ProposedActionCard`` renders as a summary + inline
badges + option buttons.

A finding = ``{type, widget_ids[], message (tr-TR)}``. The option buttons and the
trimming/retitle are owned by the FE (one place, so both structural and data-aware
findings resolve identically). Two structural checks live here because they need no
data (authoritative at compile, cheaply testable):

  * ``duplicate`` — two data widgets with the SAME signature
    ``(sorted metric ids, dims, filter key)`` → identical tables/charts (the DGN
    "Kalem Kalem Gider = Maliyet Kategorilerinin Dağılımı" case). Mirrors the CR-052
    ``_filter_key`` idea so widgets that share metric+dim but differ in filters are
    NOT twins.
  * ``mislabel`` — the title disagrees with the metric type: a "%"-titled widget over
    a ``currency`` metric (the "Maliyet Dağılımı (%)" plotting ₺), or a ₺/$-titled
    widget over a ``percent`` metric.

The data-aware checks (``empty_dimension`` / ``single_row`` / ``identical_data``) run
in the FE from the ``MiniReportPreview`` run-results already fetched — no extra
``/studio/run`` calls.
"""
from app.services.studio.catalog import METRICS


def _filter_key(spec: dict) -> tuple:
    """A stable, hashable key for a widget's filters (CR-052 idea), so two widgets
    with the same metric+dim but DIFFERENT filters are distinct, not twins."""
    out = []
    for f in (spec or {}).get("filters") or []:
        if isinstance(f, dict):
            out.append((str(f.get("field")), str(f.get("op")), str(f.get("value"))))
    return tuple(sorted(out))


def _signature(spec: dict) -> tuple:
    """The structural identity of a data widget: sorted metric ids + ordered dims +
    filter key. Two widgets with the same signature render the same table/chart."""
    spec = spec or {}
    metrics = tuple(sorted(str(m) for m in (spec.get("metrics") or [])))
    dims = tuple(str(d) for d in (spec.get("dimensions") or []))
    return (metrics, dims, _filter_key(spec))


def _metric_types(spec: dict) -> set:
    """The catalog ``type`` of each of the widget's metrics (unknown ids dropped)."""
    return {METRICS[m]["type"] for m in (spec or {}).get("metrics") or [] if m in METRICS}


def _title(w: dict) -> str:
    return str(w.get("title") or "").strip()


def _is_data_widget(w: dict) -> bool:
    spec = w.get("spec")
    return isinstance(spec, dict) and bool(spec.get("metrics"))


def build_critique(widgets: list[dict]) -> list[dict]:
    """Detect structural findings in a plan's widgets. ``widgets`` is a list of
    ``{id, title, spec}`` (text/report widgets — no metric spec — are ignored).
    Returns a possibly-empty findings list. NEVER mutates ``widgets`` (advisory)."""
    data = [w for w in (widgets or []) if _is_data_widget(w)]
    findings: list[dict] = []

    # duplicate — group by structural signature; any group of >1 is a twin set.
    by_sig: dict[tuple, list[dict]] = {}
    for w in data:
        by_sig.setdefault(_signature(w["spec"]), []).append(w)
    for group in by_sig.values():
        if len(group) > 1:
            titles = " ile ".join(f"‘{_title(w) or 'Adsız'}’" for w in group)
            findings.append({
                "type": "duplicate",
                "widget_ids": [str(w["id"]) for w in group],
                "message": f"{titles} aynı veriyi gösteriyor (aynı metrik ve kırılım).",
            })

    # mislabel — the title implies "%" but the metric is ₺ (or the reverse).
    for w in data:
        title = _title(w)
        types = _metric_types(w["spec"])
        if not types:
            continue
        if "%" in title and "percent" not in types:
            findings.append({
                "type": "mislabel",
                "widget_ids": [str(w["id"])],
                "message": (
                    f"‘{title}’ başlığı yüzde (%) ima ediyor ama metrik para birimi (₺). "
                    "Başlığı düzeltmek ister misin?"
                ),
            })
        elif ("₺" in title or "$" in title) and types == {"percent"}:
            findings.append({
                "type": "mislabel",
                "widget_ids": [str(w["id"])],
                "message": (
                    f"‘{title}’ başlığı para birimi ima ediyor ama metrik yüzde (%). "
                    "Başlığı düzeltmek ister misin?"
                ),
            })

    return findings


def critique_summary(findings: list[dict]) -> str:
    """A one-line tr-TR summary for the tool result (so the agent relays what it
    noticed and asks). ``''`` when there are no findings (the message is unchanged)."""
    if not findings:
        return ""
    return (
        "Taslağı hazırladım. Şunları fark ettim: "
        + " ".join(f["message"] for f in findings)
        + " Ne yapmamı istersin?"
    )
