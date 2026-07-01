"""CR-056 — AI plan critique (structural, at compile).

The agent NEVER auto-changes the plan. At compile ``propose_report`` /
``propose_dashboard`` / ``propose_skill`` attach an ADVISORY ``critique[]`` on the
proposed_action: ``duplicate`` (two data widgets with the same signature — the DGN
cost-by-category-twice repro) and ``mislabel`` (a "%"-titled currency widget). A
clean plan yields no findings, and the critique NEVER mutates the draft's widget
list — it's advisory data the user resolves client-side with options.
"""
from app.constants import ROLE_DIRECTOR
from app.services import agent_actions as actions
from app.services.studio.critique import build_critique, critique_summary


def _ids(seed, label="a"):
    return (seed[label]["company"].id,
            seed[label]["users"][ROLE_DIRECTOR].id,
            seed[label]["project"].id)


def _widget(wid, title, spec):
    return {"id": wid, "type": "table", "title": title,
            "layout": {"x": 0, "y": 0, "w": 6, "h": 4}, "spec": spec}


# --------------------------------------------------------------------------- #
# Pure detection — build_critique
# --------------------------------------------------------------------------- #
def test_duplicate_fires_on_same_signature():
    # The DGN repro: cost-by-category twice under different titles.
    spec = {"metrics": ["cost_try"], "dimensions": ["cost_category"], "viz": "table"}
    findings = build_critique([
        _widget("w1", "Kalem Kalem Gider", dict(spec)),
        _widget("w2", "Maliyet Kategorilerinin Dağılımı", dict(spec)),
    ])
    dups = [f for f in findings if f["type"] == "duplicate"]
    assert len(dups) == 1
    assert set(dups[0]["widget_ids"]) == {"w1", "w2"}
    assert "aynı veriyi" in dups[0]["message"]
    assert "Kalem Kalem Gider" in dups[0]["message"]


def test_duplicate_respects_filter_key():
    # Same metric+dim but DIFFERENT filters → not twins (CR-052 _filter_key idea).
    base = {"metrics": ["cost_try"], "dimensions": ["cost_category"], "viz": "table"}
    a = dict(base, filters=[{"field": "project", "op": "=", "value": "p1"}])
    b = dict(base, filters=[{"field": "project", "op": "=", "value": "p2"}])
    findings = build_critique([_widget("w1", "A", a), _widget("w2", "B", b)])
    assert not [f for f in findings if f["type"] == "duplicate"]


def test_mislabel_fires_on_percent_title_over_currency():
    findings = build_critique([
        _widget("w1", "Maliyet Dağılımı (%)",
                {"metrics": ["cost_try"], "dimensions": ["cost_category"], "viz": "bar"}),
    ])
    mis = [f for f in findings if f["type"] == "mislabel"]
    assert len(mis) == 1
    assert mis[0]["widget_ids"] == ["w1"]
    assert "yüzde" in mis[0]["message"]


def test_mislabel_fires_on_currency_title_over_percent():
    findings = build_critique([
        _widget("w1", "Kâr Marjı (₺)",
                {"metrics": ["margin_pct_current"], "dimensions": ["project"], "viz": "table"}),
    ])
    assert [f for f in findings if f["type"] == "mislabel"]


def test_clean_plan_has_no_findings():
    findings = build_critique([
        _widget("w1", "Maliyet Kategorileri",
                {"metrics": ["cost_try"], "dimensions": ["cost_category"], "viz": "table"}),
        _widget("w2", "Gelir",
                {"metrics": ["revenue"], "dimensions": ["month"], "viz": "line"}),
    ])
    assert findings == []


def test_text_and_specless_widgets_are_ignored():
    findings = build_critique([
        {"id": "t1", "type": "text", "title": "Not", "content": "x"},
        {"id": "e1", "type": "table", "title": "Boş", "spec": {"metrics": []}},
    ])
    assert findings == []


def test_critique_summary_only_when_findings():
    assert critique_summary([]) == ""
    s = critique_summary([{"type": "duplicate", "widget_ids": [], "message": "iki tablo aynı."}])
    assert "fark ettim" in s and "Ne yapmamı istersin" in s


# --------------------------------------------------------------------------- #
# Wired into the propose_* draft tools (advisory; plan never mutated)
# --------------------------------------------------------------------------- #
def test_propose_dashboard_attaches_duplicate_critique(db, seed):
    cid, uid, _ = _ids(seed)
    spec = {"metrics": ["cost_try"], "dimensions": ["cost_category"], "viz": "table"}
    widgets = [
        _widget("w1", "Kalem Kalem Gider", dict(spec)),
        _widget("w2", "Maliyet Kategorilerinin Dağılımı", dict(spec)),
    ]
    out = actions.propose_dashboard(db, cid, uid, title="DGN", widgets=widgets)
    pa = out["proposed_action"]
    crit = pa["critique"]
    assert [f["type"] for f in crit] == ["duplicate"]
    assert set(crit[0]["widget_ids"]) == {"w1", "w2"}
    # The plan is NEVER mutated by the critique — both widgets survive, in order.
    assert [w["id"] for w in pa["widgets"]] == ["w1", "w2"]
    # The tool message relays what was noticed and asks (the ask-with-options nudge).
    assert "fark ettim" in out["message"]


def test_propose_report_attaches_mislabel_critique(db, seed):
    cid, uid, _ = _ids(seed)
    spec = {"metrics": ["cost_try"], "dimensions": ["cost_category"], "viz": "bar"}
    out = actions.propose_report(db, cid, uid, title="Maliyet Dağılımı (%)", spec=spec)
    pa = out["proposed_action"]
    assert [f["type"] for f in pa["critique"]] == ["mislabel"]
    assert pa["critique"][0]["widget_ids"] == ["report"]
    # The spec is unchanged — advisory only.
    assert pa["spec"] == spec


def test_propose_report_clean_plan_no_findings(db, seed):
    cid, uid, _ = _ids(seed)
    spec = {"metrics": ["cost_try"], "dimensions": ["cost_category"], "viz": "table"}
    out = actions.propose_report(db, cid, uid, title="Maliyet Kategorileri", spec=spec)
    assert out["proposed_action"]["critique"] == []
    # Clean plan → the message is the ordinary draft message (no critique prefix).
    assert "fark ettim" not in out["message"]


def test_propose_skill_attaches_critique(db, seed):
    cid, uid, _ = _ids(seed)
    spec = {"metrics": ["cost_try"], "dimensions": ["cost_category"], "viz": "table"}
    widgets = [_widget("w1", "A", dict(spec)), _widget("w2", "B", dict(spec))]
    out = actions.propose_skill(db, cid, uid, name="Aylık Gider", widgets=widgets, format="xlsx")
    crit = out["proposed_action"]["critique"]
    assert [f["type"] for f in crit] == ["duplicate"]
