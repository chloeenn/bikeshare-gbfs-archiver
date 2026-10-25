import csv
import gzip
import json
from pathlib import Path

import pytest

import scrape

HERE = Path(__file__).parent


@pytest.fixture
def payload() -> dict:
    return json.loads((HERE / "sample_status.json").read_text())


def read_gz(path: Path) -> list[dict]:
    with gzip.open(path, "rt", newline="") as f:
        return list(csv.DictReader(f))


def test_parse_sample(payload):
    feed_ts, rows = scrape.parse_status(payload)
    assert feed_ts == payload["last_updated"]
    assert len(rows) == 20
    first = payload["data"]["stations"][0]
    assert rows[0]["station_id"] == first["station_id"]
    assert rows[0]["bikes"] == first["num_bikes_available"]
    assert rows[0]["ebikes"] == first["num_bikes_available_types"]["ebike"]
    assert rows[0]["docks"] == first["num_docks_available"]


def test_mechanical_plus_ebikes_equals_bikes(payload):
    _, rows = scrape.parse_status(payload)
    assert scrape.count_type_mismatches(rows) == 0


def test_mismatch_is_counted(payload):
    _, rows = scrape.parse_status(payload)
    rows[0]["bikes"] += 1
    assert scrape.count_type_mismatches(rows) == 1


def test_schema(payload, tmp_path):
    feed_ts, rows = scrape.parse_status(payload)
    path = scrape.save_snapshot(tmp_path, feed_ts, rows)
    written = read_gz(path)
    assert list(written[0]) == scrape.STATUS_COLUMNS
    assert "status" not in written[0]
    assert len(written) == 20


def test_unexpected_schema_raises(payload):
    del payload["data"]["stations"][0]["num_docks_available"]
    with pytest.raises(ValueError):
        scrape.parse_status(payload)


def test_path_uses_utc_feed_ts(tmp_path):
    # 2026-10-25 05:07:24 UTC
    assert (
        scrape.snapshot_path(tmp_path, 1792904844)
        == tmp_path / "2026/10/25/050724.csv.gz"
    )


def test_same_snapshot_twice_does_not_duplicate(payload, tmp_path):
    feed_ts, rows = scrape.parse_status(payload)
    assert scrape.save_snapshot(tmp_path, feed_ts, rows) is not None
    assert scrape.save_snapshot(tmp_path, feed_ts, rows) is None
    files = list(tmp_path.rglob("*.csv.gz"))
    assert len(files) == 1
    assert len(read_gz(files[0])) == 20


def test_fetch_failure_exits_zero_and_saves_nothing(monkeypatch, tmp_path):
    monkeypatch.setattr(scrape, "fetch_json", lambda name: None)
    assert scrape.main(["--data-dir", str(tmp_path)]) == 0
    assert not list(tmp_path.rglob("*"))


def test_information_tolerates_missing_optional_fields():
    info = {
        "data": {"stations": [{"station_id": "1", "name": "A", "lat": 1, "lon": 2}]}
    }
    row = scrape.parse_information(info)[0]
    assert list(row) == scrape.INFO_COLUMNS
    assert row["capacity"] is None
