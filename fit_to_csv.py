#!/usr/bin/env python3
"""Convert one Garmin FIT activity into a summary CSV and a record-stream CSV.

Uses only Python's standard library. FIT values are read from the binary
protocol; no FIT SDK or pip package is required.

Calculation notes:
* The activity summary prefers FIT session fields for timer duration,
  distance, average power, and average heart rate. FIT distance is in 0.01 m,
  and session timer time is in milliseconds.
* If session average power is absent, average power is the arithmetic mean of
  the available record power samples. Average heart rate falls back to the
  arithmetic mean of positive record HR samples; zero HR samples mean missing.
* Each rolling power result is the highest arithmetic mean of record power
  samples whose timestamps fall in a window of the requested length. Windows
  are anchored at each sample timestamp, use no interpolation, and need at
  least 90% of their expected one-second samples spanning at least length-2 s.
  The 90% allowance tolerates occasional missing samples without treating a
  short partial effort as a full-duration result.
* Record altitude is raw FIT altitude / 5 - 500 m; distance / 100 m;
  speed / 1000 m/s; latitude/longitude semicircles * 180 / 2^31 degrees.
* Timestamps in both CSVs are UTC. The date column is taken from the filename.
"""

from __future__ import annotations

import argparse
import csv
import math
import re
import struct
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

FIT_EPOCH = datetime(1989, 12, 31, tzinfo=timezone.utc)
WINDOWS = (15, 30, 60, 120, 300, 600, 1200, 1800, 3600)


def _decode_value(data: bytes, base_type: int, little_endian: bool) -> Any:
    """Decode a scalar FIT field, returning None for its invalid sentinel."""
    kind = base_type & 0x1F
    endian = "<" if little_endian else ">"
    formats = {
        0: ("B", 0xFF),       # enum
        1: ("b", 0x7F),       # sint8
        2: ("B", 0xFF),       # uint8
        3: ("h", 0x7FFF),     # sint16
        4: ("H", 0xFFFF),     # uint16
        5: ("i", 0x7FFFFFFF), # sint32
        6: ("I", 0xFFFFFFFF), # uint32
        10: ("B", 0),         # uint8z
        11: ("H", 0),         # uint16z
        12: ("I", 0),         # uint32z
        13: ("B", 0xFF),       # byte
        15: ("Q", 0xFFFFFFFFFFFFFFFF),  # uint64
    }
    if kind in formats and len(data) == struct.calcsize(formats[kind][0]):
        fmt, invalid = formats[kind]
        value = struct.unpack(endian + fmt, data)[0]
        return None if value == invalid else value
    if kind == 8 and len(data) == 4:  # float32
        value = struct.unpack(endian + "f", data)[0]
        return None if not math.isfinite(value) else value
    if kind == 9 and len(data) == 8:  # float64
        value = struct.unpack(endian + "d", data)[0]
        return None if not math.isfinite(value) else value
    # FIT string/byte arrays are not needed for the fields used here.
    if kind == 7:
        return data.rstrip(b"\0").decode("utf-8", errors="replace")
    if kind == 13:
        return data[0] if len(data) == 1 else data
    if len(data) == 1:
        return data[0]
    return None


