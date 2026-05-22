from __future__ import annotations

import core.kis_us_orderbook as ob


def test_parse_orderbook_outputs_bid_ask():
    rows = [{"vbid1": "100", "vask1": "80", "pbid1": "10.5", "pask1": "10.6"}]
    parsed = ob._parse_orderbook_outputs(rows, "NAS")
    assert parsed["ok"] is True
    assert parsed["bid_total_volume"] == 100.0
    assert parsed["ask_total_volume"] == 80.0
    assert parsed["orderbook_data_source"] == "kis_us_orderbook"
    assert round(parsed["bid_ask_spread"], 4) == 0.1


def test_parse_orderbook_domestic_style_fields():
    rows = [{"bidp1": "12.0", "askp1": "12.2", "bidp_rsqn1": "50", "askp_rsqn1": "40"}]
    parsed = ob._parse_orderbook_outputs(rows, "NYS")
    assert parsed["ok"] is True
    assert parsed["best_bid"] == 12.0
    assert parsed["best_ask"] == 12.2


def test_fetch_kis_us_orderbook_api_success(monkeypatch):
    monkeypatch.setattr(
        ob,
        "kis_us_request",
        lambda path, tr_id, params, timeout=8: {
            "ok": True,
            "payload": {"output1": {"vbid1": "50", "vask1": "40", "pbid1": "12", "pask1": "12.1"}},
        },
    )
    out = ob.fetch_kis_us_orderbook_api("AAPL")
    assert out["ok"] is True
    assert out["kis_exchange"] == "NAS"


def test_fetch_stops_on_metadata_exchange_parse_miss(monkeypatch):
    calls: list[str] = []

    def _fake_request(path, tr_id, params, timeout=8):
        calls.append(params["EXCD"])
        return {
            "ok": True,
            "payload": {"output1": {"last": "100"}},
        }

    monkeypatch.setattr(ob, "kis_us_request", _fake_request)
    out = ob.fetch_kis_us_orderbook_api("AAPL", target_row={"exchange": "NYS"})
    assert out["ok"] is False
    assert out["failure_reason"] == "no_orderbook_fields"
    assert calls == ["NYS"]
