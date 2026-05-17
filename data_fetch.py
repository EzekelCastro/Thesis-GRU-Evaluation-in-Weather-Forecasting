"""
data_fetch.py
Fetches daily weather data from Meteostat for Baguio City and Manila.
Station IDs are fixed; date range is Jan 1 2020 through today (runtime).

Meteostat v2 API note: uses lowercase `daily()` function; average temperature
column is 'temp' (not 'tavg' from the old v1 API).
"""

from datetime import datetime
import pandas as pd
from meteostat import daily

# Meteostat station identifiers
STATIONS = {
    "Baguio": "98328",
    "Manila": "98425",
}

# Variables we care about throughout the whole pipeline.
# 'temp' is the average daily temperature column in Meteostat v2.
TARGET_COLUMNS = ["prcp", "temp", "wspd", "pres"]


def fetch_station_data(station_id: str, start: datetime, end: datetime) -> pd.DataFrame:
    """
    Pull daily weather records for one station and return only the
    four target columns.  Columns absent from the station are added as
    all-NaN so downstream code always has the full schema.
    """
    ts = daily(station_id, start, end)
    df = ts.fetch()

    # Normalise the index name so downstream code can always use df.index
    df.index.name = "time"

    if df.empty:
        raise RuntimeError(
            f"Meteostat returned no data for station {station_id} "
            f"between {start.date()} and {end.date()}."
        )

    # Keep only the columns we need; add missing ones as NaN
    for col in TARGET_COLUMNS:
        if col not in df.columns:
            df[col] = float("nan")

    return df[TARGET_COLUMNS]


def fetch_all_data(
    start: datetime | None = None,
    end: datetime | None = None,
) -> dict[str, pd.DataFrame]:
    """
    Fetch data for every station in STATIONS.
    Returns {station_name: DataFrame} with a DatetimeIndex.
    """
    if start is None:
        start = datetime(2020, 1, 1)
    if end is None:
        end = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    print(f"\nFetching weather data: {start.date()} -> {end.date()}")
    print("-" * 50)

    result = {}
    for name, sid in STATIONS.items():
        print(f"  {name} (Station {sid}) ...", end=" ", flush=True)
        df = fetch_station_data(sid, start, end)
        print(f"{len(df)} daily records retrieved.")
        result[name] = df

    return result
