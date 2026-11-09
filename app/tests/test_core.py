"""Unit tests (no network). Run:  python -m unittest discover -s tests -v"""
import datetime as dt
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import store, prices, analysis, ai, fundamentals  # noqa: E402
from core.net import FetchError  # noqa: E402
import server  # noqa: E402


def bars(dates, closes, vol=1000, adj=None, floor="HOSE"):
    adj = adj or closes
    return [dict(date=d, open=c, high=c, low=c, close=c, volume=vol, value=None,
                 adj_open=a, adj_high=a, adj_low=a, adj_close=a, floor=floor, source="VNDirect")
            for d, c, a in zip(dates, closes, adj)]


def weekdays(start, n):
    d, out = dt.date.fromisoformat(start), []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += dt.timedelta(days=1)
    return out


class TempData(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self._old = store.DATA_DIR
        store.DATA_DIR = self.dir
        store.ensure_dirs()
        store.write_json(store.path("tickers.json"), [
            {"stt": 1, "ticker": "AAA", "name": "A", "segment": "Nhà ở", "listed": "2010-01-01", "note": None},
            {"stt": 2, "ticker": "BBB", "name": "B", "segment": "Khu công nghiệp", "listed": "2010-01-01", "note": None}])
        server.CACHE.clear()

    def tearDown(self):
        store.DATA_DIR = self._old
        shutil.rmtree(self.dir, ignore_errors=True)


class TestStore(unittest.TestCase):
    def test_merge_replaces_and_sorts(self):
        old = [{"date": "2020-01-02", "v": 1}, {"date": "2020-01-03", "v": 2}]
        new = [{"date": "2020-01-03", "v": 9}, {"date": "2020-01-01", "v": 0}]
        m = store.merge_rows(old, new, "date")
        self.assertEqual([r["date"] for r in m], ["2020-01-01", "2020-01-02", "2020-01-03"])
        self.assertEqual(m[2]["v"], 9)

    def test_csv_bom_for_excel(self):
        txt = store.rows_to_csv([{"a": "Việt"}], ["a"], bom=True)
        self.assertTrue(txt.startswith("﻿a\n"))


class TestCrossCheck(unittest.TestCase):
    def test_volume_mismatch_flagged(self):
        rows = bars(["2020-01-02", "2020-01-03"], [10, 11])
        s = prices.crosscheck(rows, {"SSI": {"2020-01-02": (10, 1000), "2020-01-03": (11, 5000)}})
        self.assertEqual(rows[0]["xcheck"], "OK")
        self.assertTrue(rows[1]["xcheck"].startswith("LECH"))
        self.assertEqual(s["mismatch"], 1)

    def test_odd_lot_volume_within_tolerance(self):
        rows = bars(["2020-01-02"], [10], vol=14000)
        prices.crosscheck(rows, {"VPS": {"2020-01-02": (10, 14177)}})
        self.assertEqual(rows[0]["xcheck"], "OK")

    def test_ex_dividend_day_is_method_difference_not_error(self):
        # raw price drops 10% on ex-date, our adjusted series is flat; the other
        # source did not adjust -> its return equals our raw return -> OK
        rows = bars(["2020-01-02", "2020-01-03"], [10, 9], adj=[9, 9])
        prices.crosscheck(rows, {"SSI": {"2020-01-02": (10, 1000), "2020-01-03": (9, 1000)}})
        self.assertEqual(rows[1]["xcheck"], "OK")

    def test_return_mismatch_flagged(self):
        rows = bars(["2020-01-02", "2020-01-03"], [10, 10])
        prices.crosscheck(rows, {"SSI": {"2020-01-02": (10, 1000), "2020-01-03": (11, 1000)}})
        self.assertIn("%ngày", rows[1]["xcheck"])

    def test_raw_close_vs_cafef(self):
        rows = bars(["2020-01-02"], [10])
        prices.crosscheck(rows, {}, raw_ref={"2020-01-02": {"close": 10.5}})
        self.assertIn("CafeF", rows[0]["xcheck"])

    def test_index_compares_level(self):
        rows = bars(["2020-01-02", "2020-01-03"], [1000, 1010], vol=5)
        prices.crosscheck(rows, {"SSI": {"2020-01-02": (1000, 999999), "2020-01-03": (1020, 1)}}, index=True)
        self.assertEqual(rows[0]["xcheck"], "OK")
        self.assertTrue(rows[1]["xcheck"].startswith("LECH"))

    def test_no_other_source_is_na(self):
        rows = bars(["2020-01-02"], [10])
        prices.crosscheck(rows, {})
        self.assertEqual(rows[0]["xcheck"], "NA")


class TestPriceMetrics(unittest.TestCase):
    def test_basic_metrics(self):
        ds = weekdays("2019-12-02", 300)
        closes = [10 + i * 0.01 for i in range(300)]
        rows = bars(ds, closes)
        m = analysis.price_metrics(rows, bars(ds, closes))
        self.assertAlmostEqual(m["chg_1d"], (closes[-1] / closes[-2] - 1) * 100)
        self.assertAlmostEqual(m["chg_1w"], (closes[-1] / closes[-6] - 1) * 100)
        self.assertAlmostEqual(m["max_drawdown"], 0.0)
        self.assertAlmostEqual(m["beta_1y"], 1.0, places=6)  # same series as index
        self.assertAlmostEqual(m["ma20"], sum(closes[-20:]) / 20)
        prev_year = [c for d, c in zip(ds, closes) if d < ds[-1][:4] + "-01-01"][-1]
        self.assertAlmostEqual(m["chg_ytd"], (closes[-1] / prev_year - 1) * 100)

    def test_drawdown(self):
        ds = weekdays("2020-01-01", 5)
        m = analysis.price_metrics(bars(ds, [10, 20, 10, 15, 25]))
        self.assertAlmostEqual(m["max_drawdown"], -50.0)
        self.assertEqual((m["mdd_from"], m["mdd_to"]), (ds[1], ds[2]))

    def test_empty(self):
        self.assertEqual(analysis.price_metrics([]), {})


class TestFundamentals(unittest.TestCase):
    def q(self, d, ta=1000, li=600, eq=400, cash=100, rev=100, npat=10, cap=100000):
        return {"fiscal_date": d, "total_assets": ta, "liabilities": li, "equity": eq, "cash": cash,
                "net_revenue": rev, "npat": npat, "npat_parent": npat, "paid_in_capital": cap, "source": "t"}

    def test_ratios_and_ttm(self):
        fr = [self.q(d, rev=r) for d, r in [("2020-03-31", 100), ("2020-06-30", 100), ("2020-09-30", 100),
                                            ("2020-12-31", 100), ("2021-03-31", 150)]]
        pr = bars(["2021-03-31"], [20.0])
        s = analysis.fundamental_series(fr, pr)
        last = s[-1]
        self.assertAlmostEqual(last["debt_to_assets"], 60.0)
        self.assertAlmostEqual(last["debt_to_equity"], 1.5)
        self.assertAlmostEqual(last["cash_to_assets"], 10.0)
        self.assertAlmostEqual(last["revenue_growth_yoy"], 50.0)
        self.assertAlmostEqual(last["roa"], 40 / 1000 * 100)
        self.assertAlmostEqual(last["roe"], 40 / 400 * 100)
        self.assertAlmostEqual(last["eps"], 40 / (100000 / 10000))  # 4 VND/share
        self.assertAlmostEqual(last["pe"], 20.0 * 1000 / 4)
        self.assertIsNone(s[2]["roa"])  # fewer than 4 quarters

    def test_gap_in_quarters_skips_ttm(self):
        fr = [self.q(d) for d in ("2020-03-31", "2020-06-30", "2020-12-31", "2021-03-31")]
        self.assertIsNone(analysis.fundamental_series(fr)[-1]["roa"])

    def test_negative_eps_has_no_pe(self):
        fr = [self.q(d, npat=-5) for d in ("2020-03-31", "2020-06-30", "2020-09-30", "2020-12-31")]
        s = analysis.fundamental_series(fr, bars(["2020-12-31"], [10]))
        self.assertLess(s[-1]["eps"], 0)
        self.assertIsNone(s[-1]["pe"])
        self.assertIsNone(analysis.latest_fundamentals(s, 10)["pe_now"])


class TestRefresh(TempData):
    def test_incremental_and_fallback(self):
        ds = weekdays("2018-01-01", 10)
        with mock.patch.object(prices, "fetch_vndirect", return_value=bars(ds[:8], [10] * 8)), \
             mock.patch.object(prices, "fetch_ssi", return_value={}), \
             mock.patch.object(prices, "fetch_vps", return_value={}), \
             mock.patch.object(prices, "fetch_cafef", return_value={}):
            r = prices.refresh_ticker("AAA")
        self.assertEqual((r["rows"], r["added"], r["last_date"]), (8, 8, ds[7]))
        # second run: VNDirect down -> CafeF fallback adds the missing days
        cf = {d: dict(date=d, open=10, high=10, low=10, close=10, volume=1000, adj_close=10) for d in ds[5:]}
        with mock.patch.object(prices, "fetch_vndirect", side_effect=FetchError("down")), \
             mock.patch.object(prices, "fetch_ssi", return_value={}), \
             mock.patch.object(prices, "fetch_vps", return_value={}), \
             mock.patch.object(prices, "fetch_cafef", return_value=cf):
            r = prices.refresh_ticker("AAA")
        self.assertEqual(r["last_date"], ds[9])
        self.assertEqual(r["added"], 2)
        self.assertIn("VNDirect", r["errors"])

    def test_total_failure_keeps_old_data(self):
        ds = weekdays("2018-01-01", 3)
        store.write_csv(store.price_path("AAA"), bars(ds, [10, 11, 12]), store.PRICE_COLS)
        with mock.patch.object(prices, "fetch_vndirect", side_effect=FetchError("offline")), \
             mock.patch.object(prices, "fetch_cafef", side_effect=FetchError("offline")):
            r = prices.refresh_ticker("AAA")
        self.assertFalse(r["ok"])
        self.assertEqual(r["last_date"], ds[-1])
        self.assertEqual(len(store.load_prices("AAA")), 3)

    def test_dividend_rescale_triggers_full_refetch(self):
        ds = weekdays("2018-01-01", 20)
        store.write_csv(store.price_path("AAA"), bars(ds[:15], [10] * 15), store.PRICE_COLS)
        rescaled = bars(ds, [10] * 20, adj=[9] * 20)  # history adjusted by 10%
        calls = []

        def fake(t, since, index=False):
            calls.append(since)
            return [r for r in rescaled if r["date"] >= since]
        with mock.patch.object(prices, "fetch_vndirect", side_effect=fake), \
             mock.patch.object(prices, "fetch_ssi", return_value={}), \
             mock.patch.object(prices, "fetch_vps", return_value={}), \
             mock.patch.object(prices, "fetch_cafef", return_value={}):
            prices.refresh_ticker("AAA")
        self.assertEqual(calls[-1], prices.START)
        self.assertTrue(all(float(r["adj_close"]) == 9 for r in store.load_prices("AAA")))


class TestFreshness(TempData):
    def test_expected_session(self):
        tz = prices.VN_TZ
        self.assertEqual(server.expected_session(dt.datetime(2026, 11, 9, 10, 0, tzinfo=tz)), "2026-11-06")  # Mon morning
        self.assertEqual(server.expected_session(dt.datetime(2026, 11, 9, 16, 0, tzinfo=tz)), "2026-11-09")
        self.assertEqual(server.expected_session(dt.datetime(2026, 11, 8, 12, 0, tzinfo=tz)), "2026-11-06")  # Sunday

    def test_stale_when_behind_and_check_failed(self):
        store.write_csv(store.price_path("VNINDEX"), bars(["2020-01-02"], [900]), store.PRICE_COLS)
        store.update_status("market", {"ok": False, "checked_at": "2020-01-03T10:00:00+07:00", "errors": {"VNDirect": "x"}})
        f = server.freshness()
        self.assertTrue(f["stale"])
        self.assertEqual(f["data_last"], "2020-01-02")

    def test_holiday_not_stale_after_successful_check(self):
        exp = server.expected_session()
        prev = (dt.date.fromisoformat(exp) - dt.timedelta(days=3)).isoformat()
        store.write_csv(store.price_path("VNINDEX"), bars([prev], [900]), store.PRICE_COLS)
        store.update_status("market", {"ok": True, "checked_at": exp + "T16:00:00+07:00", "errors": {}})
        self.assertTrue(server.freshness()["stale"])   # too early to call it a holiday
        store.update_status("market", {"ok": True, "checked_at": exp + "T18:00:00+07:00", "errors": {}})
        self.assertFalse(server.freshness()["stale"])


class TestDownload(TempData):
    def test_single_csv_and_zip(self):
        ds = weekdays("2020-01-01", 3)
        for t in ("AAA", "BBB"):
            store.write_csv(store.price_path(t), bars(ds, [1, 2, 3]), store.PRICE_COLS)
        name, data, ctype = server.build_download(["AAA"], "prices")
        self.assertTrue(name.startswith("gia_AAA") and ctype.startswith("text/csv"))
        self.assertTrue(data.decode("utf-8").startswith("﻿date,"))
        name, data, ctype = server.build_download(["AAA", "BBB"], "both")
        z = zipfile.ZipFile(io.BytesIO(data))
        self.assertIn("_tong_hop_gia.csv", z.namelist())
        self.assertIn("chiso_taichinh_BBB.csv", z.namelist())
        combined = z.read("_tong_hop_gia.csv").decode("utf-8-sig").splitlines()
        self.assertEqual(len(combined), 1 + 6)
        self.assertIn("tat_ca", name)  # both tickers in this fixture = all


class TestGoldUnits(unittest.TestCase):
    def test_both_page_layouts(self):
        from core import macro
        self.assertAlmostEqual(macro._to_million_per_luong("36.880"), 36.88)      # thousand VND/lượng
        self.assertAlmostEqual(macro._to_million_per_luong("14.120.000"), 141.2)  # VND/chỉ


class TestOfficialParsers(unittest.TestCase):
    """Real sentences from NSO / SBV pages of different years."""
    def test_nso_2018(self):
        from core.official import parse_release
        t = ("Chỉ số giá tiêu dùng (CPI) tháng 1/2018 tăng 0,51% so với tháng trước. So với cùng kỳ năm trước, "
             "CPI tháng 1/2018 tăng 2,65%. Chỉ số giá vàng tháng 1/2018 tăng 1,69% so với tháng trước và tăng 6,70% "
             "so với cùng kỳ năm 2017. Chỉ số giá đô la Mỹ tháng 1/2018 giảm 0,04% so với tháng trước và giảm 0,02% "
             "so với cùng kỳ năm 2017. Lạm phát cơ bản tháng 1/2018 tăng 0,18%")
        r = parse_release(t, "2018-01")
        self.assertEqual((r["cpi_yoy"], r["cpi_mom"], r["gold_idx_yoy"], r["usd_idx_yoy"]), (2.65, 0.51, 6.70, -0.02))

    def test_nso_2021_vs_named_month(self):
        from core.official import parse_release
        t = ("làm chỉ số giá tiêu dùng (CPI) tháng 5/2021 tăng 0,16% so với tháng trước, tăng 1,43% so với tháng "
             "12/2020 và tăng 2,9% so với tháng 5/2020. Bình quân 5 tháng đầu năm 2021, CPI tăng 1,29%")
        r = parse_release(t, "2021-05")
        self.assertEqual((r["cpi_yoy"], r["cpi_mom"]), (2.9, 0.16))

    def test_nso_2024(self):
        from core.official import parse_release
        t = ("– Chỉ số giá tiêu dùng (CPI) tháng 10/2024 tăng 0,33% so với tháng trước. So với tháng 12/2023, CPI "
             "tháng Mười tăng 2,52% và so với cùng kỳ năm trước tăng 2,89%. Bình quân mười tháng năm 2024, CPI tăng "
             "3,78% so với cùng kỳ năm trước; – Chỉ số giá vàng tháng 10/2024 tăng 5,96% so với tháng trước; tăng "
             "29,97% so với tháng 12/2023; tăng 38,88% so với cùng kỳ năm trước; bình quân mười tháng")
        r = parse_release(t, "2024-10")
        self.assertEqual((r["cpi_yoy"], r["cpi_mom"], r["gold_idx_yoy"]), (2.89, 0.33, 38.88))

    def test_nso_ignores_averages_and_split_digits(self):
        from core.official import parse_release
        t = ("Chỉ số giá tiêu dùng (CPI) tháng Năm tăng 0,29% so với tháng trước do giá điện tăng. CPI tháng Năm tăng "
             "3,61% so với tháng 12/2025 và tăng 5,6 0 % so với cùng kỳ năm trước. Tính chung năm tháng đầu năm 2026, "
             "CPI tăng 4,31% so với cùng kỳ năm trước; lạm phát cơ bản tăng 4,04%.")
        self.assertEqual(parse_release(t, "2026-05")["cpi_yoy"], 5.6)
        t2 = ("Chỉ số giá tiêu dùng (CPI) tháng 6/2020 tăng 0,66% so với tháng trước. Tính chung quý II/2020, CPI giảm "
              "1,87% so với quý trước và tăng 2,83% so với cùng kỳ năm 2019. CPI bình quân 6 tháng đầu năm 2020 tăng "
              "4,19% so với bình quân cùng kỳ năm 2019; CPI tháng 6/2020 giảm 0,59% so với tháng 12/2019 và tăng 3,17% "
              "so với cùng kỳ năm trước. Lạm phát cơ bản tháng 6/2020 tăng 0,07%")
        self.assertEqual(parse_release(t2, "2020-06")["cpi_yoy"], 3.17)
        t3 = ("Tính chung tháng 8/2024, chỉ số giá tiêu dùng (CPI) ổn định so với tháng trước. So với tháng 12/2023, CPI "
              "tháng Tám tăng 1,89% và so với cùng kỳ năm trước tăng 3,45%. Bình quân tám tháng năm 2024")
        r3 = parse_release(t3, "2024-08")
        self.assertEqual((r3["cpi_yoy"], r3["cpi_mom"]), (3.45, 0.0))

    def test_nso_decomposed_unicode(self):
        import unicodedata
        from core.official import parse_release
        t = unicodedata.normalize("NFD", "Chỉ số giá tiêu dùng tháng 8/2020 tăng 0,07% so với tháng trước. Chỉ số giá "
                                  "tiêu dùng bình quân 8 tháng năm 2020 tăng 3,96% so với cùng kỳ năm trước . CPI tháng "
                                  "8/2020 giảm 0,12% so với tháng 12/2019 và tăng 3,18% so với cùng kỳ năm trước;")
        self.assertEqual(parse_release(t, "2020-08")["cpi_yoy"], 3.18)

    def test_title_months(self):
        from core.official import parse_title_period as f
        self.assertEqual(f("Chỉ số giá tiêu dùng, chỉ số giá vàng và chỉ số giá đô la Mỹ tháng Mười Hai, quý IV và năm 2025"), "2025-12")
        self.assertEqual(f("Chỉ số giá tiêu dùng, chỉ số giá vàng và chỉ số giá đô la Mỹ tháng Mười và mười tháng năm 2026"), "2026-10")
        self.assertIsNone(f("Báo cáo tình hình kinh tế – xã hội tháng 10 năm 2026"))

    def test_gold_lowercase_no_space(self):
        from core.official import parse_release
        t = ("Chỉ số giá tiêu dùng (CPI) tháng 5/2022 tăng 0,38% so với tháng trước và tăng 2,86% so với cùng kỳ năm "
             "trước. Trong nước, chỉ số giá vàng tháng 5/2022giảm 0,52% so với tháng trước; tăng 2,75% so với cùng kỳ "
             "năm 2021. Chỉ số giá đô la Mỹ tháng 5/2022 tăng 0,35% so với tháng trước; tăng 0,1% so với cùng kỳ")
        r = parse_release(t, "2022-05")
        self.assertEqual((r["cpi_yoy"], r["gold_idx_yoy"], r["usd_idx_yoy"]), (2.86, 2.75, 0.1))

    def test_derive_yoy_forward_and_backward(self):
        from core.official import derive_yoy
        rows = [{"period": "2018-%02d" % m, "cpi_mom": "1.0", "cpi_yoy": ""} for m in range(1, 13)]
        rows += [{"period": "2019-01", "cpi_yoy": "5.0", "cpi_mom": "2.0"},
                 {"period": "2019-02", "cpi_yoy": "", "cpi_mom": "1.0"},      # stated m/m only
                 {"period": "2019-04", "cpi_yoy": "6.0", "cpi_mom": "0.5"}]   # 2019-03 has no release
        by = {r["period"]: r for r in derive_yoy(rows)}
        self.assertAlmostEqual(by["2019-02"]["cpi_yoy"], round((1.05 * 1.01 / 1.01 - 1) * 100, 2))
        self.assertAlmostEqual(by["2019-03"]["cpi_yoy"], round((1.06 * 1.01 / 1.005 - 1) * 100, 2))
        self.assertIn("NSO", by["2019-03"]["yoy_method"])

    def test_mom_before_comma_average_clause(self):
        from core.official import parse_release
        t = ("Chỉ số giá tiêu dùng (CPI) tháng 5/2019 tăng 0,49% so với tháng trước, CPI bình quân 5 tháng đầu năm "
             "2019 tăng 2,74% so với cùng kỳ năm 2018, đây là mức tăng bình quân thấp nhất.")
        r = parse_release(t, "2019-05")
        self.assertEqual((r["cpi_mom"], r["cpi_yoy"]), (0.49, None))
        r2 = parse_release("Chỉ số giá tiêu dùng tháng 7/2019 tăng 0,18% so với tháng trước, bình quân 7 tháng năm "
                           "2019 tăng 2,61% so với cùng kỳ năm 2018. CPI tháng 7/2019 tăng 1,59% so với tháng 12/2018 và "
                           "tăng 2,44% so với cùng kỳ năm trước.", "2019-07")
        self.assertEqual((r2["cpi_mom"], r2["cpi_yoy"]), (0.18, 2.44))

    def test_report_titles(self):
        from core.official import parse_report_period as f
        self.assertEqual(f("Báo cáo tình hình kinh tế – xã hội tháng 10 và 10 tháng năm 2020"), "2020-10")
        self.assertEqual(f("Báo cáo tình hình kinh tế – xã hội quý III và 9 tháng năm 2020"), "2020-09")
        self.assertEqual(f("Thông cáo báo chí tình hình kinh tế – xã hội quý IV và năm 2019"), "2019-12")
        self.assertEqual(f("Báo cáo tình hình kinh tế – xã hội 6 tháng đầu năm 2019"), "2019-06")
        self.assertIsNone(f("Một số nét chính tình hình kinh tế – xã hội tháng 10"))

    def test_sbv_fx_item_uses_effective_date(self):
        from core.official import parse_sbv_fx_item
        it = {"title": "17/11/2026", "contentFields": [
            {"name": "NgayBatDau", "contentFieldValue": {"data": "2025-11-16T17:00:00Z"}},
            {"name": "TyGiaSo", "contentFieldValue": {"data": "25254"}},
            {"name": "SoVanBan", "contentFieldValue": {"data": "288/TB-NHNN"}}]}
        r = parse_sbv_fx_item(it, today="2026-11-10")
        self.assertEqual((r["date"], r["central_rate"]), ("2025-11-17", 25254.0))
        it["contentFields"][0]["contentFieldValue"]["data"] = "2026-12-01T17:00:00Z"
        self.assertIsNone(parse_sbv_fx_item(it, today="2026-11-10"))  # future date rejected

    def test_sbv(self):
        from core.official import parse_sbv_rates, parse_sbv_fx
        r = parse_sbv_rates("Lãi suất tái chiết khấu 3,000% 1123/QĐ-NHNN ngày 16/06/2023 19/03/2023 Lãi suất tái cấp vốn "
                            "4,500% 1123/QĐ-NHNN Lãi suất thị trường liên ngân hàng Ngày áp dụng: 06/11/2026 Thời hạn "
                            "Lãi suất BQ Qua đêm 6,07 824.769,0")
        self.assertEqual((r["refinancing_rate"], r["rediscount_rate"], r["decision"], r["interbank_overnight"]),
                         (4.5, 3.0, "1123/QĐ-NHNN", 6.07))
        f = parse_sbv_fx("áp dụng cho ngày 09/11/2026 như sau: Tỷ giá trung tâm Tỷ giá 1 Đô la Mỹ = 25.610 VND Bằng chữ "
                         "Hai mươi Số văn bản 464/TB-NHNN Ngày ban hành")
        self.assertEqual((f["date"], f["central_rate"], f["notice"]), ("2026-11-09", 25610.0, "464/TB-NHNN"))


class TestSettings(TempData):
    def test_keys_masked_and_masked_value_ignored(self):
        ai.save_settings({"keys": {"claude": "sk-ant-secret-1234"}, "provider": "claude"})
        pub = ai.public_settings()
        self.assertEqual(pub["keys"]["claude"], "••••1234")
        self.assertNotIn("secret", json.dumps(pub))
        ai.save_settings({"keys": {"claude": "••••1234"}})  # browser echoes mask back
        self.assertEqual(ai.load_settings()["keys"]["claude"], "sk-ant-secret-1234")
        ai.save_settings({"keys": {"claude": ""}})
        self.assertNotIn("claude", ai.load_settings()["keys"])

    def test_ask_without_key_raises(self):
        with self.assertRaises(FetchError):
            ai.ask("hi", "{}", "openai")


if __name__ == "__main__":
    unittest.main()
