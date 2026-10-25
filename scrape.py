"""Archive one Bike Share Toronto GBFS station_status snapshot per run."""

import argparse
import csv
import gzip
import io
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import requests

BASE = "https://tor.publicbikesystem.net/ube/gbfs/v1/en"
USER_AGENT = (
    "bikeshare-gbfs-archiver (+https://github.com/OWNER/bikeshare-gbfs-archiver)"
)
TIMEOUT_S = 20
RETRIES = 2
STALE_AFTER_S = 600

STATUS_COLUMNS = [
    "feed_ts",
    "station_id",
    "bikes",
    "ebikes",
    "mechanical",
    "bikes_disabled",
    "docks",
    "docks_disabled",
    "last_reported",
    "is_installed",
    "is_renting",
    "is_returning",
]
INFO_COLUMNS = [
    "station_id",
    "name",
    "lat",
    "lon",
    "capacity",
    "address",
    "physical_configuration",
]


def fetch_json(name: str) -> dict | None:
    """GET a feed with a timeout and retries; None if every attempt fails."""
    for attempt in range(RETRIES + 1):
        try:
            resp = requests.get(
                f"{BASE}/{name}", headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT_S
            )
            resp.raise_for_status()
            return resp.json()
        except (requests.RequestException, ValueError) as exc:
            print(f"fetch {name} attempt {attempt + 1} failed: {exc}")
            time.sleep(2 * attempt)
    return None


def parse_status(payload: dict) -> tuple[int, list[dict]]:
    """Return (feed_ts, rows). Raises ValueError if the schema is not as expected."""
    try:
        feed_ts = int(payload["last_updated"])
        rows = []
        for s in payload["data"]["stations"]:
            types = s["num_bikes_available_types"]
            rows.append(
                {
                    "feed_ts": feed_ts,
                    "station_id": s["station_id"],
                    "bikes": s["num_bikes_available"],
                    "ebikes": types["ebike"],
                    "mechanical": types["mechanical"],
                    "bikes_disabled": s["num_bikes_disabled"],
                    "docks": s["num_docks_available"],
                    "docks_disabled": s["num_docks_disabled"],
                    "last_reported": s["last_reported"],
                    "is_installed": s["is_installed"],
                    "is_renting": s["is_renting"],
                    "is_returning": s["is_returning"],
                }
            )
    except (KeyError, TypeError) as exc:
        raise ValueError(f"unexpected station_status schema: {exc!r}") from exc
    return feed_ts, rows


def parse_information(payload: dict) -> list[dict]:
    try:
        return [
            {"station_id": s["station_id"]} | {c: s.get(c) for c in INFO_COLUMNS[1:]}
            for s in payload["data"]["stations"]
        ]
    except (KeyError, TypeError) as exc:
        raise ValueError(f"unexpected station_information schema: {exc!r}") from exc


def count_type_mismatches(rows: list[dict]) -> int:
    return sum(r["mechanical"] + r["ebikes"] != r["bikes"] for r in rows)


def snapshot_path(data_dir: Path, feed_ts: int) -> Path:
    t = datetime.fromtimestamp(feed_ts, tz=UTC)
    return data_dir / f"{t:%Y}/{t:%m}/{t:%d}/{t:%H%M%S}.csv.gz"


def write_csv_gz(path: Path, columns: list[str], rows: list[dict]) -> None:
    """Write atomically so a killed run never leaves a truncated file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as gz:
        text = io.TextIOWrapper(gz, encoding="utf-8", newline="")
        writer = csv.DictWriter(text, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
        text.flush()
        text.detach()
    tmp.replace(path)


def save_snapshot(data_dir: Path, feed_ts: int, rows: list[dict]) -> Path | None:
    """Save the snapshot; None if a file for this feed_ts already exists."""
    path = snapshot_path(data_dir, feed_ts)
    if path.exists():
        return None
    write_csv_gz(path, STATUS_COLUMNS, rows)
    return path


def save_information_once_per_day(data_dir: Path, feed_ts: int) -> Path | None:
    path = snapshot_path(data_dir, feed_ts).parent / "stations.csv.gz"
    if path.exists():
        return None
    payload = fetch_json("station_information")
    if payload is None:
        return None
    try:
        write_csv_gz(path, INFO_COLUMNS, parse_information(payload))
    except ValueError as exc:
        print(f"::warning::{exc}")
        return None
    return path


def set_output(key: str, value: object) -> None:
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a") as f:
            f.write(f"{key}={value}\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", type=Path, default=Path("data"))
    args = ap.parse_args(argv)

    payload = fetch_json("station_status")
    if payload is None:
        print("::warning::station_status unavailable; nothing saved")
        return 0
    try:
        feed_ts, rows = parse_status(payload)
    except ValueError as exc:
        print(f"::warning::{exc}; nothing saved")
        return 0

    lag = time.time() - feed_ts
    if lag > STALE_AFTER_S:
        print(
            f"::warning::feed_ts is {lag / 60:.0f} min behind wall-clock; saving anyway"
        )
    bad = count_type_mismatches(rows)
    if bad:
        print(f"::warning::{bad} stations where mechanical + ebikes != bikes")

    set_output("feed_ts", feed_ts)
    path = save_snapshot(args.data_dir, feed_ts, rows)
    print(
        f"saved {path} ({len(rows)} stations)"
        if path
        else f"feed_ts {feed_ts} already saved"
    )
    info = save_information_once_per_day(args.data_dir, feed_ts)
    if info:
        print(f"saved {info}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
