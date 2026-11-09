"""Quarterly financial statements from VNDirect finfo (consolidated, VAS)."""
import datetime as dt

from . import store
from .net import fetch_json, FetchError

# VNDirect item codes (TT200/2014/TT-BTC layout, see /v4/financial_models)
ITEMS = {
    12700: "total_assets",      # TỔNG CỘNG TÀI SẢN
    13000: "liabilities",       # Nợ phải trả
    14000: "equity",            # Vốn chủ sở hữu
    11100: "cash",              # Tiền và các khoản tương đương tiền
    21001: "net_revenue",       # Doanh thu thuần
    23003: "npat",              # Lợi nhuận sau thuế TNDN
    23000: "npat_parent",       # LNST của cổ đông công ty mẹ
    14110: "paid_in_capital",   # Vốn góp của chủ sở hữu
}
SOURCE_URL = "https://dstock.vndirect.com.vn/tong-quan/{t}/bao-cao-tai-chinh"


def fetch_statements(ticker, since="2016-01-01"):
    codes = ",".join(str(c) for c in ITEMS)
    url = ("https://api-finfo.vndirect.com.vn/v4/financial_statements?q=code:%s"
           "~reportType:QUARTER~modelType:1,2~itemCode:%s~fiscalDate:gte:%s"
           "&sort=fiscalDate&size=5000" % (ticker, codes, since))
    data = fetch_json(url).get("data", [])
    by_date = {}
    for x in data:
        key = ITEMS.get(int(x["itemCode"]))
        if not key:
            continue
        r = by_date.setdefault(x["fiscalDate"], {"fiscal_date": x["fiscalDate"], "source": "VNDirect"})
        r[key] = x.get("numericValue")
    return [by_date[k] for k in sorted(by_date)]


def refresh_fund(ticker):
    ticker = ticker.upper()
    try:
        rows = fetch_statements(ticker)
    except FetchError as e:
        old = store.load_fund(ticker)
        return {"ticker": ticker, "ok": False, "errors": {"VNDirect": str(e)},
                "last_quarter": old[-1]["fiscal_date"] if old else None}
    if rows:
        merged = store.merge_rows(store.load_fund(ticker), rows, "fiscal_date")
        store.write_csv(store.fund_path(ticker), merged, store.FUND_COLS)
    return {"ticker": ticker, "ok": bool(rows), "errors": {} if rows else {"VNDirect": "không có số liệu"},
            "last_quarter": rows[-1]["fiscal_date"] if rows else None,
            "refreshed_at": dt.datetime.now().isoformat(timespec="seconds")}
