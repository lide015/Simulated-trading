from __future__ import annotations

import datetime as dt

import pytest

from taiwan_stock_ai.data import finmind_client, twse_client
from taiwan_stock_ai.data.http import HttpError, RateLimiter, get_json
from taiwan_stock_ai.data.util import pick, roc_date_to_western, roc_yyymm_to_western, to_float, to_int


# ---- util.py ------------------------------------------------------------


def test_pick_returns_first_present_key():
    assert pick({"a": 1, "b": 2}, "x", "a", "b") == 1
    assert pick({"a": None, "b": 2}, "a", "b") == 2  # None 被跳過
    assert pick({"a": ""}, "a", default="fallback") == "fallback"  # 空字串被跳過


def test_to_float_and_to_int_handle_placeholders():
    assert to_float("1,234.5") == 1234.5
    assert to_float("--") is None
    assert to_float(None) is None
    assert to_int("1,000") == 1000
    assert to_int("not a number") is None


def test_roc_yyymm_to_western():
    assert roc_yyymm_to_western("11507") == "2026-07"
    assert roc_yyymm_to_western("10001") == "2011-01"


def test_roc_date_to_western():
    assert roc_date_to_western("1150810") == dt.date(2026, 8, 10)
    assert roc_date_to_western("bad") == dt.date.today()  # 容錯


# ---- http.py --------------------------------------------------------------


def test_rate_limiter_allows_calls_within_limit():
    limiter = RateLimiter(max_calls=3, period_seconds=60)
    # 不應該 raise 或 hang(在限制內)
    for _ in range(3):
        limiter.acquire()


def test_get_json_retries_then_succeeds(monkeypatch):
    calls = {"n": 0}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"ok": True}

    def fake_get(url, params=None, headers=None, timeout=None):
        calls["n"] += 1
        if calls["n"] < 2:
            import requests

            raise requests.ConnectionError("boom")
        return FakeResponse()

    monkeypatch.setattr("taiwan_stock_ai.data.http.requests.get", fake_get)
    monkeypatch.setattr("taiwan_stock_ai.data.http.time.sleep", lambda *_: None)

    result = get_json("https://example.invalid/api", retries=3)
    assert result == {"ok": True}
    assert calls["n"] == 2


def test_get_json_raises_http_error_after_exhausting_retries(monkeypatch):
    import requests

    def always_fail(*args, **kwargs):
        raise requests.ConnectionError("nope")

    monkeypatch.setattr("taiwan_stock_ai.data.http.requests.get", always_fail)
    monkeypatch.setattr("taiwan_stock_ai.data.http.time.sleep", lambda *_: None)

    with pytest.raises(HttpError):
        get_json("https://example.invalid/api", retries=2)


# ---- twse_client.py normalization -----------------------------------------


def test_fetch_daily_quotes_all_normalizes_known_fields(monkeypatch):
    raw = [
        {
            "Code": "2330",
            "Name": "台積電",
            "OpeningPrice": "1,000.00",
            "HighestPrice": "1,010.00",
            "LowestPrice": "995.00",
            "ClosingPrice": "1,005.00",
            "TradeVolume": "12,345,678",
            "TradeValue": "123,456,789",
            "Change": "5.00",
            "Transaction": "5,555",
        }
    ]
    monkeypatch.setattr(twse_client, "get_json", lambda *a, **k: raw)

    rows = twse_client.fetch_daily_quotes_all(dt.date(2026, 8, 14))

    assert len(rows) == 1
    row = rows[0]
    assert row["stock_id"] == "2330"
    assert row["close"] == 1005.0
    assert row["volume_shares"] == 12345678
    assert row["market"] == "TWSE"
    assert row["trade_date"] == dt.date(2026, 8, 14)


def test_fetch_daily_quotes_all_skips_rows_without_code(monkeypatch):
    raw = [{"Name": "缺代號"}, {"Code": "2330", "Name": "台積電"}]
    monkeypatch.setattr(twse_client, "get_json", lambda *a, **k: raw)

    rows = twse_client.fetch_daily_quotes_all()
    assert len(rows) == 1
    assert rows[0]["stock_id"] == "2330"


def test_fetch_monthly_revenue_normalizes_roc_fields(monkeypatch):
    raw = [
        {
            "公司代號": "2330",
            "公司名稱": "台積電股份有限公司",
            "資料年月": "11507",
            "營業收入-當月營收": "200000000",
            "營業收入-上月營收": "190000000",
            "營業收入-去年當月營收": "180000000",
            "營業收入-上月比較增減(%)": "5.26",
            "營業收入-去年同月增減(%)": "11.11",
        }
    ]
    monkeypatch.setattr(twse_client, "get_json", lambda *a, **k: raw)

    rows = twse_client.fetch_monthly_revenue()
    assert rows[0]["revenue_year_month"] == "2026-07"
    assert rows[0]["revenue"] == 200000000
    assert rows[0]["yoy_pct"] == 11.11


def test_fetch_disposition_stocks_returns_none_on_exception(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(twse_client, "get_json", boom)
    assert twse_client.fetch_disposition_stocks() is None


def test_fetch_disposition_stocks_parses_dict_payload(monkeypatch):
    payload = {"data": [{"Code": "1234", "Reason": "測試處置", "StartDate": "1150810"}]}
    monkeypatch.setattr(twse_client, "get_json", lambda *a, **k: payload)

    rows = twse_client.fetch_disposition_stocks()
    assert rows is not None
    assert rows[0]["stock_id"] == "1234"
    assert rows[0]["start_date"] == dt.date(2026, 8, 10)


# ---- finmind_client.py -----------------------------------------------------


def test_fetch_stock_price_parses_finmind_payload(monkeypatch):
    payload = {
        "status": 200,
        "data": [
            {
                "date": "2026-08-14",
                "stock_id": "2330",
                "open": 1000.0,
                "max": 1010.0,
                "min": 995.0,
                "close": 1005.0,
                "spread": 5.0,
                "Trading_Volume": 12345678,
                "Trading_money": 123456789,
                "Trading_turnover": 5555,
            }
        ],
    }
    monkeypatch.setattr(finmind_client, "get_json", lambda *a, **k: payload)

    rows = finmind_client.fetch_stock_price("2330", dt.date(2026, 8, 1))
    assert len(rows) == 1
    assert rows[0]["close"] == 1005.0
    assert rows[0]["source"] == "finmind:TaiwanStockPrice"


def test_fetch_dataset_returns_empty_on_bad_status(monkeypatch):
    monkeypatch.setattr(finmind_client, "get_json", lambda *a, **k: {"status": 402, "msg": "paid feature"})
    rows = finmind_client.fetch_stock_price("2330", dt.date(2026, 8, 1))
    assert rows == []
