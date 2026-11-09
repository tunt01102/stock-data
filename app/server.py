"""Local web server for the BĐS HOSE analysis app.

Run:  python server.py     (or double-click the Start file for your OS)
Then the browser opens http://127.0.0.1:8686 (or the next free port)
Only the Python standard library is used.
"""
import datetime as dt
import io
import json
import mimetypes
import os
import socket
import sys
import threading
import time
import traceback
import urllib.parse
import webbrowser
import zipfile
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core import store, prices, fundamentals, macro, analysis, ai  # noqa: E402
from core.net import FetchError  # noqa: E402

STATIC = os.path.join(store.APP_DIR, "static")
INDEX = "VNINDEX"
VERSION = "1.0.0"


# ====================================================================== jobs
class Job:
    def __init__(self):
        self.lock = threading.Lock()
        self.state = {"running": False}

    def snapshot(self):
        with self.lock:
            return json.loads(json.dumps(self.state))

    def start(self, what, tickers=None):
        with self.lock:
            if self.state.get("running"):
                return False
            self.state = {"running": True, "what": what, "done": 0, "total": 0,
                          "current": "", "errors": {}, "log": [],
                          "started": now_iso(), "finished": None}
        threading.Thread(target=self._run, args=(what, tickers), daemon=True).start()
        return True

    def _set(self, **kw):
        with self.lock:
            self.state.update(kw)

    def _log(self, msg):
        with self.lock:
            self.state["log"] = (self.state["log"] + [msg])[-200:]

    def _err(self, key, msg):
        with self.lock:
            self.state["errors"][key] = msg

    def _run(self, what, tickers):
        try:
            all_t = [t["ticker"] for t in store.tickers()]
            tickers = tickers or all_t
            steps = []
            if what in ("prices", "all"):
                steps += [("index", INDEX)] + [("price", t) for t in tickers]
            if what in ("fundamentals", "all"):
                steps += [("fund", t) for t in tickers]
            if what in ("macro", "all"):
                steps += [("macro", None)]
            self._set(total=len(steps))
            fails = 0
            for i, (kind, t) in enumerate(steps):
                if fails >= 3 and kind in ("price", "fund", "index"):
                    # three tickers in a row got nothing: most likely offline
                    self._err("Mạng", "Dừng tải giá/BCTC: 3 mã liên tiếp lỗi kết nối. Kiểm tra internet rồi bấm Làm mới lại.")
                    continue
                self._set(done=i, current="%s %s" % (kind, t or ""))
                try:
                    if kind == "index":
                        r = prices.refresh_ticker(INDEX, index=True)
                        fails = 1 if (not r["ok"] and r["errors"]) else 0
                        store.update_status("market", {
                            "last_date": r["last_date"], "ok": r["ok"] or not r["errors"],
                            "checked_at": now_iso(), "errors": r["errors"]})
                        self._report(INDEX, r)
                    elif kind == "price":
                        r = prices.refresh_ticker(t)
                        store.update_status("prices", {t: slim(r)})
                        self._report(t, r)
                        fails = fails + 1 if (not r["ok"] and r["errors"]) else 0
                        time.sleep(0.2)
                    elif kind == "fund":
                        r = fundamentals.refresh_fund(t)
                        if r["ok"]:
                            store.update_status("fundamentals", {t: r})
                        fails = fails + 1 if not r["ok"] else 0
                        if r["errors"]:
                            self._err("BCTC " + t, "; ".join(r["errors"].values()))
                        time.sleep(0.1)
                    elif kind == "macro":
                        res = macro.refresh_all()
                        for k, v in res.items():
                            if not v["ok"]:
                                self._err("Vĩ mô " + k, v["error"])
                        self._log("Vĩ mô: " + ", ".join("%s→%s" % (k, v["last_period"]) for k, v in res.items()))
                except Exception as e:  # never kill the whole job for one ticker
                    self._err("%s %s" % (kind, t), "%s: %s" % (type(e).__name__, e))
            store.update_status("last_refresh", {what: {"at": now_iso(), "errors": self.snapshot()["errors"]}})
            CACHE.clear()
        except Exception as e:
            self._err("job", traceback.format_exc(limit=3))
        finally:
            self._set(running=False, finished=now_iso(), done=self.state.get("total", 0), current="")

    def _report(self, t, r):
        if r["errors"]:
            self._err(t, "; ".join("%s: %s" % kv for kv in r["errors"].items()))
        self._log("%s: +%d phiên, đến %s%s" % (t, r["added"], r["last_date"],
                                              "" if r["ok"] or not r["errors"] else " (LỖI)"))