def read_fit(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Return record messages, session messages, and file-id messages."""
    content = path.read_bytes()
    if len(content) < 14 or content[8:12] != b".FIT":
        raise ValueError(f"Not a valid FIT file: {path}")
    header_size = content[0]
    data_size = struct.unpack_from("<I", content, 4)[0]
    data_end = header_size + data_size
    if data_end > len(content):
        raise ValueError("FIT data size extends beyond the end of the file")

    definitions: dict[int, dict[str, Any]] = {}
    records: list[dict[str, Any]] = []
    sessions: list[dict[str, Any]] = []
    file_ids: list[dict[str, Any]] = []
    offset = header_size
    last_timestamp: int | None = None

    while offset < data_end:
        header = content[offset]
        offset += 1
        compressed = bool(header & 0x80)
        if compressed:
            # Compressed headers store local message type in bits 6-5 and the
            # low five bits of the timestamp in bits 4-0.
            local_type = (header >> 5) & 0x03
            is_definition = False
            developer_data = False
        else:
            is_definition = bool(header & 0x40)
            developer_data = bool(header & 0x20)
            local_type = header & 0x0F

        if is_definition:
            if offset + 5 > data_end:
                raise ValueError("Truncated FIT definition message")
            offset += 1  # reserved byte
            architecture = content[offset]
            offset += 1
            little = architecture == 0
            global_num = struct.unpack_from("<H" if little else ">H", content, offset)[0]
            offset += 2
            field_count = content[offset]
            offset += 1
            fields = []
            for _ in range(field_count):
                number, size, base_type = content[offset : offset + 3]
                offset += 3
                fields.append((number, size, base_type))
            dev_fields = []
            if developer_data:
                dev_count = content[offset]
                offset += 1
                for _ in range(dev_count):
                    number, size, developer_index = content[offset : offset + 3]
                    offset += 3
                    dev_fields.append((number, size, developer_index))
            definitions[local_type] = {
                "global": global_num,
                "little": little,
                "fields": fields,
                "dev_fields": dev_fields,
            }
            continue

        if local_type not in definitions:
            raise ValueError(f"FIT data message references undefined local message {local_type}")
        definition = definitions[local_type]
        values: dict[int, Any] = {}
        compressed_timestamp: int | None = None
        if compressed and last_timestamp is not None:
            compressed_timestamp = (last_timestamp & ~0x1F) | (header & 0x1F)
            if compressed_timestamp < last_timestamp:
                compressed_timestamp += 0x20

        for number, size, base_type in definition["fields"]:
            raw = content[offset : offset + size]
            if len(raw) != size:
                raise ValueError("Truncated FIT data message")
            values[number] = _decode_value(raw, base_type, definition["little"])
            offset += size
        for _, size, _ in definition["dev_fields"]:
            offset += size

        if compressed_timestamp is not None and 253 not in values:
            values[253] = compressed_timestamp
        timestamp = values.get(253)
        if timestamp is not None:
            last_timestamp = int(timestamp)

        global_num = definition["global"]
        if global_num == 20:
            records.append(values)
        elif global_num == 18:
            sessions.append(values)
        elif global_num == 0:
            file_ids.append(values)

    return records, sessions, file_ids


def fit_time(seconds: Any) -> str:
    if seconds is None:
        return ""
    return (FIT_EPOCH + timedelta(seconds=float(seconds))).isoformat(timespec="seconds")


def get_nonzero(value: Any) -> Any:
    return value if value is not None and value > 0 else None


def rolling_max(power_samples: list[tuple[int, float]], seconds: int) -> float | None:
    """Maximum sample mean in any sufficiently complete seconds-long window."""
    if not power_samples:
        return None
    times = [sample[0] for sample in power_samples]
    prefix = [0.0]
    for _, power in power_samples:
        prefix.append(prefix[-1] + power)

    best: float | None = None
    left = 0
    for right, end_time in enumerate(times):
        start_time = end_time - seconds + 1
        while left < right and times[left] < start_time:
            left += 1
        count = right - left + 1
        if count < math.ceil(seconds * 0.9) or times[right] - times[left] < seconds - 2:
            continue
        mean = (prefix[right + 1] - prefix[left]) / count
        if best is None or mean > best:
            best = mean
    return best


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def convert(
    input_file: Path,
    output_dir: Path | None = None,
    *,
    metadata_writer: csv.DictWriter | None = None,
    records_writer: csv.DictWriter | None = None,
) -> tuple[Path | None, Path | None, dict[str, Any]]:
    records, sessions, file_ids = read_fit(input_file)
    session = sessions[-1] if sessions else {}
    file_id = file_ids[0] if file_ids else {}

    match = re.match(r"^(\d{4}-\d{2}-\d{2})", input_file.name)
    filename_date = match.group(1) if match else ""
    start_timestamp = session.get(2)
    if start_timestamp is None and records:
        start_timestamp = records[0].get(253)

    power_values = [float(row[7]) for row in records if row.get(7) is not None]
    hr_values = [float(row[3]) for row in records if row.get(3) is not None and row[3] > 0]
    avg_power = session.get(20)
    if avg_power is None and power_values:
        avg_power = sum(power_values) / len(power_values)
    avg_hr = get_nonzero(session.get(16))
    if avg_hr is None and hr_values:
        avg_hr = sum(hr_values) / len(hr_values)

    distance_m = session.get(9)
    if distance_m is not None:
        distance_m = distance_m / 100
    elif records and records[-1].get(5) is not None:
        distance_m = records[-1][5] / 100

    duration_s = session.get(8)
    if duration_s is not None:
        duration_s = duration_s / 1000
    elif len(records) > 1 and records[0].get(253) is not None and records[-1].get(253) is not None:
        duration_s = records[-1][253] - records[0][253]

    # Some FITs contain only file/session metadata and no time-series samples.
    # Keep their file row, but do not present empty-session zeroes as workout metrics.
    if not records:
        duration_s = None
        distance_m = None
        avg_power = None
        avg_hr = None

    record_rows = []
    timed_power = []
    for row in records:
        timestamp = row.get(253)
        power = row.get(7)
        if timestamp is not None and power is not None:
            timed_power.append((int(timestamp), float(power)))
        record_rows.append(
            {
                "activity_file": input_file.name,
                "timestamp_utc": fit_time(timestamp),
                "latitude_deg": round(row[0] * 180 / 2147483648, 6) if row.get(0) is not None else "",
                "longitude_deg": round(row[1] * 180 / 2147483648, 6) if row.get(1) is not None else "",
                "altitude_m": round(row[2] / 5 - 500, 2) if row.get(2) is not None else "",
                "heart_rate_bpm": get_nonzero(row.get(3)) or "",
                "cadence_rpm": row.get(4) if row.get(4) is not None else "",
                "distance_m": round(row[5] / 100, 2) if row.get(5) is not None else "",
                "speed_m_s": round(row[6] / 1000, 3) if row.get(6) is not None else "",
                "power_w": power if power is not None else "",
                "temperature_c": row.get(13) if row.get(13) is not None else "",
                "raw_timestamp_s": timestamp if timestamp is not None else "",
            }
        )

    summary: dict[str, Any] = {
        "activity_file": input_file.name,
        "date_from_filename": filename_date,
        "start_time_utc": fit_time(start_timestamp),
        "sport": session.get(5, ""),
        "sub_sport": session.get(6, ""),
        "duration_s": round(duration_s, 1) if duration_s is not None else "",
        "distance_m": round(distance_m, 2) if distance_m is not None else "",
        "avg_power_w": round(float(avg_power), 2) if avg_power is not None else "",
        "avg_heart_rate_bpm": round(float(avg_hr), 2) if avg_hr is not None else "",
        "max_heart_rate_bpm": get_nonzero(session.get(17)) or "",
        "total_ascent_m": session.get(22, "") if records else "",
        "total_descent_m": session.get(23, "") if records else "",
        "record_count": len(records),
        "manufacturer": file_id.get(1, ""),
        "product_id": file_id.get(2, ""),
        "normalized_power_w": session.get(34, ""),
        "training_stress_score": session.get(35, ""),
    }
    for seconds in WINDOWS:
        value = rolling_max(timed_power, seconds)
        summary[f"max_avg_power_{seconds}s_w"] = round(value, 2) if value is not None else ""

    metadata_fields = list(summary)
    record_fields = [
        "activity_file", "timestamp_utc", "latitude_deg", "longitude_deg", "altitude_m",
        "heart_rate_bpm", "cadence_rpm", "distance_m", "speed_m_s", "power_w",
        "temperature_c", "raw_timestamp_s",
    ]
    if metadata_writer is not None and records_writer is not None:
        metadata_writer.writerow(summary)
        records_writer.writerows(record_rows)
        return None, None, summary

    if output_dir is None:
        raise ValueError("output_dir is required when writing a single activity")
    metadata_path = output_dir / "activity_metadata.csv"
    records_path = output_dir / "workout_records.csv"
    write_csv(metadata_path, metadata_fields, [summary])
    write_csv(records_path, record_fields, record_rows)
    return metadata_path, records_path, summary


def convert_folder(input_dir: Path, output_dir: Path, years: list[int]) -> tuple[int, int, list[tuple[str, str]]]:
    """Convert matching FIT files into one consolidated pair of CSV files."""
    if not input_dir.is_dir():
        raise NotADirectoryError(f"Input directory does not exist: {input_dir}")

    year_set = {str(year) for year in years}
    fit_files = sorted(
        path for path in input_dir.rglob("*.fit")
        if re.match(r"^(\d{4})-", path.name) and path.name[:4] in year_set
    )
    if not fit_files:
        raise FileNotFoundError(f"No FIT files found for years {', '.join(map(str, years))} in {input_dir}")

    output_dir.mkdir(parents=True, exist_ok=True)
    metadata_path = output_dir / "activity_metadata.csv"
    records_path = output_dir / "workout_records.csv"
    metadata_fields = [
        "activity_file", "date_from_filename", "start_time_utc", "sport", "sub_sport",
        "duration_s", "distance_m", "avg_power_w", "avg_heart_rate_bpm", "max_heart_rate_bpm",
        "total_ascent_m", "total_descent_m", "record_count", "manufacturer", "product_id",
        "normalized_power_w", "training_stress_score",
        *[f"max_avg_power_{seconds}s_w" for seconds in WINDOWS],
    ]
    record_fields = [
        "activity_file", "timestamp_utc", "latitude_deg", "longitude_deg", "altitude_m",
        "heart_rate_bpm", "cadence_rpm", "distance_m", "speed_m_s", "power_w",
        "temperature_c", "raw_timestamp_s",
    ]
    failures: list[tuple[str, str]] = []
    completed = 0
    record_count = 0

    with metadata_path.open("w", newline="", encoding="utf-8-sig") as metadata_stream, records_path.open(
        "w", newline="", encoding="utf-8-sig"
    ) as records_stream:
        metadata_writer = csv.DictWriter(metadata_stream, fieldnames=metadata_fields, extrasaction="ignore")
        records_writer = csv.DictWriter(records_stream, fieldnames=record_fields, extrasaction="ignore")
        metadata_writer.writeheader()
        records_writer.writeheader()
        for index, fit_file in enumerate(fit_files, start=1):
            try:
                _, _, summary = convert(
                    fit_file,
                    metadata_writer=metadata_writer,
                    records_writer=records_writer,
                )
                completed += 1
                record_count += int(summary["record_count"])
                print(f"[{index}/{len(fit_files)}] Converted {fit_file.name}")
            except Exception as error:  # keep processing the remaining files, but report every omission
                failures.append((str(fit_file), str(error)))
                print(f"[{index}/{len(fit_files)}] FAILED {fit_file.name}: {error}")

    print(f"Processed {completed} of {len(fit_files)} files; wrote {record_count} workout records.")
    if failures:
        print("Files omitted because conversion failed:")
        for file_name, error in failures:
            print(f"  {file_name}: {error}")
    print(f"Metadata CSV: {metadata_path}")
    print(f"Workout records CSV: {records_path}")
    return completed, record_count, failures


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert a FIT workout into Power BI-friendly CSV files.")
    parser.add_argument("input_path", type=Path, help="Path to one .fit file or a directory containing FIT files")
    parser.add_argument("--output-dir", type=Path, default=Path("output"), help="Directory for the two CSVs (default: output)")
    parser.add_argument("--years", type=int, nargs="+", help="When input_path is a directory, include only these filename years")
    args = parser.parse_args()
    if args.input_path.is_dir():
        years = args.years or [datetime.now().year]
        convert_folder(args.input_path, args.output_dir, years)
    else:
        metadata, records, summary = convert(args.input_path, args.output_dir)
        print(f"Metadata: {metadata}")
        print(f"Workout records: {records} ({summary['record_count']} rows)")
        print(f"Date: {summary['date_from_filename']}; distance: {summary['distance_m']} m; average power: {summary['avg_power_w']} W")


if __name__ == "__main__":
    main()
