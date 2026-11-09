"""Daily prices: fetch, cross-check and incremental refresh.

Primary source  : VNDirect finfo (raw + adjusted prices, matched volume).
Cross-check     : SSI iBoard (adjusted, volume), VPS, DNSE/Entrade, CafeF (raw close).
Prices are stored in thousand VND, as all Vietnamese sources publish them.
"""
import datetime as dt
import time

from . import store
from .net import fetch_json, FetchError

START = "2018-01-01"
VN_TZ = dt.timezone(dt.timedelta(hours=7))

SOURCES = {
    "VNDirect": "https://dchart.vndirect.com.vn/?symbol={t}",
    "SSI": "https://iboard.ssi.com.vn/",
    "VPS": "https://banggia.vps.com.vn/",
    "DNSE": "https://banggia.dnse.com.vn/",
    "CafeF": "https://cafef.vn/du-lieu/lich-su-giao-dich-{t}-1.chn",
}


def _ts(date_str):
    d = dt.datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc)
    return int(d.timestamp())


def _ts_to_date(t):
    return (dt.datetime.fromtimestamp(int(t), dt.timezone.utc) + dt.timedelta(hours=7)).strftime("%Y-%m-%d")


def today_vn():
    return dt.datetime.now(VN_TZ).strftime("%Y-%m-%d")


def _f(x):
    try:
        return None if x is None or x == "" else float(x)
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------------ sources
def fetch_vndirect(ticker, since=START, index=False):
    ep = "vnmarket_prices" if index else "stock_prices"
    url = ("https://api-finfo.vndirect.com.vn/v4/%s?sort=date&q=code:%s~date:gte:%s"
           "&size=9999&page=1" % (ep, ticker, since))
    data = fetch_json(url).get("data", [])
    out = []
    for x in data:
        if index:
            out.append(dict(date=x["date"], open=x.get("open"), high=x.get("high"),
                            low=x.get("low"), close=x.get("close"),
                            volume=x.get("nmVolume"), value=x.get("nmValue"),
                            adj_open=x.get("open"), adj_high=x.get("high"),
                            adj_low=x.get("low"), adj_close=x.get("close"),
                            floor=x.get("floor"), source="VNDirect"))
        else:
            out.append(dict(date=x["date"], open=x.get("open"), high=x.get("high"),
                            low=x.get("low"), close=x.get("close"),
                            volume=x.get("nmVolume"), value=x.get("nmValue"),
                            adj_open=x.get("adOpen"), adj_high=x.get("adHigh"),
                            adj_low=x.get("adLow"), adj_close=x.get("adClose"),
                            floor=x.get("floor"), source="VNDirect"))
    out.sort(key=lambda r: r["date"])
    return out


def _tv_rows(d):
    """TradingView-style arrays {t,o,h,l,c,v} -> {date: (close, volume)}."""
    res = {}
    for i, t in enumerate(d.get("t") or []):
        res[_ts_to_date(t)] = (d["c"][i], d["v"][i])
    return res


def fetch_ssi(ticker, since=START):
    url = ("https://iboard-api.ssi.com.vn/statistics/charts/history?resolution=1D"
           "&symbol=%s&from=%d&to=%d" % (ticker, _ts(since), int(time.time()) + 86400))
    return _tv_rows(fetch_json(url).get("data") or {})


def fetch_vps(ticker, since=START):
    url = ("https://histdatafeed.vps.com.vn/tradingview/history?symbol=%s&resolution=D"
           "&from=%d&to=%d" % (ticker, _ts(since), int(time.time()) + 86400))
    return _tv_rows(fetch_json(url))


def fetch_dnse(ticker, since=START, index=False):
    kind = "index" if index else "stock"
    url = ("https://services.entrade.com.vn/chart-api/v2/ohlcs/%s?from=%d&to=%d"
           "&symbol=%s&resolution=1D" % (kind, _ts(since), int(time.time()) + 86400, ticker))
    return _tv_rows(fetch_json(url))


def fetch_cafef(ticker, pages=1):
    """Raw (unadjusted) prices for the most recent sessions (30 per page)."""
    out = {}
    for p in range(1, pages + 1):
        url = ("https://cafef.vn/du-lieu/Ajax/PageNew/DataHistory/PriceHistory.ashx?"
               "Symbol=%s&StartDate=&EndDate=&PageIndex=%d&PageSize=30" % (ticker, p))
        rows = (fetch_json(url).get("Data") or {}).get("Data") or []
        if not rows:
            break
        for x in rows:
            d = dt.datetime.strptime(x["Ngay"], "%d/%m/%Y").strftime("%Y-%m-%d")
            out[d] = dict(date=d, open=x.get("GiaMoCua"), high=x.get("GiaCaoNhat"),
                          low=x.get("GiaThapNhat"), close=x.get("GiaDongCua"),
                          volume=x.get("KhoiLuongKhopLenh"), adj_close=x.get("GiaDieuChinh"))
    return out


# ------------------------------------------------------------------ cross-check
VOL_TOL = 0.02       # 2 % (some sources include odd-lot trades)
RET_TOL = 0.5        # 0.5 percentage-point difference in daily return
RAW_TOL = 0.051      # thousand VND (one tick is 0.05 for most HOSE prices)


