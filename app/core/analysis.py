"""Indicators computed from stored CSVs. Pure functions, unit-tested."""
import math

from . import store


def _f(x):
    try:
        return None if x is None or x == "" else float(x)
    except (TypeError, ValueError):
        return None


def _pct(a, b):
    return None if a is None or not b else (a / b - 1) * 100


# ------------------------------------------------------------------ prices
def price_metrics(rows, index_rows=None):
    pts = [(r["date"], _f(r.get("adj_close")), _f(r.get("close"))) for r in rows]
    pts = [p for p in pts if p[1]]
    if not pts:
        return {}
    dates = [p[0] for p in pts]
    adj = [p[1] for p in pts]
    last_d, last = dates[-1], adj[-1]

    def back(n):
        return _pct(last, adj[-1 - n]) if len(adj) > n else None

    prev_year_end = [a for d, a in zip(dates, adj) if d < last_d[:4] + "-01-01"]
    ytd = _pct(last, prev_year_end[-1]) if prev_year_end else None
    days = _days(dates[0], last_d)
    cagr = ((last / adj[0]) ** (365.25 / days) - 1) * 100 if days > 365 else None

    rets = [math.log(adj[i] / adj[i - 1]) for i in range(1, len(adj))]
    r1y = rets[-252:]
    vol = _std(r1y) * math.sqrt(252) * 100 if len(r1y) > 20 else None

    peak, peak_d, mdd, mdd_from, mdd_to = adj[0], dates[0], 0.0, None, None
    for d, a in zip(dates, adj):
        if a > peak:
            peak, peak_d = a, d
        dd = a / peak - 1
        if dd < mdd:
            mdd, mdd_from, mdd_to = dd, peak_d, d

    beta = None
    if index_rows:
        idx = {r["date"]: _f(r.get("close")) for r in index_rows}
        beta = _beta(dates[-253:], adj[-253:], idx)

    def ma(n):
        return sum(adj[-n:]) / n if len(adj) >= n else None

    return {
        "last_date": last_d, "close": pts[-1][2], "adj_close": last,
        "open": _f(rows[-1].get("open")), "volume": _f(rows[-1].get("volume")),
        "chg_1d": back(1), "chg_1w": back(5), "chg_1m": back(21), "chg_3m": back(63),
        "chg_ytd": ytd, "chg_1y": back(252), "chg_all": _pct(last, adj[0]),
        "first_date": dates[0], "cagr": cagr, "volatility": vol,
        "max_drawdown": mdd * 100, "mdd_from": mdd_from, "mdd_to": mdd_to,
        "beta_1y": beta, "ma20": ma(20), "ma50": ma(50), "ma200": ma(200),
        "high_52w": max(adj[-252:]), "low_52w": min(adj[-252:]),
    }


