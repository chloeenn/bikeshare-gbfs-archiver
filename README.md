# bikeshare-gbfs-archiver

This repo keeps a history of Bike Share Toronto station availability. A GitHub Actions job fetches the public GBFS feed about every 15 minutes and commits one small file per fetch. It uses Python 3.11, `requests` and the standard library.

## What it collects

Every run saves the `station_status` feed from `https://tor.publicbikesystem.net/ube/gbfs/v1/en/station_status`. Once per UTC day it also saves `station_information` from the same host. The feed listed 1,071 stations when last checked.

The Toronto Parking Authority runs Bike Share Toronto and publishes the data on the City of Toronto Open Data portal: https://open.toronto.ca/dataset/bike-share-toronto/

Licence as listed on the dataset page: License not specified

## How it runs

The workflow in `.github/workflows/scrape.yml` runs at minutes 5, 20, 35 and 50 of every hour. You can also start it by hand with `workflow_dispatch`. A concurrency group stops two runs from overlapping.

Each request times out after 20 seconds and retries twice. If the fetch fails or the response lacks the expected fields, the script logs a warning, saves nothing and exits with status 0, so a temporary outage does not show as a failed run. If the feed timestamp is more than 10 minutes behind the clock, the script logs a warning and still saves the snapshot.

After the script finishes, the workflow commits any change under `data/` as `github-actions[bot]` with the message `data: <feed_ts>`, runs `git pull --rebase` and pushes. With no change, it makes no commit.

## Data layout and columns

Snapshots go to `data/YYYY/MM/DD/HHMMSS.csv.gz`. The path comes from the feed's own `last_updated` time in UTC. If that file already exists, the run saves nothing, so a snapshot is never stored twice. The daily station file is `data/YYYY/MM/DD/stations.csv.gz`.

Each snapshot has one row per station:

| Column | Source field |
|---|---|
| feed_ts | last_updated (epoch seconds) |
| station_id | station_id |
| bikes | num_bikes_available |
| ebikes | num_bikes_available_types.ebike |
| mechanical | num_bikes_available_types.mechanical |
| bikes_disabled | num_bikes_disabled |
| docks | num_docks_available |
| docks_disabled | num_docks_disabled |
| last_reported | last_reported (epoch seconds, per station) |
| is_installed | is_installed |
| is_renting | is_renting |
| is_returning | is_returning |

`status`, `is_charging_station` and `traffic` are skipped. In the feed checked, `mechanical + ebikes` equaled `bikes` at every station. The script logs a warning if that stops holding.

The station file has `station_id`, `name`, `lat`, `lon`, `capacity`, `address` and `physical_configuration`. Some stations have no `physical_configuration`, and the field is empty for them.

A snapshot of 1,071 stations compresses to about 8.4 KB, and the daily station file is about 33 KB. At 96 runs a day that adds up to roughly 0.84 MB per day, or about 300 MB per year if no run is skipped.

## Folder structure

```text
.
├── .github/workflows/scrape.yml   Schedule, scrape step, commit and push of changes under data/
├── scrape.py                      Fetch, parse and write; the whole pipeline
├── tests/
│   ├── test_scrape.py             Test cases
│   ├── sample_status.json         20-station sample of a real station_status response
│   └── sample_information.json    Matching station_information sample
├── requirements.txt               Runtime dependency (requests)
├── requirements-dev.txt           pytest and ruff
├── pytest.ini                     Puts the repo root on the import path
└── data/                          Created by the workflow; do not edit by hand
```

## Setup and tests

```bash
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/ruff check .
.venv/bin/pytest
.venv/bin/python scrape.py --data-dir /tmp/try
```

The tests use a saved 20-station sample of a real response. They cover parsing, the column schema, the `mechanical + ebikes` check, a failed fetch, and saving the same snapshot twice.

## Usage

Load a snapshot with pandas (not in `requirements.txt`; install it separately):

```python
import pandas as pd

df = pd.read_csv("data/2025/01/15/120500.csv.gz")
print(df[["station_id", "bikes", "ebikes", "docks"]].head())
```