def crosscheck(rows, others, raw_ref=None, index=False):
    """Annotate each row's `xcheck` field.

    rows    : primary rows (sorted by date), each with volume/close/adj_close
    others  : {source_name: {date: (adj_close, volume)}}
    raw_ref : {date: row} from CafeF to compare the unadjusted close
    index   : for indices compare the level itself (no adjustment, volume
              definitions differ between sources)

    Stocks: matched volume must agree; the daily % change must agree with
    either our adjusted or our raw series (sources adjust for cash dividends
    differently, which is a method difference, not a data error).
    """
    summary = {"checked": 0, "ok": 0, "mismatch": 0, "examples": []}
    prev = None
    prev_other = {}
    for r in rows:
        notes, checked = [], False
        vol, adj, raw = _f(r.get("volume")), _f(r.get("adj_close")), _f(r.get("close"))
        for name, series in others.items():
            o = series.get(r["date"])
            if not o:
                prev_other.pop(name, None)
                continue
            checked = True
            oc, ov = _f(o[0]), _f(o[1])
            if index:
                if raw and oc and abs(raw / oc - 1) > 0.001:
                    notes.append("%s=%.2f" % (name, oc))
                continue
            if vol and ov is not None and abs(vol - ov) > max(1.0, VOL_TOL * vol):
                notes.append("%s KL=%d" % (name, ov))
            po = prev_other.get(name)
            if prev and po and oc:
                pa, pr = _f(prev.get("adj_close")), _f(prev.get("close"))
                r_o = (oc / po - 1) * 100
                ok_adj = adj and pa and abs((adj / pa - 1) * 100 - r_o) <= RET_TOL
                ok_raw = raw and pr and abs((raw / pr - 1) * 100 - r_o) <= RET_TOL
                if not (ok_adj or ok_raw):
                    notes.append("%s %%ngày=%.2f" % (name, r_o))
            prev_other[name] = oc
        if raw_ref and r["date"] in raw_ref:
            checked = True
            c2 = _f(raw_ref[r["date"]].get("close"))
            if raw is not None and c2 is not None and abs(raw - c2) > RAW_TOL:
                notes.append("CafeF giá=%.2f" % c2)
        if checked:
            summary["checked"] += 1
            if notes:
                summary["mismatch"] += 1
                r["xcheck"] = "LECH: " + "; ".join(notes)
                if len(summary["examples"]) < 5:
                    summary["examples"].append("%s %s" % (r["date"], r["xcheck"]))
            else:
                summary["ok"] += 1
                r["xcheck"] = "OK"
        elif not r.get("xcheck"):
            r["xcheck"] = "NA"
        prev = r
    return summary


# ------------------------------------------------------------------ refresh
def _overlap_ratio_changed(old_rows, new_rows):
    """True if adjusted prices were rescaled (new dividend/split) since last save."""
    old = {r["date"]: _f(r.get("adj_close")) for r in old_rows}
    for r in new_rows:
        a, b = old.get(r["date"]), _f(r.get("adj_close"))
        if a and b:
            return abs(a / b - 1) > 0.001
    return False


def refresh_ticker(ticker, index=False, full=False, crosscheck_sources=True):
    """Fetch missing days for one ticker; returns a status dict."""
    ticker = ticker.upper()
    p = store.price_path(ticker)
    old = store.read_csv(p)
    last = old[-1]["date"] if old else None
    if full or not last:
        since = START
    else:
        since = (dt.date.fromisoformat(last) - dt.timedelta(days=7)).isoformat()
    errors = {}
    new = []
    try:
        new = fetch_vndirect(ticker, since, index=index)
    except FetchError as e:
        errors["VNDirect"] = str(e)
    if new and old and since != START and _overlap_ratio_changed(old, new):
        # corporate action happened: adjusted history must be rebuilt
        try:
            new = fetch_vndirect(ticker, START, index=index)
            old = []
            since = START
        except FetchError as e:
            errors["VNDirect(full)"] = str(e)
    if not new and not index:
        # fallback: CafeF raw + adjusted for recent sessions
        try:
            pages = 1 if last else 10
            cf = fetch_cafef(ticker, pages=pages)
            new = [dict(v, value=None, adj_open=None, adj_high=None, adj_low=None,
                        floor="", source="CafeF") for k, v in sorted(cf.items()) if k >= since]
        except FetchError as e:
            errors["CafeF"] = str(e)

    xsum = None
    if new and crosscheck_sources:
        others = {}
        fetchers = ([("DNSE", lambda: fetch_dnse(ticker, since, index=True)),
                     ("SSI", lambda: fetch_ssi(ticker, since))] if index else
                    [("SSI", lambda: fetch_ssi(ticker, since)),
                     ("VPS", lambda: fetch_vps(ticker, since))])
        for name, fn in fetchers:
            try:
                others[name] = fn()
            except FetchError as e:
                errors[name] = str(e)
        raw_ref = None
        if not index and new[0]["source"] != "CafeF":
            try:
                raw_ref = fetch_cafef(ticker, pages=1)
            except FetchError as e:
                errors["CafeF"] = str(e)
        xsum = crosscheck(new, others, raw_ref, index=index)

    rows = store.merge_rows(old, new, "date") if new else old
    if new:
        store.write_csv(p, rows, store.PRICE_COLS)
    return {
        "ticker": ticker,
        "last_date": rows[-1]["date"] if rows else None,
        "first_date": rows[0]["date"] if rows else None,
        "rows": len(rows),
        "added": len([r for r in new if not last or r["date"] > last]),
        "errors": errors,
        "ok": bool(new),
        "xcheck": xsum,
        "refreshed_at": dt.datetime.now(VN_TZ).isoformat(timespec="seconds"),
    }
