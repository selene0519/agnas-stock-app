from __future__ import annotations


def test_quote_targets_exclude_inactive_symbols(monkeypatch, tmp_path) -> None:
    from app.services import quotes

    monkeypatch.setattr(quotes.data, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(quotes.data, "inactive_symbols", lambda market: {"EXAS"} if market == "us" else set())
    monkeypatch.setattr(quotes.data, "read_csv", lambda _path: [{"symbol": "EXAS"}, {"symbol": "ABT"}])
    monkeypatch.setattr(quotes.data, "dataframe_records", lambda rows: rows)
    monkeypatch.setattr(quotes.data, "positions", lambda _market: {"items": []})
    monkeypatch.setattr(quotes.data, "symbols", lambda _market: {"items": []})

    assert quotes._refresh_targets("us", None, 150) == ["ABT"]


def test_us_recommendation_universe_excludes_inactive_symbols(monkeypatch) -> None:
    from scripts import generate_us_recommendations as generator

    monkeypatch.setattr(generator, "inactive_symbols", lambda _market: {"EXAS"})
    monkeypatch.setattr(
        generator,
        "_read_csv",
        lambda _path: [{"market": "us", "symbol": "EXAS"}, {"market": "us", "symbol": "ABT"}],
    )

    assert generator._load_us_candidate_symbols() == ["ABT"]


def test_price_collection_bucket_drops_inactive_symbol(monkeypatch) -> None:
    from scripts import build_price_collection_universe as builder

    monkeypatch.setattr(builder, "is_inactive", lambda market, symbol: market == "us" and symbol == "EXAS")
    bucket = {}
    builder.add_symbol(bucket, {"market": "us", "symbol": "EXAS"}, "us", "targets", "test.csv")
    builder.add_symbol(bucket, {"market": "us", "symbol": "ABT"}, "us", "targets", "test.csv")

    assert ("us", "EXAS") not in bucket
    assert ("us", "ABT") in bucket
