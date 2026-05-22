from __future__ import annotations

import json

import core.kis_us_quote as kis_us


def test_exchange_candidates_prefers_row_metadata():
    row = {"exchange": "NYSE", "symbol": "XOM"}
    excds = kis_us.kis_us_exchange_candidates("XOM", row)
    assert excds[0] == "NYS"
    assert "NAS" in excds


def test_parse_kis_us_output_volume_and_value():
    parsed = kis_us._parse_kis_us_output({"last": "100.5", "base": "99", "tvol": "1200", "tr_pbmn": "120500"}, "NAS")
    assert parsed["ok"] is True
    assert parsed["quote_source"] == "kis_us_quote"
    assert parsed["quote_full_available"] is True
    assert parsed["intraday_volume"] == 1200.0


def test_fetch_kis_us_quote_api_success(monkeypatch):
    class FakeResp:
        def __init__(self, payload: dict):
            self._payload = payload

        def read(self):
            return json.dumps(self._payload).encode()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(req, timeout=8):
        return FakeResp({"rt_cd": "0", "output": {"last": "42", "base": "40", "tvol": "0"}})

    monkeypatch.setattr(kis_us, "_kis_configured", lambda: True)
    monkeypatch.setattr(
        kis_us,
        "get_kis_access_token",
        lambda env, allow_request=True: {"valid": True, "access_token": "tok"},
    )
    monkeypatch.setattr(kis_us, "merged_env", lambda: {"KIS_APP_KEY": "k", "KIS_APP_SECRET": "s"})
    monkeypatch.setattr(kis_us.urllib.request, "urlopen", fake_urlopen)
    out = kis_us.fetch_kis_us_quote_api("AAPL")
    assert out["ok"] is True
    assert out["quote_source"] == "kis_us_quote"
    assert out["kis_quote_attempted"] is True
    assert out["kis_quote_success"] is True
    assert out["kis_quote_error"] == ""
    assert out["kis_exchange_code"] == "NAS"
    assert out["last_price"] == 42.0


def test_fetch_kis_us_quote_api_failure_records_error(monkeypatch):
    monkeypatch.setattr(kis_us, "_kis_configured", lambda: False)
    out = kis_us.fetch_kis_us_quote_api("AAPL")
    assert out["ok"] is False
    assert out["kis_quote_attempted"] is True
    assert out["kis_quote_success"] is False
    assert "endpoint_not_configured" in out["kis_quote_error"]
