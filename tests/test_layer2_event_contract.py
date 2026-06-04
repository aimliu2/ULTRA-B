import pandas as pd

from ultrab.core.smc.candleEvent import FvgEventEngine
from ultrab.core.smc.pivotEvent import PivotEventEngine


BASE = pd.Timestamp("2024-01-01T00:00:00Z")


def row(hours: int, open_: float, high: float, low: float, close: float) -> pd.Series:
    return pd.Series(
        {"open": open_, "high": high, "low": low, "close": close},
        name=BASE + pd.Timedelta(hours=hours),
    )


def test_ce02_uses_canonical_event_stream_contract():
    engine = FvgEventEngine({"timeframe": "1H"})

    engine.on_bar(row(0, 100.0, 101.0, 99.0, 100.5))
    engine.on_bar(row(1, 100.5, 103.0, 100.0, 102.5))
    events = engine.on_bar(row(2, 104.0, 105.0, 102.0, 104.5))

    ce02 = next(event for event in events if event.event_code == "CE02")
    payload = ce02.to_dict()

    assert payload["eventId"].startswith("CE:CE02:1H:")
    assert payload["eventCode"] == "CE02"
    assert payload["eventGroup"] == "CE"
    assert payload["timeframe"] == "1H"
    assert payload["eventTimestamp"] == row(2, 0, 0, 0, 0).name
    assert payload["causalAvailableAt"] == payload["eventTimestamp"]
    assert payload["anchorTimestamp"] == row(1, 0, 0, 0, 0).name
    assert payload["pivotTimestamp"] == row(1, 0, 0, 0, 0).name
    assert payload["sourceBarIndexes"] == [0, 1, 2]
    assert [ref["barIndex"] for ref in payload["sourceCandleRefs"]] == [0, 1, 2]
    assert payload["type"] == "rally"
    assert payload["gapTop"] == 102.0
    assert payload["gapBottom"] == 101.0
    assert payload["price"] == 101.0


def test_pe01_uses_canonical_event_stream_contract():
    engine = PivotEventEngine(
        {
            "timeframe": "1H",
            "compute": {"str": True, "itr": False, "ltr": False},
            "str_bars": 1,
        }
    )

    engine.on_bar(row(0, 10.0, 11.0, 9.0, 10.5))
    events = engine.on_bar(row(1, 10.5, 10.8, 9.5, 10.0))

    pe01 = next(event for event in events if event.event_code == "PE01")
    payload = pe01.to_dict()

    assert payload["eventId"].startswith("PE:PE01:1H:")
    assert payload["eventCode"] == "PE01"
    assert payload["eventGroup"] == "PE"
    assert payload["timeframe"] == "1H"
    assert payload["tier"] == "str"
    assert payload["side"] == "high"
    assert payload["eventTimestamp"] == row(1, 0, 0, 0, 0).name
    assert payload["causalAvailableAt"] == payload["eventTimestamp"]
    assert payload["anchorTimestamp"] == row(0, 0, 0, 0, 0).name
    assert payload["pivotTimestamp"] == row(0, 0, 0, 0, 0).name
    assert payload["pivotPrice"] == 11.0
    assert payload["price"] == 11.0
    assert payload["sourceBarIndexes"] == [0, 1]
    assert [ref["barIndex"] for ref in payload["sourceCandleRefs"]] == [0, 1]
