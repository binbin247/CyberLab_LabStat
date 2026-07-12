#!/Applications/Xcode.app/Contents/Developer/usr/bin/python3

from __future__ import annotations

import csv
import math
from argparse import ArgumentParser
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from lab_status_rules import (
    HUMIDITY_RANGE_RH,
    MAX_OUT_OF_RANGE_DURATION,
    MAX_SAMPLE_HOLD,
    TEMPERATURE_RANGE_C,
)


ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
REPORT_DIR = ROOT / "reports"
TIMEZONE = ZoneInfo("Asia/Shanghai")
SENSOR_CONFIGS = (
    {"name": "106-设备区", "label": "外间"},
    {"name": "106-testing 5", "label": "内间"},
)
DEVICE_NAMES = tuple(sensor["name"] for sensor in SENSOR_CONFIGS)


@dataclass(frozen=True)
class MetricSpec:
    name: str
    prefix: str
    unit: str
    normal_range: tuple[float, float]


@dataclass(frozen=True)
class MetricEvaluation:
    sensor_label: str
    metric: MetricSpec
    points: tuple[tuple[datetime, float], ...]
    out_of_range_duration: timedelta

    @property
    def is_abnormal(self) -> bool:
        return self.out_of_range_duration > MAX_OUT_OF_RANGE_DURATION


METRIC_SPECS = (
    MetricSpec("温度", "field1(", "°C", TEMPERATURE_RANGE_C),
    MetricSpec("湿度", "field2(", "%RH", HUMIDITY_RANGE_RH),
)


def default_window() -> tuple[datetime, datetime]:
    today = datetime.now(TIMEZONE).date()
    window_end = datetime.combine(today, time(12, 0, 0))
    return window_end - timedelta(days=1), window_end


def parse_local_datetime(value: str) -> datetime:
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass
    raise ValueError(f"时间格式不支持: {value!r}")


