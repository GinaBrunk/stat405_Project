#!/usr/bin/env python3
"""Download BTS monthly on-time flight data or raw PREZIP archives."""

from __future__ import annotations

import argparse
import csv
import io
import re
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_OUT_DIR = BASE_DIR / "stat628_airplanes"
PREZIP_INDEX_URL = "https://transtats.bts.gov/PREZIP/"
USER_AGENT = "stat605-bts-downloader/1.0"
REQUEST_TIMEOUT_SECONDS = 120
CHUNK_SIZE = 1024 * 1024
DATASET_PREFIX = "On_Time_Reporting_Carrier_On_Time_Performance"

# Columns observed in /Users/liyuang/Desktop/STAT628/installment4/stat628_airplanes/*.csv
INSTALLMENT4_COLUMNS = [
    "Year",
    "Month",
    "DayofMonth",
    "DayOfWeek",
    "FlightDate",
    "Reporting_Airline",
    "DOT_ID_Reporting_Airline",
    "Flight_Number_Reporting_Airline",
    "OriginAirportID",
    "OriginAirportSeqID",
    "OriginCityMarketID",
    "Origin",
    "OriginCityName",
    "OriginState",
    "DestAirportID",
    "DestAirportSeqID",
    "DestCityMarketID",
    "Dest",
    "DestCityName",
    "DestStateName",
    "CRSDepTime",
    "DepTime",
    "DepDelay",
    "TaxiOut",
    "WheelsOff",
    "WheelsOn",
    "TaxiIn",
    "CRSArrTime",
    "ArrTime",
    "ArrDelay",
    "Cancelled",
    "CancellationCode",
    "Diverted",
    "CRSElapsedTime",
    "ActualElapsedTime",
    "AirTime",
    "Distance",
    "DistanceGroup",
    "CarrierDelay",
    "WeatherDelay",
    "NASDelay",
    "SecurityDelay",
    "LateAircraftDelay",
    "TotalAddGTime",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Download monthly BTS On-Time Reporting Carrier data and save it as "
            "airlines_YYYY_M.csv with the same columns used in installment4."
        )
    )
    parser.add_argument(
        "months",
        nargs="*",
        metavar="YYYY-MM",
        help="Specific months to download, e.g. 2024-09 2024-10 2025-11.",
    )
    parser.add_argument(
        "--start",
        help="Inclusive start month for a range download, format YYYY-MM.",
    )
    parser.add_argument(
        "--end",
        help="Inclusive end month for a range download, format YYYY-MM.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help=f"Output directory. Default: {DEFAULT_OUT_DIR}",
    )
    parser.add_argument(
        "--keep-zip",
        action="store_true",
        help="Keep the downloaded ZIP archives in the output directory.",
    )
    parser.add_argument(
        "--zip-only",
        action="store_true",
        help="Only download the raw BTS PREZIP archives and skip CSV extraction.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite an existing airlines_YYYY_M.csv if it already exists.",
    )
    parser.add_argument(
        "--keep-all-columns",
        action="store_true",
        help="Keep every raw BTS column instead of trimming to the installment4 schema.",
    )
    parser.add_argument(
        "--jobs",
        type=int,
        default=1,
        help="Number of months to download in parallel. Default: 1",
    )
    return parser.parse_args()


def log(message: str) -> None:
    print(message, flush=True)


def parse_year_month(value: str) -> tuple[int, int]:
    match = re.fullmatch(r"(\d{4})-(\d{1,2})", value.strip())
    if not match:
        raise ValueError(f"invalid year-month '{value}', expected YYYY-MM")

    year = int(match.group(1))
    month = int(match.group(2))
    if not 1 <= month <= 12:
        raise ValueError(f"invalid month '{value}', month must be between 1 and 12")

    return year, month


def month_iter(start: tuple[int, int], end: tuple[int, int]) -> list[tuple[int, int]]:
    start_key = start[0] * 12 + start[1]
    end_key = end[0] * 12 + end[1]
    if start_key > end_key:
        raise ValueError("--start must be earlier than or equal to --end")

    months: list[tuple[int, int]] = []
    year, month = start
    while (year, month) <= end:
        months.append((year, month))
        if month == 12:
            year += 1
            month = 1
        else:
            month += 1
    return months


def resolve_requested_months(args: argparse.Namespace) -> list[tuple[int, int]]:
    explicit = [parse_year_month(value) for value in args.months]

    if explicit and (args.start or args.end):
        raise ValueError("use either explicit YYYY-MM arguments or --start/--end, not both")

    if explicit:
        deduped = sorted(set(explicit))
        return deduped

    if bool(args.start) != bool(args.end):
        raise ValueError("--start and --end must be provided together")

    if args.start and args.end:
        return month_iter(parse_year_month(args.start), parse_year_month(args.end))

    raise ValueError("provide at least one YYYY-MM argument or a --start/--end range")


