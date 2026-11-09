"""Macro indicators for Vietnam from 2018, each with source links and cross-checks.

Automatic: IMF SDMX (CPI, USD/VND, gold), World Bank (annual CPI, GDP, FX),
VNDirect/SSI/DNSE (VN-Index), Vietcombank (today's USD rate).
Curated (hand-collected, every row cites an official page): SBV policy rates,
quarterly GDP, real-estate legal documents.
"""
import csv
import datetime as dt
import io
import re
import time

from . import store
from .net import fetch, fetch_json, FetchError

START_YEAR = 2018
IMF_BASE = "https://api.imf.org/external/sdmx/3.0/data/dataflow/"
IMF_CSV = {"Accept": "application/vnd.sdmx.data+csv;version=2.0.0"}
TROY_OZ_PER_LUONG = 37.5 / 31.1034768  # 1 lượng = 37.5 g

LINKS = {
    "imf_cpi": "https://data.imf.org/en/datasets/IMF.STA:CPI",
    "imf_er": "https://data.imf.org/en/datasets/IMF.STA:ER",
    "imf_pcps": "https://data.imf.org/en/datasets/IMF.RES:PCPS",
    "wb_cpi": "https://data.worldbank.org/indicator/FP.CPI.TOTL.ZG?locations=VN",
    "wb_gdp": "https://data.worldbank.org/indicator/NY.GDP.MKTP.KD.ZG?locations=VN",
    "wb_fx": "https://data.worldbank.org/indicator/PA.NUS.FCRF?locations=VN",
    "vcb": "https://www.vietcombank.com.vn/vi-VN/KHCN/Cong-cu-Tien-ich/Ty-gia",
    "nso": "https://www.nso.gov.vn/",
    "sbv_rates": "https://www.sbv.gov.vn/vi/l%C3%A3i-su%E1%BA%A5t1",
    "sbv_fx": "https://www.sbv.gov.vn/vi/t%E1%BB%B7-gi%C3%A1",
    "sbv_fx_hist": "https://www.sbv.gov.vn/bieu-do-ty-gia-trung-tam",
    "sbv": "https://www.sbv.gov.vn/",
    "sjc": "https://sjc.com.vn/",
    "webgia": "https://webgia.com/gia-vang/sjc/",
}

MACRO_COLS = ["period", "value", "unit", "source", "source_url",
              "xcheck_value", "xcheck_source", "xcheck"]


def _imf(flow, key, since="2017-01"):
    url = "%s%s/+/%s?c%%5BTIME_PERIOD%%5D=ge:%s" % (IMF_BASE, flow, key, since)
    raw = fetch(url, headers=IMF_CSV, timeout=60).decode("utf-8-sig")
    out = []
    for r in csv.DictReader(io.StringIO(raw)):
        tp, v = r.get("TIME_PERIOD", ""), r.get("OBS_VALUE", "")
        if not v:
            continue
        m = re.match(r"(\d{4})-M(\d{2})$", tp)
        if m:
            out.append((r, "%s-%s" % m.groups(), float(v)))
    return out


def _wb(indicator):
    url = ("https://api.worldbank.org/v2/country/VNM/indicator/%s?format=json&date=%d:%d"
           % (indicator, START_YEAR, dt.date.today().year))
    js = fetch_json(url, timeout=40)
    rows = js[1] if isinstance(js, list) and len(js) > 1 and js[1] else []
    return {r["date"]: r["value"] for r in rows if r.get("value") is not None}


def _save(name, rows):
    store.write_csv(store.path("macro", name + ".csv"), rows, MACRO_COLS)


def _mk(period, value, unit, source, url, **kw):
    r = dict(period=period, value=round(value, 4) if value is not None else None,
             unit=unit, source=source, source_url=url, xcheck="NA")
    r.update(kw)
    return r


