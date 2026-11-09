"""Figures read directly from official Vietnamese state websites.

- Cục Thống kê (NSO, nso.gov.vn): monthly press release "Chỉ số giá tiêu dùng,
  chỉ số giá vàng và chỉ số giá đô la Mỹ" -> CPI (y/y, m/m), gold price index
  and USD price index (y/y).
- Ngân hàng Nhà nước (SBV, sbv.gov.vn): policy rates in force, interbank
  overnight rate, and today's central USD/VND rate.
"""
import datetime as dt
import html as htmlmod
import re
import time
import unicodedata
import urllib.parse

from . import store
from .net import fetch, fetch_json, FetchError

SBV_RATES = "https://www.sbv.gov.vn/vi/l%C3%A3i-su%E1%BA%A5t1"
SBV_FX = "https://www.sbv.gov.vn/vi/t%E1%BB%B7-gi%C3%A1"

NSO_COLS = ["period", "cpi_yoy", "cpi_mom", "gold_idx_yoy", "usd_idx_yoy", "title", "source_url", "published"]

_MONTH_WORDS = [("mười hai", 12), ("mười một", 11), ("mười", 10), ("chín", 9), ("tám", 8), ("bảy", 7),
                ("sáu", 6), ("năm", 5), ("tư", 4), ("bốn", 4), ("ba", 3), ("hai", 2), ("một", 1), ("giêng", 1)]


def _text(raw):
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", raw, flags=re.S)
    t = htmlmod.unescape(re.sub(r"<[^>]+>", " ", t))
    t = unicodedata.normalize("NFC", t)  # some pages use decomposed Vietnamese characters
    return re.sub(r"\s+", " ", t)


def parse_title_period(title):
    """'... tháng Mười và mười tháng năm 2026' -> '2026-10'; None if not a monthly CPI release."""
    title = unicodedata.normalize("NFC", title)
    t = title.lower()
    if not t.startswith("chỉ số giá tiêu dùng"):
        return None
    y = re.search(r"năm\s+(\d{4})", t)
    m = re.search(r"tháng\s+(.+?)(?:\s+và\b|,|\s+năm\b|\s+quý\b|\s+\d)", t)
    if not y or not m:
        return None
    word = m.group(1).strip()
    month = int(word) if word.isdigit() else dict(_MONTH_WORDS).get(word)
    if not month or not 1 <= month <= 12:
        return None
    return "%s-%02d" % (y.group(1), month)


def _signed(word, num):
    v = float(num.replace(",", "."))
    return -v if word == "giảm" else v


_NUM = r"(tăng|giảm)\s*([\d]+(?:,\d+)?)\s*%"
_REF = r"(cùng kỳ(?: năm (?:trước|\d{4}))?|tháng trước|tháng\s*\d{1,2}\s*/\s*\d{4})"


def _classify(ref, period):
    ref = ref.lower()
    if ref.startswith("cùng kỳ"):
        return "yoy"
    if ref == "tháng trước":
        return "mom"
    m = re.search(r"(\d{1,2})\s*/\s*(\d{4})", ref)
    if m and period:
        y, mo = int(period[:4]), int(period[5:7])
        if int(m.group(2)) == y - 1 and int(m.group(1)) == mo:
            return "yoy"           # e.g. "so với tháng 5/2020" in the May 2021 release
    return None                    # vs. December of last year etc.


def _changes(seg, period):
    """All (kind, value, position) comparisons found in a text segment."""
    out = []
    for m in re.finditer(_NUM + r"\s*so với\s*" + _REF, seg, re.I):
        out.append((_classify(m.group(3), period), _signed(m.group(1), m.group(2)), m.start()))
    gap = r"(?:(?!tăng|giảm|so với|\bvà\b)[^.;%]){0,60}?"
    for m in re.finditer(r"so với\s*" + _REF + r"\s*,?\s*" + gap + _NUM, seg, re.I):
        out.append((_classify(m.group(1), period), _signed(m.group(2), m.group(3)), m.start()))
    return sorted(out, key=lambda x: x[2])


_SKIP = ("bình quân", "tính chung", "quý", "nhóm", "lạm phát cơ bản", "khu vực")


def _clean_numbers(text):
    # the site sometimes splits digits with spaces: "5,6 0 %" -> "5,60%"
    text = re.sub(r"(?<=\d)\s+(?=[\d%])", "", text)
    text = re.sub(r"(?<=\d)\s*,\s*(?=\d)", ",", text)
    return text.replace("ổn định so với tháng trước", "tăng 0% so với tháng trước")


def _region(text, anchors, stops, length=900):
    starts = [text.find(a) for a in anchors]
    starts = [i for i in starts if i >= 0]
    if not starts:
        return ""
    i = min(starts)
    seg = text[i:i + length]
    cut = [seg.find(x, 10) for x in stops]
    cut = [c for c in cut if c > 0]
    return seg[:min(cut)] if cut else seg


def _first(region, period, kind):
    """First comparison of `kind` in sentences that are about the month itself."""
    for sent in re.split(r"[.;]\s", region):
        low = sent.lower().replace(" ", "")  # the site sometimes splits letters: "b ình quân"
        if any(k.replace(" ", "") in low for k in _SKIP):
            continue
        for k, v, _ in _changes(sent, period):
            if k == kind:
                return v
    return None