def slim(r):
    return {k: r.get(k) for k in ("last_date", "first_date", "rows", "added", "errors", "ok",
                                  "xcheck", "refreshed_at")}


JOB = Job()
CACHE = {}


def now_iso():
    return dt.datetime.now(prices.VN_TZ).isoformat(timespec="seconds")


# ====================================================================== freshness
def expected_session(now=None):
    """Latest weekday session that should have closed (HOSE closes 15:00 VN time)."""
    now = now or dt.datetime.now(prices.VN_TZ)
    d = now.date()
    if now.weekday() < 5 and (now.hour, now.minute) < (15, 30):
        d -= dt.timedelta(days=1)
    while d.weekday() >= 5:
        d -= dt.timedelta(days=1)
    return d.isoformat()


def freshness():
    st = store.status()
    idx = store.load_prices(INDEX)
    data_last = idx[-1]["date"] if idx else None
    expected = expected_session()
    market = st.get("market", {})
    checked = market.get("checked_at")
    # If a successful check ran after the expected session closed and found no
    # newer data, that day was a holiday: the data is as fresh as it can be.
    # Require the check to be after 17:00 so a bar not yet published at 15:30-17:00
    # is never mistaken for a holiday (conservative: show red until confirmed).
    holiday_ok = bool(market.get("ok") and checked and data_last and
                      checked[:16] >= expected + "T17:00" and not market.get("errors"))
    stale = (data_last is None) or (data_last < expected and not holiday_ok)
    return {"data_last": data_last, "expected": expected, "stale": stale,
            "last_check": checked, "last_check_errors": market.get("errors") or {},
            "last_refresh": st.get("last_refresh", {}), "today": prices.today_vn()}


# ====================================================================== payloads
def tickers_overview():
    if "overview" in CACHE:
        return CACHE["overview"]
    idx = store.load_prices(INDEX)
    st = store.status().get("prices", {})
    out = []
    for t in store.tickers():
        pm, fs, lf = analysis.ticker_summary(t["ticker"], idx)
        out.append(dict(t, metrics=pm, fund={k: lf.get(k) for k in (
            "fiscal_date", "total_assets", "debt_to_assets", "debt_to_equity", "cash_to_assets",
            "revenue_growth_yoy", "revenue_growth_ttm", "roa", "roe", "eps", "pe_now")},
            status=st.get(t["ticker"], {})))
    CACHE["overview"] = out
    return out


def stock_payload(t):
    t = t.upper()
    meta = next((x for x in store.tickers() if x["ticker"] == t), {"ticker": t})
    rows = store.load_prices(t)
    idx = store.load_prices(INDEX)
    pm = analysis.price_metrics(rows, idx)
    fs = analysis.fundamental_series(store.load_fund(t), rows)
    xc = {"ok": 0, "mismatch": 0, "na": 0, "examples": []}
    for r in rows:
        x = r.get("xcheck") or "NA"
        if x == "OK":
            xc["ok"] += 1
        elif x.startswith("LECH"):
            xc["mismatch"] += 1
            xc["examples"].append({"date": r["date"], "note": x})
        else:
            xc["na"] += 1
    xc["examples"] = xc["examples"][-30:]
    cols = ["date", "open", "high", "low", "close", "volume", "adj_close", "floor", "xcheck"]
    return {
        "meta": meta, "metrics": pm, "fund": fs,
        "fund_latest": analysis.latest_fundamentals(fs, pm.get("close")),
        "prices": {c: [r.get(c) for r in rows] for c in cols},
        "index": {"date": [r["date"] for r in idx], "close": [r["close"] for r in idx]},
        "xcheck": xc, "status": store.status().get("prices", {}).get(t, {}),
        "fund_status": store.status().get("fundamentals", {}).get(t, {}),
        "sources": {k: v.format(t=t) for k, v in prices.SOURCES.items()},
        "fund_source": fundamentals.SOURCE_URL.format(t=t),
    }


def series_payload(tickers, field="adj_close"):
    out = {}
    for t in tickers:
        rows = store.load_prices(t)
        out[t] = [[r["date"], r.get(field)] for r in rows]
    return out