# ------------------------------------------------------------------ CPI
def refresh_cpi():
    data = _imf("IMF.STA/CPI", "VNM.CPI._T.*.M")
    yoy = {p: v for r, p, v in data if r["TYPE_OF_TRANSFORMATION"] == "YOY_PCH_PA_PT"}
    idx = {p: v for r, p, v in data if r["TYPE_OF_TRANSFORMATION"] == "IX"}
    rows = [_mk(p, yoy[p], "% so cùng kỳ", "IMF (số liệu gốc: Tổng cục Thống kê/NSO)",
                LINKS["imf_cpi"]) for p in sorted(yoy) if p >= "%d-01" % START_YEAR]
    # internal check: YoY recomputed from the index
    for r in rows:
        y, m = r["period"].split("-")
        a, b = idx.get(r["period"]), idx.get("%d-%s" % (int(y) - 1, m))
        if a and b:
            calc = (a / b - 1) * 100
            r.update(xcheck_value=round(calc, 2), xcheck_source="Tính lại từ chỉ số CPI (IMF)",
                     xcheck="OK" if abs(calc - r["value"]) <= 0.1 else "LECH")
    # Official NSO releases are the primary figure; IMF is the cross-check and
    # only fills months whose release does not state the y/y change.
    nso = {r["period"]: r for r in store.read_csv(store.path("macro", "nso_cpi.csv")) if r.get("cpi_yoy")}
    imf_by = {r["period"]: r["value"] for r in rows}
    merged = []
    for per in sorted(set(imf_by) | set(nso)):
        if per < "%d-01" % START_YEAR:
            continue
        n = nso.get(per)
        if n:
            v = float(n["cpi_yoy"])
            r = _mk(per, v, "% so cùng kỳ", "Cục Thống kê (NSO) – thông cáo tháng", n["source_url"])
            if per in imf_by:
                r.update(xcheck_value=round(imf_by[per], 2), xcheck_source="IMF (CPI tháng)",
                         xcheck="OK" if abs(imf_by[per] - v) <= 0.1 else "LECH")
            else:
                r.update(xcheck_source="IMF chưa có kỳ này")
        else:
            r = next(x for x in rows if x["period"] == per)
            r["source"] = "IMF (thông cáo NSO tháng này không nêu số so cùng kỳ)"
        merged.append(r)
    rows = merged
    annual = {}
    try:
        wb = _wb("FP.CPI.TOTL.ZG")
        for year, v in sorted(wb.items()):
            months = [idx.get("%s-%02d" % (year, m)) for m in range(1, 13)]
            prev = [idx.get("%d-%02d" % (int(year) - 1, m)) for m in range(1, 13)]
            mine = None
            if all(months) and all(prev):
                mine = (sum(months) / sum(prev) - 1) * 100
            annual[year] = dict(year=year, worldbank=round(v, 2),
                                imf_avg=round(mine, 2) if mine is not None else None,
                                status=("OK" if mine is not None and abs(mine - v) <= 0.2 else
                                        "LECH" if mine is not None else "NA"))
    except FetchError as e:
        annual["error"] = str(e)
    _save("cpi", rows)
    store.write_json(store.path("macro", "cpi_annual_check.json"),
                     {"source_url": LINKS["wb_cpi"], "rows": annual})
    return rows[-1]["period"] if rows else None


# ------------------------------------------------------------------ USD/VND
def refresh_fx():
    imf = {}
    try:
        data = _imf("IMF.STA/ER", "VNM.USD_XDC.PA_RT.M")
        imf = {p: 1.0 / v for r, p, v in data if v and p >= "%d-01" % START_YEAR}
    except FetchError:
        pass
    # Primary: monthly average of the State Bank's daily central rate (sbv.gov.vn)
    by_month = {}
    for r in store.read_csv(store.path("macro", "sbv_central.csv")):
        by_month.setdefault(r["date"][:7], []).append(float(r["central_rate"]))
    rows = []
    for per in sorted(set(by_month) | set(imf)):
        if per < "%d-01" % START_YEAR:
            continue
        if per in by_month:
            v = sum(by_month[per]) / len(by_month[per])
            r = _mk(per, v, "VND/USD (bình quân tháng tỷ giá trung tâm)", "Ngân hàng Nhà nước (sbv.gov.vn)",
                    LINKS["sbv_fx_hist"], days=len(by_month[per]))
            if per in imf:
                r.update(xcheck_value=round(imf[per], 1), xcheck_source="IMF (tỷ giá chính thức bình quân tháng)",
                         xcheck="OK" if abs(imf[per] / v - 1) <= 0.01 else "LECH")
        else:
            r = _mk(per, imf[per], "VND/USD (bình quân tháng)", "IMF (số liệu gốc: NHNN)", LINKS["imf_er"])
        rows.append(r)
    if not rows:
        raise FetchError("Không có số liệu tỷ giá từ NHNN hoặc IMF")
    try:
        wb = _wb("PA.NUS.FCRF")
        for year, v in wb.items():
            ms = [r["value"] for r in rows if r["period"].startswith(year)]
            if len(ms) == 12:
                avg = sum(ms) / 12
                for r in rows:
                    if r["period"] == year + "-12":
                        r.update(xcheck_value=round(v, 1),
                                 xcheck_source="World Bank (bình quân năm %s)" % year,
                                 xcheck="OK" if abs(avg / v - 1) <= 0.01 else "LECH")
    except FetchError:
        pass
    today = None
    try:
        today = vcb_usd()
    except FetchError as e:
        today = {"error": str(e)}
    _save("fx", rows)
    store.write_json(store.path("macro", "fx_today.json"), today)
    return rows[-1]["period"] if rows else None


