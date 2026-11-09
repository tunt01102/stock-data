"""CSV/JSON storage. Every file is plain text so students can open it in Excel."""
import csv
import io
import json
import os
import threading

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.environ.get("BDS_DATA_DIR") or os.path.join(APP_DIR, "data")

PRICE_COLS = ["date", "open", "high", "low", "close", "volume", "value",
              "adj_open", "adj_high", "adj_low", "adj_close", "floor",
              "source", "xcheck"]
FUND_COLS = ["fiscal_date", "total_assets", "liabilities", "equity", "cash",
             "net_revenue", "npat", "npat_parent", "paid_in_capital", "source"]

_lock = threading.RLock()


def path(*parts):
    return os.path.join(DATA_DIR, *parts)


def ensure_dirs():
    for d in ("prices", "fundamentals", "macro"):
        os.makedirs(path(d), exist_ok=True)


def atomic_write_text(p, text):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    os.replace(tmp, p)


def read_csv(p):
    if not os.path.exists(p):
        return []
    with open(p, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def rows_to_csv(rows, cols, bom=False):
    buf = io.StringIO()
    if bom:
        buf.write("﻿")  # lets Excel detect UTF-8 (Vietnamese text)
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore", lineterminator="\n")
    w.writeheader()
    for r in rows:
        w.writerow({c: ("" if r.get(c) is None else r.get(c)) for c in cols})
    return buf.getvalue()


def write_csv(p, rows, cols):
    with _lock:
        atomic_write_text(p, rows_to_csv(rows, cols))


def merge_rows(old, new, key):
    """Union by key; rows in `new` replace rows in `old`. Result sorted by key."""
    m = {r[key]: r for r in old}
    for r in new:
        m[r[key]] = r
    return [m[k] for k in sorted(m)]


def read_json(p, default=None):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_json(p, obj):
    with _lock:
        atomic_write_text(p, json.dumps(obj, ensure_ascii=False, indent=1))


def tickers():
    return read_json(path("tickers.json"), [])


def price_path(t):
    return path("prices", t.upper() + ".csv")


def fund_path(t):
    return path("fundamentals", t.upper() + ".csv")


def load_prices(t):
    return read_csv(price_path(t))


def load_fund(t):
    return read_csv(fund_path(t))


# ---- status (last refresh, per-source errors, last dates) ----
def status():
    return read_json(path("status.json"), {}) or {}


def update_status(section, data):
    with _lock:
        st = status()
        st.setdefault(section, {}).update(data)
        write_json(path("status.json"), st)