def parse_created_at(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(TIMEZONE).replace(tzinfo=None)
    return parsed


def window_slug(start: datetime, end: datetime) -> str:
    return f"{start:%Y-%m-%d-%H-%M-%S}_to_{end:%Y-%m-%d-%H-%M-%S}"


def find_column(headers: list[str], prefix: str) -> str:
    for header in headers:
        if header.strip().startswith(prefix):
            return header
    raise ValueError(f"CSV 中找不到以 {prefix!r} 开头的列")


def build_sensors(
    slug: str, device_names: list[str] | None = None
) -> list[dict[str, object]]:
    selected_devices = set(device_names or DEVICE_NAMES)
    return [
        {
            "csv": RAW_DIR / f"{sensor['name']}_raw_{slug}.csv",
            "label": sensor["label"],
        }
        for sensor in SENSOR_CONFIGS
        if sensor["name"] in selected_devices
    ]


def read_metric_points(
    csv_path: Path, metric: MetricSpec, start: datetime, end: datetime
) -> tuple[tuple[datetime, float], ...]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        if reader.fieldnames is None or "created_at" not in reader.fieldnames:
            raise ValueError(f"{csv_path} 缺少 created_at 表头")
        metric_column = find_column(reader.fieldnames, metric.prefix)
        points = []
        for row in reader:
            created_at = row.get("created_at", "").strip()
            metric_value = row.get(metric_column, "").strip()
            if not created_at or not metric_value:
                continue
            local_time = parse_created_at(created_at)
            if start <= local_time <= end:
                points.append((local_time, float(metric_value)))

    points.sort(key=lambda item: item[0])
    if not points:
        raise ValueError(f"{csv_path} 在目标时间窗内没有有效{metric.name}点")
    return tuple(points)


def is_out_of_range(value: float, normal_range: tuple[float, float]) -> bool:
    lower, upper = normal_range
    return value < lower or value > upper


def calculate_out_of_range_duration(
    points: tuple[tuple[datetime, float], ...],
    normal_range: tuple[float, float],
    end: datetime,
) -> timedelta:
    total = timedelta()
    for index, (timestamp, value) in enumerate(points):
        next_timestamp = points[index + 1][0] if index + 1 < len(points) else end
        interval_end = min(next_timestamp, end, timestamp + MAX_SAMPLE_HOLD)
        if interval_end > timestamp and is_out_of_range(value, normal_range):
            total += interval_end - timestamp
    return total


def evaluate_window(
    start: datetime, end: datetime, device_names: list[str] | None = None
) -> list[MetricEvaluation]:
    evaluations = []
    for sensor in build_sensors(window_slug(start, end), device_names):
        for metric in METRIC_SPECS:
            points = read_metric_points(sensor["csv"], metric, start, end)
            duration = calculate_out_of_range_duration(
                points, metric.normal_range, end
            )
            evaluations.append(
                MetricEvaluation(sensor["label"], metric, points, duration)
            )
    return evaluations


def format_duration(duration: timedelta) -> str:
    total_minutes = math.ceil(duration.total_seconds() / 60)
    hours, minutes = divmod(total_minutes, 60)
    if hours and minutes:
        return f"{hours} 小时 {minutes} 分钟"
    if hours:
        return f"{hours} 小时"
    return f"{minutes} 分钟"


def describe_extremes(evaluation: MetricEvaluation) -> str:
    lower, upper = evaluation.metric.normal_range
    below = [point for point in evaluation.points if point[1] < lower]
    above = [point for point in evaluation.points if point[1] > upper]
    descriptions = []
    if below:
        timestamp, value = min(below, key=lambda item: item[1])
        descriptions.append(
            f"最低 {value:.2f} {evaluation.metric.unit}（{timestamp:%Y-%m-%d %H:%M}）"
        )
    if above:
        timestamp, value = max(above, key=lambda item: item[1])
        descriptions.append(
            f"最高 {value:.2f} {evaluation.metric.unit}（{timestamp:%Y-%m-%d %H:%M}）"
        )
    return "，".join(descriptions)


def build_conclusion(
    evaluations: list[MetricEvaluation], start: datetime, end: datetime
) -> str:
    window = f"{start:%Y-%m-%d %H:%M} 至 {end:%Y-%m-%d %H:%M}"
    abnormal = [evaluation for evaluation in evaluations if evaluation.is_abnormal]
    if abnormal:
        details = []
        for evaluation in abnormal:
            lower, upper = evaluation.metric.normal_range
            details.append(
                f"{evaluation.sensor_label}{evaluation.metric.name}超出 "
                f"{lower:g}–{upper:g} {evaluation.metric.unit} 的累计时长为 "
                f"{format_duration(evaluation.out_of_range_duration)}"
                f"（{describe_extremes(evaluation)}）"
            )
        return f"实验室温湿度监测：不正常。{window} 期间，{'；'.join(details)}。"

    labels = []
    for evaluation in evaluations:
        if evaluation.sensor_label not in labels:
            labels.append(evaluation.sensor_label)
    coverage = "和".join(labels)
    return (
        f"实验室温湿度监测：正常。{window} 期间，{coverage}温度超出 "
        "20–25 °C、湿度超出 35–60 %RH 的各项累计时长均未超过 2 小时。"
    )


def parse_args() -> object:
    parser = ArgumentParser(description="Analyze CyberLab temperature and humidity.")
    parser.add_argument("--start", help="窗口开始时间，例如 2026-07-11 12:00:00")
    parser.add_argument("--end", help="窗口结束时间，例如 2026-07-12 12:00:00")
    parser.add_argument(
        "--device",
        action="append",
        choices=DEVICE_NAMES,
        help="仅分析指定设备，可重复传入；默认分析两台设备",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    start, end = default_window()
    if args.start or args.end:
        if not args.start or not args.end:
            raise SystemExit("--start 和 --end 必须同时提供")
        start = parse_local_datetime(args.start)
        end = parse_local_datetime(args.end)
    if start >= end:
        raise SystemExit("--start 必须早于 --end")

    evaluations = evaluate_window(start, end, args.device)
    conclusion = build_conclusion(evaluations, start, end)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = REPORT_DIR / f"lab_status_{window_slug(start, end)}.md"
    output_path.write_text(
        f"# 106 实验室状态结论\n\n{conclusion}\n", encoding="utf-8"
    )
    for evaluation in evaluations:
        print(
            f"{evaluation.sensor_label}{evaluation.metric.name}: "
            f"{len(evaluation.points)} 个点, "
            f"超限 {format_duration(evaluation.out_of_range_duration)}"
        )
    print(output_path)


if __name__ == "__main__":
    main()