def build_download(tickers, kind):
    """Return (filename, bytes, content-type)."""
    stamp = prices.today_vn()
    files = {}
    for t in tickers:
        if kind in ("prices", "both"):
            rows = store.load_prices(t)
            files["gia_%s.csv" % t] = store.rows_to_csv(rows, store.PRICE_COLS, bom=True)
        if kind in ("fundamentals", "both"):
            fs = analysis.fundamental_series(store.load_fund(t), store.load_prices(t))
            cols = list(fs[0].keys()) if fs else ["fiscal_date"]
            files["chiso_taichinh_%s.csv" % t] = store.rows_to_csv(fs, cols, bom=True)
    if kind == "macro":
        mdir = store.path("macro")
        for f in sorted(os.listdir(mdir)):
            if f.endswith(".csv"):
                files["vimo_" + f] = "﻿" + open(os.path.join(mdir, f), encoding="utf-8").read()
            elif f.startswith("curated_") and f.endswith(".json"):
                d = store.read_json(os.path.join(mdir, f), {}) or {}
                rows = d.get("rows", [])
                if rows:
                    files["vimo_" + f.replace(".json", ".csv")] = store.rows_to_csv(rows, list(rows[0].keys()), bom=True)
    if len(files) == 1:
        name, text = next(iter(files.items()))
        return name.replace(".csv", "_%s.csv" % stamp), text.encode("utf-8"), "text/csv; charset=utf-8"
    if kind in ("prices", "both") and len(tickers) > 1:
        # one combined long-format file is handy for Excel pivot tables
        allrows = []
        for t in tickers:
            for r in store.load_prices(t):
                allrows.append(dict(r, ticker=t))
        files["_tong_hop_gia.csv"] = store.rows_to_csv(allrows, ["ticker"] + store.PRICE_COLS, bom=True)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("DOC_TOI.txt", README_ZIP.format(date=stamp))
        for n, text in files.items():
            z.writestr(n, text)
    label = "vimo" if kind == "macro" else ("tat_ca" if len(tickers) >= len(store.tickers()) else "%d_ma" % len(tickers))
    return "du_lieu_bds_%s_%s.zip" % (label, stamp), buf.getvalue(), "application/zip"


README_ZIP = """Dữ liệu tải từ ứng dụng Phân tích BĐS HOSE ngày {date}.
- Giá tính bằng nghìn đồng (VD 29.5 = 29.500 đ).
- open/high/low/close: giá giao dịch thực tế (chưa điều chỉnh).
- adj_*: giá đã điều chỉnh cổ tức, chia tách (dùng để tính lợi suất).
- volume: khối lượng khớp lệnh (cổ phiếu).
- xcheck: kết quả đối chiếu với SSI/VPS/CafeF (OK = khớp; LECH = có chênh lệch, xem chi tiết; NA = chưa đối chiếu).
- File mở được bằng Excel (mã hoá UTF-8).
Nguồn chính: VNDirect (api-finfo.vndirect.com.vn). Đối chiếu: SSI iBoard, VPS, CafeF.
"""


def ai_context(body):
    if body.get("ticker"):
        p = stock_payload(body["ticker"])
        fund = p["fund"][-8:]
        return json.dumps({"ma": p["meta"], "chi_so_gia": p["metrics"], "bctc_8_quy_gan_nhat": fund,
                           "doi_chieu": {k: p["xcheck"][k] for k in ("ok", "mismatch", "na")},
                           "don_vi": "giá: nghìn đồng; tài chính: đồng; tỷ lệ: %"},
                          ensure_ascii=False, default=str)
    m = macro.load_all()
    small = {k: (v[-24:] if isinstance(v, list) else v) for k, v in m.items()
             if k in ("cpi", "fx", "gold", "gdp_annual", "vnindex")}
    small["sbv"] = (m.get("sbv") or {}).get("rows")
    small["gdp_quarterly"] = ((m.get("gdp_quarterly") or {}).get("rows") or [])[-12:]
    return json.dumps(small, ensure_ascii=False, default=str)


