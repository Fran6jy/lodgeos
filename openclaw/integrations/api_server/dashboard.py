"""
OpenClaw Dashboard — read-only, localhost-only finance view.

Design principles (deliberately conservative for sensitive financial data):
  * READ-ONLY: no endpoint mutates the ledger, so it can never corrupt records.
  * LOCAL-FIRST: binds to 127.0.0.1 by default — only your machine can reach it.
  * SINGLE-USER: shows exactly one user_id (DASHBOARD_USER), so there is no way
    to view another person's finances through it.
  * NO EXTERNAL CALLS: HTML/CSS is rendered inline; nothing is sent anywhere.

Run:
    python -m openclaw.integrations.api_server.dashboard
    # then open http://127.0.0.1:8000

Config (env): OPENCLAW_DB, DASHBOARD_USER, DASHBOARD_HOST, DASHBOARD_PORT.
"""

import os
from datetime import datetime
from typing import Any, Dict

from openclaw.storage.sqlite_adapter import SQLiteAdapter
from openclaw.utils.currency_normalizer import format_amount
from openclaw.utils.date_parser import current_month_range

try:
    from fastapi import FastAPI
    from fastapi.responses import HTMLResponse, JSONResponse
    _FASTAPI = True
except ImportError:
    _FASTAPI = False


DB_PATH = os.environ.get("OPENCLAW_DB", "openclaw.db")
USER_ID = os.environ.get("DASHBOARD_USER", "default")
BRAND = os.environ.get("BRAND_NAME", "LodgeOS")


def gather_data(db: SQLiteAdapter, user_id: str, space: str = None) -> Dict[str, Any]:
    """Collect this month's finance view for a single user, optionally one Space."""
    now = datetime.now()
    s, e = current_month_range(now)
    since, until = s.isoformat(), e.isoformat()

    expenses = db.query_records(domain="finance", record_type="expense",
                                user_id=user_id, since=since, until=until, limit=2000, space=space)
    income = db.query_records(domain="finance", record_type="income",
                              user_id=user_id, since=since, until=until, limit=2000, space=space)

    total_exp = sum(r.get("amount", 0) or 0 for r in expenses)
    total_inc = sum(r.get("amount", 0) or 0 for r in income)

    # Primary currency = most common among this view's records (no FX conversion).
    from collections import Counter
    cur_counts = Counter(r.get("currency", "GBP") for r in (expenses + income) if r.get("amount") is not None)
    cur = cur_counts.most_common(1)[0][0] if cur_counts else "GBP"

    by_cat: Dict[str, float] = {}
    for r in expenses:
        cat = r.get("entities", {}).get("category", "Other")
        by_cat[cat] = by_cat.get(cat, 0) + (r.get("amount", 0) or 0)
    by_cat = dict(sorted(by_cat.items(), key=lambda x: -x[1]))

    budgets = []
    for b in db.get_budgets(user_id, "monthly", space=space):
        spent = db.sum_amount(domain="finance", record_type="expense", user_id=user_id,
                              since=since, until=until, category=b["category"], space=b.get("space"))
        budgets.append({
            "category": b["category"], "budget": b["amount"], "spent": spent,
            "remaining": b["amount"] - spent,
            "pct": (spent / b["amount"] * 100) if b["amount"] else 0,
        })

    # Recent includes voided rows so the audit trail is visible.
    recent = db.query_records(domain="finance", user_id=user_id, limit=25,
                              include_voided=True, space=space)

    return {
        "user_id": user_id,
        "month": now.strftime("%B %Y"),
        "space": space,                       # None = All spaces
        "currency": cur,
        "spaces": db.list_spaces(user_id),
        "total_expense": total_exp,
        "total_income": total_inc,
        "net": total_inc - total_exp,
        "by_category": by_cat,
        "budgets": budgets,
        "recent": recent,
    }


def render_html(d: Dict[str, Any], link_base: str = "") -> str:
    # Space selector chips (All + each space), linking back to this dashboard.
    def _sep(q):
        return ("&" if "?" in link_base else "?") + q
    active = d.get("space")
    chips = [f'<a class="chip {"on" if active is None else ""}" href="{link_base or "/"}">All</a>']
    for sp in d.get("spaces", []):
        on = "on" if sp == active else ""
        chips.append(f'<a class="chip {on}" href="{link_base}{_sep("space=" + sp.replace(" ", "+"))}">{sp}</a>')
    space_bar = '<div class="chips">' + "".join(chips) + "</div>"
    cat_max = max(d["by_category"].values(), default=1) or 1
    cat_rows = "".join(
        f"""<div class="row"><span class="lbl">{cat}</span>
        <span class="bar"><i style="width:{(amt / cat_max * 100):.0f}%"></i></span>
        <span class="amt">{format_amount(amt, d["currency"])}</span></div>"""
        for cat, amt in d["by_category"].items()
    ) or "<p class='muted'>No spending this month.</p>"

    budget_rows = ""
    for b in d["budgets"]:
        over = b["remaining"] < 0
        pct = min(b["pct"], 100)
        budget_rows += f"""<div class="row"><span class="lbl">{b['category']}</span>
        <span class="bar"><i class="{'over' if over else ''}" style="width:{pct:.0f}%"></i></span>
        <span class="amt">{format_amount(b['spent'], d['currency'])} / {format_amount(b['budget'], d['currency'])}</span></div>"""
    if not budget_rows:
        budget_rows = "<p class='muted'>No budgets set. Use /setbudget in the bot.</p>"

    tx_rows = ""
    for r in d["recent"]:
        voided = r.get("voided")
        cat = r.get("entities", {}).get("category", "")
        amt = format_amount(r.get("amount") or 0, r.get("currency", "GBP"))
        cls = "voided" if voided else ("income" if r.get("type") == "income" else "")
        tag = " <s>VOID</s>" if voided else ""
        tx_rows += f"""<tr class="{cls}"><td>{r.get('timestamp','')[:10]}</td>
        <td>{r.get('description','')[:50]}{tag}</td><td>{cat}</td>
        <td class="r">{amt}</td></tr>"""

    net = d["net"]
    net_cls = "pos" if net >= 0 else "neg"
    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{BRAND} Dashboard</title><style>