def parse_release(text, period=None):
    """Extract y/y and m/m changes from an NSO monthly price press release."""
    text = _clean_numbers(unicodedata.normalize("NFC", text))
    cpi = _region(text, ["(CPI)", "CPI tháng", "chỉ số giá tiêu dùng tháng", "Chỉ số giá tiêu dùng tháng"],
                  ["Chỉ số giá vàng", "I. ", "Lạm phát cơ bản tháng"])
    gold = _region(text, ["Chỉ số giá vàng tháng"], ["Chỉ số giá đô la", "Chỉ số giá đôla", "Lạm phát"], 400)
    usd = _region(text, ["Chỉ số giá đô la Mỹ tháng", "Chỉ số giá đô la mỹ tháng", "Chỉ số giá đôla Mỹ tháng"],
                  ["Lạm phát", "Chỉ số giá vàng", "Chỉ số giá tiêu dùng"], 400)
    return {"cpi_yoy": _first(cpi, period, "yoy"), "cpi_mom": _first(cpi, period, "mom"),
            "gold_idx_yoy": _first(gold, period, "yoy"), "usd_idx_yoy": _first(usd, period, "yoy")}


NSO_API = "https://www.nso.gov.vn/wp-json/wp/v2/posts?"


def _nso_api_page(page, after=None):
    q = {"search": "Chỉ số giá tiêu dùng, chỉ số giá vàng", "per_page": 100, "page": page,
         "_fields": "date,link,title,content"}
    if after:
        q["after"] = after
    try:
        return fetch_json(NSO_API + urllib.parse.urlencode(q), timeout=60, retries=1)
    except FetchError as e:
        if "HTTP 400" in str(e):  # past the last page
            return []
        raise


def refresh_nso_cpi(since="2018-01", max_pages=15):
    """Monthly CPI release of the statistics office, via its WordPress JSON API."""
    p = store.path("macro", "nso_cpi.csv")
    have = {r["period"]: r for r in store.read_csv(p) if r.get("cpi_yoy")}
    # incremental: only posts published in the last ~120 days once history exists
    after = None
    if have and min(have) <= since:
        after = (dt.date.today() - dt.timedelta(days=120)).isoformat() + "T00:00:00"
    for page in range(1, max_pages + 1):
        posts = _nso_api_page(page, after)
        if not posts:
            break
        for x in posts:
            title = htmlmod.unescape(re.sub(r"<[^>]+>", "", x["title"]["rendered"])).strip()
            per = parse_title_period(title)
            if not per or per < since:
                continue
            vals = parse_release(_text(x.get("content", {}).get("rendered", "")), per)
            if vals.get("cpi_yoy") is None:
                continue
            old = have.get(per)
            if old and old.get("published", "") > x["date"]:
                continue  # keep the latest publication for a month
            have[per] = dict(period=per, title=title, source_url=x["link"], published=x["date"], **vals)
        time.sleep(0.2)
    if not have:
        raise FetchError("Không đọc được thông cáo CPI từ nso.gov.vn")
    rows = [have[k] for k in sorted(have)]
    store.write_csv(p, rows, NSO_COLS)
    return rows[-1]["period"]


# ------------------------------------------------------------------ SBV
def _num_vn(s):
    return float(s.replace(".", "").replace(",", "."))


def parse_sbv_rates(text):
    out = {}
    m = re.search(r"Lãi suất tái chiết khấu\s+([\d.,]+)\s*%\s+(\S+/QĐ-NHNN)", text)
    if m:
        out["rediscount_rate"], out["decision"] = _num_vn(m.group(1)), m.group(2)
    m = re.search(r"Lãi suất tái cấp vốn\s+([\d.,]+)\s*%", text)
    if m:
        out["refinancing_rate"] = _num_vn(m.group(1))
    m = re.search(r"liên ngân hàng\s+Ngày áp dụng:\s*(\d{2}/\d{2}/\d{4}).*?Qua đêm\s+([\d,]+)", text)
    if m:
        out["interbank_date"] = dt.datetime.strptime(m.group(1), "%d/%m/%Y").date().isoformat()
        out["interbank_overnight"] = _num_vn(m.group(2))
    return out


def parse_sbv_fx(text):
    m = re.search(r"áp dụng cho ngày\s*(\d{2}/\d{2}/\d{4})\s*như sau:.*?1 Đô la Mỹ\s*=\s*([\d.]+)\s*VND.*?Số văn bản\s+(\S+)", text)
    if not m:
        return {}
    return {"date": dt.datetime.strptime(m.group(1), "%d/%m/%Y").date().isoformat(),
            "central_rate": _num_vn(m.group(2)), "notice": m.group(3)}


def refresh_sbv():
    rates = parse_sbv_rates(_text(fetch(SBV_RATES, timeout=40).decode("utf-8", "replace")))
    fx = parse_sbv_fx(_text(fetch(SBV_FX, timeout=40).decode("utf-8", "replace")))
    if not rates.get("refinancing_rate") and not fx.get("central_rate"):
        raise FetchError("Không đọc được số liệu từ sbv.gov.vn (trang có thể đã đổi định dạng)")
    now = dt.datetime.now().isoformat(timespec="seconds")
    store.write_json(store.path("macro", "sbv_live.json"),
                     dict(rates=rates, fx=fx, fetched_at=now, rates_url=SBV_RATES, fx_url=SBV_FX))
    if fx.get("central_rate"):  # keep a growing daily history of the central rate
        p = store.path("macro", "sbv_central.csv")
        old = store.read_csv(p)
        row = {"date": fx["date"], "central_rate": fx["central_rate"], "notice": fx.get("notice"),
               "source_url": SBV_FX}
        store.write_csv(p, store.merge_rows(old, [row], "date"), ["date", "central_rate", "notice", "source_url"])
    return fx.get("date") or rates.get("interbank_date")