def _days(a, b):
    import datetime as dt
    return (dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days


def _std(xs):
    if len(xs) < 2:
        return 0.0
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def _beta(dates, adj, idx):
    rs, rm = [], []
    for i in range(1, len(dates)):
        a, b = idx.get(dates[i - 1]), idx.get(dates[i])
        if a and b:
            rs.append(adj[i] / adj[i - 1] - 1)
            rm.append(b / a - 1)
    if len(rs) < 30:
        return None
    ms, mm = sum(rs) / len(rs), sum(rm) / len(rm)
    cov = sum((x - ms) * (y - mm) for x, y in zip(rs, rm)) / (len(rs) - 1)
    var = sum((y - mm) ** 2 for y in rm) / (len(rm) - 1)
    return cov / var if var else None


# ------------------------------------------------------------------ fundamentals
PAR_VALUE = 10000.0  # VND per share


def _consecutive(dates):
    """True if 4 fiscal dates are consecutive quarters."""
    ms = [int(d[:4]) * 12 + int(d[5:7]) for d in dates]
    return all(ms[i] - ms[i - 1] == 3 for i in range(1, len(ms)))


def fundamental_series(frows, price_rows=None):
    """Per-quarter ratios matching the columns of the source spreadsheet."""
    q = [{k: (_f(v) if k not in ("fiscal_date", "source") else v) for k, v in r.items()} for r in frows]
    closes = [(r["date"], _f(r.get("close"))) for r in (price_rows or []) if _f(r.get("close"))]
    out = []
    for i, r in enumerate(q):
        ta, li, eq = r.get("total_assets"), r.get("liabilities"), r.get("equity")
        cash, rev = r.get("cash"), r.get("net_revenue")
        row = {"fiscal_date": r["fiscal_date"], "total_assets": ta, "liabilities": li,
               "equity": eq, "cash": cash, "net_revenue": rev, "npat": r.get("npat"),
               "npat_parent": r.get("npat_parent"),
               "debt_to_assets": li / ta * 100 if li is not None and ta else None,
               "debt_to_equity": li / eq if li is not None and eq and eq > 0 else None,
               "cash_to_assets": cash / ta * 100 if cash is not None and ta else None,
               "revenue_growth_yoy": None, "revenue_ttm": None, "revenue_growth_ttm": None,
               "npat_ttm": None, "roa": None, "roe": None, "eps": None, "pe": None,
               "close_at_quarter": None}
        if i >= 4 and _consecutive([x["fiscal_date"] for x in q[i - 4:i + 1]]):
            prev_rev = q[i - 4].get("net_revenue")
            if rev is not None and prev_rev and prev_rev > 0:
                row["revenue_growth_yoy"] = (rev / prev_rev - 1) * 100
        if i >= 3 and _consecutive([x["fiscal_date"] for x in q[i - 3:i + 1]]):
            win = q[i - 3:i + 1]
            if all(x.get("npat") is not None for x in win):
                npat_ttm = sum(x["npat"] for x in win)
                row["npat_ttm"] = npat_ttm
                ta0 = q[i - 4].get("total_assets") if i >= 4 else None
                eq0 = q[i - 4].get("equity") if i >= 4 else None
                avg_ta = (ta + ta0) / 2 if ta and ta0 else ta
                avg_eq = (eq + eq0) / 2 if eq and eq0 else eq
                row["roa"] = npat_ttm / avg_ta * 100 if avg_ta else None
                row["roe"] = npat_ttm / avg_eq * 100 if avg_eq and avg_eq > 0 else None
            if all(x.get("net_revenue") is not None for x in win):
                row["revenue_ttm"] = sum(x["net_revenue"] for x in win)
                if i >= 7 and _consecutive([x["fiscal_date"] for x in q[i - 7:i + 1]]) \
                        and all(x.get("net_revenue") is not None for x in q[i - 7:i - 3]):
                    prev = sum(x["net_revenue"] for x in q[i - 7:i - 3])
                    if prev > 0:
                        row["revenue_growth_ttm"] = (row["revenue_ttm"] / prev - 1) * 100
            if all(x.get("npat_parent") is not None for x in win) and r.get("paid_in_capital"):
                shares = r["paid_in_capital"] / PAR_VALUE
                row["eps"] = sum(x["npat_parent"] for x in win) / shares
        if closes:
            c = [p for d, p in closes if d <= r["fiscal_date"]]
            if c:
                row["close_at_quarter"] = c[-1]
                if row["eps"] and row["eps"] > 0:
                    row["pe"] = c[-1] * 1000 / row["eps"]
        out.append(row)
    return out


def latest_fundamentals(series, last_close):
    if not series:
        return {}
    last = series[-1]
    res = dict(last)
    eps = last.get("eps")
    res["pe_now"] = last_close * 1000 / eps if last_close and eps and eps > 0 else None
    return res


def ticker_summary(t, index_rows=None):
    rows = store.load_prices(t)
    pm = price_metrics(rows, index_rows)
    fs = fundamental_series(store.load_fund(t), rows)
    lf = latest_fundamentals(fs, pm.get("close"))
    return pm, fs, lf