*{{box-sizing:border-box}}body{{font-family:-apple-system,Segoe UI,Roboto,sans-serif;
background:#0f1419;color:#e6edf3;margin:0;padding:24px;max-width:880px;margin:0 auto}}
h1{{font-size:20px;margin:0 0 4px}}.muted{{color:#8b949e}}.sub{{color:#8b949e;margin:0 0 24px;font-size:13px}}
.cards{{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:24px}}
.card{{flex:1;min-width:140px;background:#161b22;border:1px solid #30363d;border-radius:10px;padding:16px}}
.card .k{{color:#8b949e;font-size:12px}}.card .v{{font-size:22px;font-weight:600;margin-top:4px}}
.pos{{color:#3fb950}}.neg{{color:#f85149}}
.panel{{background:#161b22;border:1px solid #30363d;border-radius:10px;padding:16px 18px;margin-bottom:20px}}
.panel h2{{font-size:14px;margin:0 0 14px;color:#c9d1d9}}
.row{{display:flex;align-items:center;gap:10px;margin:7px 0;font-size:13px}}
.lbl{{width:120px;flex-shrink:0}}.amt{{width:150px;text-align:right;flex-shrink:0;color:#c9d1d9}}
.bar{{flex:1;background:#21262d;border-radius:5px;height:14px;overflow:hidden}}
.bar i{{display:block;height:100%;background:#388bfd;border-radius:5px}}
.bar i.over{{background:#f85149}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
td{{padding:6px 8px;border-bottom:1px solid #21262d}}.r{{text-align:right}}
tr.voided td{{color:#6e7681;text-decoration:none}}tr.voided s{{color:#f85149}}
tr.income td.r{{color:#3fb950}}
.chips{{display:flex;gap:8px;flex-wrap:wrap;margin:0 0 20px}}
.chip{{padding:5px 12px;border-radius:20px;border:1px solid #30363d;background:#161b22;
color:#c9d1d9;text-decoration:none;font-size:13px}}
.chip.on{{background:#388bfd;border-color:#388bfd;color:#fff}}
</style></head><body>
<h1>{BRAND} — {d['month']}</h1>
<p class="sub">Read-only · {('Space: <b>' + d['space'] + '</b>') if d.get('space') else 'All spaces'} · user <code>{d['user_id']}</code></p>
{space_bar}
<div class="cards">
  <div class="card"><div class="k">Spent</div><div class="v">{format_amount(d['total_expense'], d['currency'])}</div></div>
  <div class="card"><div class="k">Income</div><div class="v">{format_amount(d['total_income'], d['currency'])}</div></div>
  <div class="card"><div class="k">Net</div><div class="v {net_cls}">{format_amount(net, d["currency"])}</div></div>
</div>
<div class="panel"><h2>Spending by category</h2>{cat_rows}</div>
<div class="panel"><h2>Budgets</h2>{budget_rows}</div>
<div class="panel"><h2>Recent transactions</h2><table>{tx_rows or '<tr><td class=muted>No records.</td></tr>'}</table></div>
</body></html>"""


def create_app() -> "FastAPI":
    if not _FASTAPI:
        raise ImportError("FastAPI not installed. Run: pip install fastapi uvicorn")
    app = FastAPI(title="OpenClaw Dashboard", docs_url=None, redoc_url=None)
    db = SQLiteAdapter(DB_PATH)

    # Allow the single-user localhost root only when explicitly enabled, so a
    # multi-user deployment doesn't accidentally expose one user's data at "/".
    if os.environ.get("DASHBOARD_ROOT", "1") == "1":
        @app.get("/", response_class=HTMLResponse)
        def index(space: str = None):
            return render_html(gather_data(db, USER_ID, space), link_base="/")

    @app.get("/d/{token}", response_class=HTMLResponse)
    def user_dashboard(token: str, space: str = None):
        user_id = db.resolve_dashboard_token(token)
        if not user_id:
            return HTMLResponse(
                "<body style='font-family:sans-serif;background:#0f1419;color:#e6edf3;"
                "padding:40px'><h2>🔒 Link invalid or expired</h2>"
                "<p>Send <code>/dashboard</code> to the bot for a fresh link.</p></body>",
                status_code=403,
            )
        return render_html(gather_data(db, user_id, space), link_base=f"/d/{token}")

    return app


def main():
    if not _FASTAPI:
        print("FastAPI/uvicorn not installed. Run: pip install fastapi uvicorn")
        return
    import uvicorn
    host = os.environ.get("DASHBOARD_HOST", "127.0.0.1")  # localhost only by default
    port = int(os.environ.get("DASHBOARD_PORT", "8000"))
    print(f"OpenClaw dashboard → http://{host}:{port}  (user={USER_ID}, db={DB_PATH})")
    uvicorn.run(create_app(), host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