def vcb_usd():
    raw = fetch("https://portal.vietcombank.com.vn/Usercontrols/TVPortal.TyGia/pXML.aspx",
                timeout=20).decode("utf-8", "replace")
    m = re.search(r'CurrencyCode="USD"[^>]*Buy="([\d,.]+)"[^>]*Transfer="([\d,.]+)"[^>]*Sell="([\d,.]+)"', raw)
    d = re.search(r"<DateTime>([^<]+)</DateTime>", raw)
    if not m:
        raise FetchError("Không đọc được tỷ giá USD từ Vietcombank")
    num = lambda s: float(s.replace(",", ""))
    return {"buy": num(m.group(1)), "transfer": num(m.group(2)), "sell": num(m.group(3)),
            "time": d.group(1) if d else None, "source": "Vietcombank", "source_url": LINKS["vcb"]}


# ------------------------------------------------------------------ Gold
def refresh_gold():
    data = _imf("IMF.RES/PCPS", "G001.PGOLD.USD.M")
    fx = {r["period"]: float(r["value"]) for r in store.read_csv(store.path("macro", "fx.csv"))}
    rows = []
    for r, p, v in sorted(data, key=lambda x: x[1]):
        if p < "%d-01" % START_YEAR:
            continue
        row = _mk(p, v, "USD/ounce", "IMF Primary Commodity Prices", LINKS["imf_pcps"])
        rate = fx.get(p)
        if rate is None:  # FX for this month not published yet: use the latest month
            older = [k for k in fx if k <= p]
            if older:
                rate = fx[max(older)]
                row["xcheck_source"] = "quy đổi bằng tỷ giá tháng %s" % max(older)
        if rate:
            row["vnd_per_luong"] = round(v * rate * TROY_OZ_PER_LUONG / 1e6, 2)
        rows.append(row)
    store.write_csv(store.path("macro", "gold.csv"), rows, MACRO_COLS + ["vnd_per_luong"])
    return rows[-1]["period"] if rows else None


# ------------------------------------------------------------------ GDP
def refresh_gdp():
    wb = _wb("NY.GDP.MKTP.KD.ZG")
    rows = [_mk(y, v, "% tăng trưởng thực", "World Bank (số liệu gốc: NSO)", LINKS["wb_gdp"])
            for y, v in sorted(wb.items())]
    cur = store.read_json(store.path("macro", "curated_gdp_quarterly.json"), {}) or {}
    official = {r["period"]: r for r in cur.get("rows", []) if re.fullmatch(r"\d{4}", str(r.get("period")))}
    for r in rows:
        o = official.get(r["period"])
        if o and o.get("gdp_yoy_pct") is not None:
            v = float(o["gdp_yoy_pct"])
            r.update(xcheck_value=v, xcheck_source="Thông cáo NSO (thủ công)",
                     xcheck="OK" if abs(v - r["value"]) <= 0.2 else "LECH")
    _save("gdp_annual", rows)
    return rows[-1]["period"] if rows else None


# ------------------------------------------------------------------ SJC gold (domestic)
SJC_PAGE = "https://webgia.com/gia-vang/sjc/{d}.html"


def _sjc_day(day):
    """(buy, sell) in million VND/lượng from the last SJC update of `day`, or None."""
    url = SJC_PAGE.format(d=day.strftime("%d-%m-%Y"))
    raw = fetch(url, timeout=25, retries=1).decode("utf-8", "replace")
    i = raw.find("<table")
    if i < 0:
        return None, url
    seg = raw[i:raw.find("</table>", i)]
    pairs = re.findall(r"<td[^>]*>\s*([\d.]{5,})[^<]*</td>\s*<td[^>]*>\s*([\d.]{5,})", re.sub(r"<(?!/?td)[^>]+>", "", seg))
    if not pairs:
        return None, url
    # Two page layouts: history pages list each update of the day (last row =
    # closing price, thousand VND/lượng); the current-day page lists products,
    # first row = SJC 1L bar, priced in VND per chỉ (1 lượng = 10 chỉ).
    buy, sell = pairs[0] if "Loại vàng" in seg else pairs[-1]
    return (_to_million_per_luong(buy), _to_million_per_luong(sell)), url