def fetch_text(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        encoding = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(encoding, errors="replace")


def resolve_archive_name(index_html: str, year: int, month: int) -> str:
    pattern = re.compile(
        rf"({re.escape(DATASET_PREFIX)}[^\"'<>\s]*_{year}_{month}\.zip)",
        flags=re.IGNORECASE,
    )
    matches = []
    for match in pattern.findall(index_html):
        if match not in matches:
            matches.append(match)

    if not matches:
        raise FileNotFoundError(
            f"could not find a BTS PREZIP archive for {year}-{month:02d}"
        )

    # Prefer the modern 1987_present name when several aliases exist.
    matches.sort(key=lambda value: ("1987_present" not in value, len(value), value))
    return matches[0]


def download_file(url: str, dest: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        total = response.headers.get("Content-Length")
        total_mb = None if total is None else int(total) / (1024 * 1024)
        if total_mb is None:
            log(f"  downloading {dest.name} ...")
        else:
            log(f"  downloading {dest.name} ({total_mb:.1f} MB) ...")

        downloaded = 0
        with dest.open("wb") as fh:
            while True:
                chunk = response.read(CHUNK_SIZE)
                if not chunk:
                    break
                fh.write(chunk)
                downloaded += len(chunk)

        log(f"  downloaded {downloaded / (1024 * 1024):.1f} MB")


def find_csv_member(zip_path: Path) -> str:
    with zipfile.ZipFile(zip_path) as zf:
        members = [name for name in zf.namelist() if name.lower().endswith(".csv")]
    if not members:
        raise FileNotFoundError(f"no CSV file found inside {zip_path.name}")
    if len(members) > 1:
        log(f"  note: {zip_path.name} contains multiple CSV files, using {members[0]}")
    return members[0]


def extract_trimmed_csv(zip_path: Path, output_path: Path) -> None:
    member_name = find_csv_member(zip_path)
    with zipfile.ZipFile(zip_path) as zf:
        with zf.open(member_name, "r") as zipped_csv:
            text_stream = io.TextIOWrapper(zipped_csv, encoding="utf-8-sig", newline="")
            reader = csv.reader(text_stream)
            header = next(reader)
            index_by_name = {name: idx for idx, name in enumerate(header)}

            missing = [name for name in INSTALLMENT4_COLUMNS if name not in index_by_name]
            if missing:
                raise KeyError(
                    "archive is missing required installment4 columns: "
                    + ", ".join(missing)
                )

            selected = [index_by_name[name] for name in INSTALLMENT4_COLUMNS]
            with output_path.open("w", encoding="utf-8", newline="") as out_fh:
                writer = csv.writer(out_fh)
                writer.writerow(INSTALLMENT4_COLUMNS)
                for row in reader:
                    writer.writerow([row[idx] if idx < len(row) else "" for idx in selected])


def extract_raw_csv(zip_path: Path, output_path: Path) -> None:
    member_name = find_csv_member(zip_path)
    with zipfile.ZipFile(zip_path) as zf:
        with zf.open(member_name, "r") as zipped_csv:
            with output_path.open("wb") as out_fh:
                while True:
                    chunk = zipped_csv.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    out_fh.write(chunk)


def build_archive_url(archive_name: str) -> str:
    encoded = urllib.parse.quote(archive_name, safe="")
    return urllib.parse.urljoin(PREZIP_INDEX_URL, encoded)


def process_month(
    year: int,
    month: int,
    index_html: str,
    out_dir: Path,
    overwrite: bool,
    keep_zip: bool,
    keep_all_columns: bool,
    zip_only: bool,
) -> None:
    archive_name = resolve_archive_name(index_html, year, month)
    output_path = (
        out_dir / archive_name if zip_only else out_dir / f"airlines_{year}_{month}.csv"
    )
    if output_path.exists() and not overwrite:
        log(f"{output_path.name}: already exists, skipping (use --overwrite to replace)")
        return

    archive_url = build_archive_url(archive_name)
    log(f"{year}-{month:02d}: {archive_name}")

    temp_zip: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            suffix=".tmpzip",
            prefix=f"bts_{year}_{month}_",
            dir=out_dir,
            delete=False,
        ) as tmp:
            temp_zip = Path(tmp.name)

        download_file(archive_url, temp_zip)

        if zip_only:
            temp_zip.replace(output_path)
            temp_zip = None
            log(f"  saved {output_path}")
        elif keep_all_columns:
            extract_raw_csv(temp_zip, output_path)
            log(f"  saved {output_path}")
        else:
            extract_trimmed_csv(temp_zip, output_path)
            log(f"  saved {output_path}")

        if keep_zip:
            zip_copy = out_dir / archive_name
            if temp_zip is None:
                log(f"  kept archive {output_path}")
            else:
                temp_zip.replace(zip_copy)
                temp_zip = None
                log(f"  kept archive {zip_copy}")
    finally:
        if temp_zip is not None and temp_zip.exists():
            temp_zip.unlink()


def main() -> int:
    try:
        args = parse_args()
        months = resolve_requested_months(args)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.jobs < 1:
        print("error: --jobs must be at least 1", file=sys.stderr)
        return 2

    if args.zip_only and args.keep_all_columns:
        print("error: --zip-only cannot be combined with --keep-all-columns", file=sys.stderr)
        return 2

    args.out_dir.mkdir(parents=True, exist_ok=True)

    try:
        log(f"Fetching BTS archive index from {PREZIP_INDEX_URL}")
        index_html = fetch_text(PREZIP_INDEX_URL)
        if args.jobs == 1:
            for year, month in months:
                process_month(
                    year=year,
                    month=month,
                    index_html=index_html,
                    out_dir=args.out_dir,
                    overwrite=args.overwrite,
                    keep_zip=args.keep_zip,
                    keep_all_columns=args.keep_all_columns,
                    zip_only=args.zip_only,
                )
        else:
            with ThreadPoolExecutor(max_workers=args.jobs) as executor:
                futures = [
                    executor.submit(
                        process_month,
                        year=year,
                        month=month,
                        index_html=index_html,
                        out_dir=args.out_dir,
                        overwrite=args.overwrite,
                        keep_zip=args.keep_zip,
                        keep_all_columns=args.keep_all_columns,
                        zip_only=args.zip_only,
                    )
                    for year, month in months
                ]
                for future in futures:
                    future.result()
    except (urllib.error.URLError, TimeoutError) as exc:
        print(f"network error: {exc}", file=sys.stderr)
        return 1
    except (FileNotFoundError, KeyError, zipfile.BadZipFile) as exc:
        print(f"data error: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