# ====================================================================== HTTP
class Handler(BaseHTTPRequestHandler):
    server_version = "BDSApp/" + VERSION

    def log_message(self, fmt, *args):  # keep the console quiet
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8", headers=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False, default=str).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        return json.loads(self.rfile.read(n).decode("utf-8") or "{}")

    def do_GET(self):
        try:
            self._route("GET")
        except Exception as e:
            self._send(500, {"error": "%s: %s" % (type(e).__name__, e)})

    def do_POST(self):
        # same-origin guard: only the app's own page may trigger actions
        origin = self.headers.get("Origin")
        host = self.headers.get("Host", "")
        if origin and urllib.parse.urlparse(origin).netloc != host:
            return self._send(403, {"error": "forbidden"})
        try:
            self._route("POST")
        except Exception as e:
            self._send(500, {"error": "%s: %s" % (type(e).__name__, e)})

    def _route(self, method):
        u = urllib.parse.urlparse(self.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        p = u.path
        if method == "GET":
            if p == "/api/overview":
                return self._send(200, {"tickers": tickers_overview(), "fresh": freshness()})
            if p.startswith("/api/stock/"):
                return self._send(200, stock_payload(p.rsplit("/", 1)[1]))
            if p == "/api/series":
                ts = [t for t in q.get("tickers", "").upper().split(",") if t]
                return self._send(200, series_payload(ts, q.get("field", "adj_close")))
            if p == "/api/macro":
                return self._send(200, dict(macro.load_all(), fresh=freshness()))
            if p == "/api/status":
                return self._send(200, {"fresh": freshness(), "job": JOB.snapshot(),
                                        "version": VERSION})
            if p == "/api/job":
                return self._send(200, JOB.snapshot())
            if p == "/api/settings":
                return self._send(200, ai.public_settings())
            if p == "/api/download":
                kind = q.get("kind", "prices")
                valid = {t["ticker"] for t in store.tickers()} | {INDEX}
                ts = [t for t in q.get("tickers", "").upper().split(",") if t in valid]
                if q.get("tickers") == "ALL":
                    ts = [t["ticker"] for t in store.tickers()]
                if not ts and kind != "macro":
                    return self._send(400, {"error": "Chưa chọn mã nào"})
                name, data, ctype = build_download(ts, kind)
                return self._send(200, data, ctype, {
                    "Content-Disposition": "attachment; filename=\"%s\"" % name})
            return self._static(p)
        body = self._body()
        if p == "/api/refresh":
            what = body.get("what", "all")
            ts = body.get("tickers") or None
            ok = JOB.start(what, ts)
            return self._send(200 if ok else 409, {"started": ok, "job": JOB.snapshot()})
        if p == "/api/settings":
            return self._send(200, ai.save_settings(body))
        if p == "/api/ai":
            try:
                text, model = ai.ask(body.get("question", ""), ai_context(body),
                                     body.get("provider"), body.get("lang", "vi"))
                return self._send(200, {"answer": text, "model": model})
            except FetchError as e:
                return self._send(502, {"error": str(e)})
            except (KeyError, IndexError, TypeError) as e:
                return self._send(502, {"error": "Phản hồi AI không đúng định dạng: %s" % e})
        self._send(404, {"error": "not found"})

    def _static(self, p):
        if p in ("", "/"):
            p = "/index.html"
        full = os.path.normpath(os.path.join(STATIC, p.lstrip("/")))
        if not full.startswith(STATIC) or not os.path.isfile(full):
            return self._send(404, "Not found", "text/plain")
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype.endswith("javascript"):
            ctype += "; charset=utf-8"
        with open(full, "rb") as f:
            self._send(200, f.read(), ctype)


def find_port(start=8686):
    for port in range(start, start + 30):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if os.name != "nt":  # same rule as the HTTP server: allow a port in TIME_WAIT
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise SystemExit("Không tìm được cổng trống")


def main():
    for stream in (sys.stdout, sys.stderr):  # never crash on a non-UTF-8 console
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass
    mimetypes.add_type("application/javascript", ".js")
    mimetypes.add_type("text/css", ".css")
    store.ensure_dirs()
    port = find_port(int(os.environ.get("BDS_PORT") or 8686))
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = "http://127.0.0.1:%d/" % port
    print("=" * 60, flush=True)
    print(" Ứng dụng Phân tích BĐS HOSE đang chạy tại:", url)
    print(" Giữ cửa sổ này mở trong lúc dùng. Đóng cửa sổ để tắt ứng dụng.")
    print("=" * 60, flush=True)
    if os.environ.get("BDS_AUTO_REFRESH", "1") == "1":
        JOB.start("all")  # fetch missing days in the background (needs internet)
    if os.environ.get("BDS_NO_BROWSER") != "1":
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