def _to_million_per_luong(txt):
    n = float(txt.replace(".", "").replace(",", ""))
    if n >= 1e6:          # VND per chỉ
        return n * 10 / 1e6
    return n / 1000.0     # thousand VND per lượng


def refresh_sjc(max_new=200):
    p = store.path("macro", "gold_sjc.csv")
    old = {r["period"]: r for r in store.read_csv(p)}
    today = dt.date.today()
    months = []
    y, m = START_YEAR, 1
    while (y, m) <= (today.year, today.month):
        months.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    cur = "%d-%02d" % (today.year, today.month)
    world = {r["period"]: r.get("vnd_per_luong") for r in store.read_csv(store.path("macro", "gold.csv"))}
    fetched, ok, last_err = 0, 0, None
    for (y, m) in months:
        per = "%d-%02d" % (y, m)
        if per in old and per != cur and old[per].get("value"):
            continue
        if fetched >= max_new:
            break
        nxt = dt.date(y + (m == 12), m % 12 + 1, 1)
        day = min(nxt - dt.timedelta(days=1), today)
        for _ in range(7):  # walk back over weekends/holidays
            fetched += 1
            try:
                res, url = _sjc_day(day)
            except FetchError as e:
                res, url, last_err = None, None, e
                if "kết nối" in str(e):
                    break  # offline: do not walk back further
            if res:
                ok += 1
                buy, sell = res
                w = world.get(per)
                row = _mk(per, sell, "triệu đ/lượng (giá bán)", "SJC qua webgia.com", url,
                          date=day.isoformat(), buy=buy)
                if w:
                    prem = (sell / float(w) - 1) * 100
                    row.update(xcheck_value=round(float(w), 2),
                               xcheck_source="Vàng thế giới quy đổi (IMF)", premium_pct=round(prem, 1),
                               xcheck="OK" if -5 <= prem <= 30 else "LECH")
                old[per] = row
                break
            day -= dt.timedelta(days=1)
            time.sleep(0.15)
    if fetched and not ok and last_err:
        raise last_err
    rows = [old[k] for k in sorted(old)]
    store.write_csv(p, rows, MACRO_COLS + ["date", "buy", "premium_pct"])
    return rows[-1]["period"] if rows else None


# ------------------------------------------------------------------ all
def _nso():
    from .official import refresh_nso_cpi
    return refresh_nso_cpi()


def _sbv():
    from .official import refresh_sbv, refresh_sbv_fx_history
    last = refresh_sbv()
    refresh_sbv_fx_history()
    return last


TASKS = [("nso", _nso), ("sbv", _sbv), ("cpi", refresh_cpi), ("fx", refresh_fx), ("gold", refresh_gold), ("sjc", refresh_sjc),
         ("gdp", refresh_gdp)]


def refresh_all(progress=None):
    res = {}
    for i, (name, fn) in enumerate(TASKS):
        if progress:
            progress(i, len(TASKS), name)
        try:
            res[name] = {"ok": True, "last_period": fn(), "error": None}
        except Exception as e:  # keep going; the UI shows the failure in red
            msg = str(e) if isinstance(e, FetchError) else "%s: %s" % (type(e).__name__, e)
            res[name] = {"ok": False, "last_period": None, "error": msg}
        res[name]["refreshed_at"] = dt.datetime.now().isoformat(timespec="seconds")
    store.update_status("macro", res)
    return res


def load_all():
    """Everything the Macro tab needs in one payload."""
    rd = lambda n: store.read_csv(store.path("macro", n + ".csv"))
    rj = lambda n: store.read_json(store.path("macro", n + ".json"), None)
    idx = store.load_prices("VNINDEX")
    monthly = {}
    for r in idx:
        monthly[r["date"][:7]] = r  # last session of each month
    vnindex = [{"period": k, "value": float(v["close"]), "date": v["date"], "xcheck": v.get("xcheck")}
               for k, v in sorted(monthly.items())]
    return {
        "cpi": rd("cpi"), "cpi_annual": rj("cpi_annual_check"),
        "fx": rd("fx"), "fx_today": rj("fx_today"),
        "gold": rd("gold"), "gold_sjc": rd("gold_sjc"), "gdp_annual": rd("gdp_annual"),
        "gdp_quarterly": rj("curated_gdp_quarterly"),
        "sbv": rj("curated_sbv_rates"), "legal": rj("curated_legal"),
        "sbv_live": rj("sbv_live"), "nso_cpi": rd("nso_cpi"),
        "vnindex": vnindex, "vnindex_last": idx[-1] if idx else None,
        "status": store.status().get("macro", {}), "links": LINKS,
    }
