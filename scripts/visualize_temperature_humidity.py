#!/Applications/Xcode.app/Contents/Developer/usr/bin/python3

from __future__ import annotations

import csv
from argparse import ArgumentParser
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import matplotlib.dates as mdates
import matplotlib.pyplot as plt


ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
FIGURE_DIR = ROOT / "figures"
TIMEZONE = ZoneInfo("Asia/Shanghai")
SENSOR_CONFIGS = (
    {
        "name": "106-设备区",
        "label": "外间",
        "color": "#2563EB",
    },
    {
        "name": "106-testing 5",
        "label": "内间",
        "color": "#EA580C",
    },
)
DEVICE_NAMES = tuple(sensor["name"] for sensor in SENSOR_CONFIGS)


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


def window_slug(start: datetime, end: datetime) -> str:
    return f"{start:%Y-%m-%d-%H-%M-%S}_to_{end:%Y-%m-%d-%H-%M-%S}"


def build_sensors(
    slug: str, device_names: list[str] | None = None
) -> list[dict[str, object]]:
    selected_devices = set(device_names or DEVICE_NAMES)
    return [
        {
            "csv": RAW_DIR / f"{sensor['name']}_raw_{slug}.csv",
            "label": sensor["label"],
            "color": sensor["color"],
        }
        for sensor in SENSOR_CONFIGS
        if sensor["name"] in selected_devices
    ]


WINDOW_START, WINDOW_END = default_window()
TIME_WINDOW = f"{WINDOW_START:%Y-%m-%d %H:%M} 至 {WINDOW_END:%Y-%m-%d %H:%M}"
TIME_WINDOW_SLUG = window_slug(WINDOW_START, WINDOW_END)
SENSORS = build_sensors(TIME_WINDOW_SLUG)


def configure_matplotlib() -> None:
    plt.rcParams.update(
        {
            "font.sans-serif": [
                "PingFang SC",
                "Heiti SC",
                "Songti SC",
                "Arial Unicode MS",
                "DejaVu Sans",
                "Arial",
                "sans-serif",
            ],
            "axes.unicode_minus": False,
            "axes.spines.top": True,
            "axes.spines.right": True,
            "figure.dpi": 140,
            "savefig.dpi": 200,
        }
    )


def find_column(headers: list[str], prefix: str) -> str:
    for header in headers:
        if header.strip().startswith(prefix):
            return header
    raise ValueError(f"CSV 中找不到以 {prefix!r} 开头的列")


def read_metric(csv_path: Path, metric_prefix: str) -> tuple[list[datetime], list[float]]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        if reader.fieldnames is None:
            raise ValueError(f"{csv_path} 没有表头")

        metric_column = find_column(reader.fieldnames, metric_prefix)
        points: list[tuple[datetime, float]] = []
        for row in reader:
            created_at = row.get("created_at", "").strip()
            metric_value = row.get(metric_column, "").strip()
            if not created_at or not metric_value:
                continue
            local_time = datetime.fromisoformat(created_at).replace(tzinfo=None)
            if not WINDOW_START <= local_time <= WINDOW_END:
                continue
            points.append((local_time, float(metric_value)))

    points.sort(key=lambda item: item[0])
    return [item[0] for item in points], [item[1] for item in points]


def read_latest_voltage(csv_path: Path) -> float | None:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        if reader.fieldnames is None:
            raise ValueError(f"{csv_path} 没有表头")

        voltage_column = find_column(reader.fieldnames, "field3(")
        points: list[tuple[datetime, float]] = []
        for row in reader:
            created_at = row.get("created_at", "").strip()
            voltage_value = row.get(voltage_column, "").strip()
            if not created_at or not voltage_value:
                continue
            local_time = datetime.fromisoformat(created_at).replace(tzinfo=None)
            if not WINDOW_START <= local_time <= WINDOW_END:
                continue
            points.append((local_time, float(voltage_value)))

    if not points:
        return None
    points.sort(key=lambda item: item[0])
    return points[-1][1]


def format_voltage(voltage: float | None) -> str:
    if voltage is None:
        return "--"
    return f"{voltage:.3f} V"


def add_summary_table(ax, rows: list[list[str]], row_colors: list[str]) -> None:
    table = ax.table(
        cellText=rows,
        colLabels=["设备", "最高", "最低", "差值", "电压"],
        cellLoc="center",
        colLoc="center",
        bbox=[0.21, 1.035, 0.58, 0.20],
    )
    table.auto_set_font_size(False)
    table.set_fontsize(8.6)

    for (row, column), cell in table.get_celld().items():
        cell.set_edgecolor("#D7DBE7")
        cell.set_linewidth(0.7)
        if row == 0:
            cell.set_facecolor("#F4F5F7")
            cell.get_text().set_weight("bold")
            cell.get_text().set_color("#1F2430")
        else:
            cell.set_facecolor("#FFFFFF")
            cell.get_text().set_color("#1F2430")
            if column == 0:
                cell.get_text().set_weight("bold")
                cell.get_text().set_color(row_colors[row - 1])


def plot_metric(
    ax,
    metric_prefix: str,
    title: str,
    unit: str,
    span_label: str,
    ylabel: str,
    reference_value: float,
    reference_label: str,
) -> list[str]:
    counts: list[str] = []
    summary_rows: list[list[str]] = []
    row_colors: list[str] = []

    for sensor in SENSORS:
        times, values = read_metric(sensor["csv"], metric_prefix)
        voltage = read_latest_voltage(sensor["csv"])
        counts.append(f"{sensor['label']} {len(values)} 个点")
        if values:
            metric_min = min(values)
            metric_max = max(values)
            metric_span = metric_max - metric_min
            summary_rows.append(
                [
                    sensor["label"],
                    f"{metric_max:.2f}{unit}",
                    f"{metric_min:.2f}{unit}",
                    f"{metric_span:.2f}{unit}",
                    format_voltage(voltage),
                ]
            )
            row_colors.append(sensor["color"])
        ax.plot(
            times,
            values,
            label=sensor["label"],
            color=sensor["color"],
            linewidth=1.8,
            marker="o",
            markersize=3.2,
            markeredgewidth=0,
        )

    ax.axhline(
        reference_value,
        color="#464C55",
        linestyle="--",
        linewidth=1.2,
        label=reference_label,
    )
    ax.set_title(title, loc="center", fontsize=15, fontweight="bold", y=1.29)
    add_summary_table(ax, summary_rows, row_colors)
    ax.set_ylabel(ylabel)
    ax.grid(True, axis="y", color="#E5E7EB", linewidth=0.8)
    ax.grid(True, axis="x", color="#F3F4F6", linewidth=0.6)
    ax.legend(frameon=False, loc="best")
    ax.set_xlim(WINDOW_START, WINDOW_END)

    for spine in ax.spines.values():
        spine.set_visible(True)
        spine.set_color("#1F2430")
        spine.set_linewidth(0.9)

    locator = mdates.AutoDateLocator(minticks=5, maxticks=9)
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
    return counts


def plot_combined() -> None:
    fig, axes = plt.subplots(2, 1, figsize=(11.4, 8.4), sharex=True)
    fig.subplots_adjust(left=0.08, right=0.985, top=0.88, bottom=0.08, hspace=0.60)

    temperature_counts = plot_metric(
        axes[0],
        "field1(",
        f"实验室温度（{TIME_WINDOW}）",
        " °C",
        "最大温差",
        "温度 (°C)",
        25,
        "25 °C 警戒线",
    )
    humidity_counts = plot_metric(
        axes[1],
        "field2(",
        f"实验室湿度（{TIME_WINDOW}）",
        "%RH",
        "最大湿度差",
        "相对湿度 (%RH)",
        39,
        "39% 警戒线",
    )

    axes[1].set_xlabel("时间")

    output_path = FIGURE_DIR / f"temperature_humidity_{TIME_WINDOW_SLUG}.png"
    fig.savefig(output_path, bbox_inches="tight")
    plt.close(fig)
    print(f"{output_path}: 温度 {', '.join(temperature_counts)}; 湿度 {', '.join(humidity_counts)}")


def parse_args() -> object:
    parser = ArgumentParser(description="Plot CyberLab temperature and humidity data.")
    parser.add_argument("--start", help="窗口开始时间，例如 2026-07-08 12:00:00")
    parser.add_argument("--end", help="窗口结束时间，例如 2026-07-09 12:00:00")
    parser.add_argument(
        "--device",
        action="append",
        choices=DEVICE_NAMES,
        help="仅绘制指定设备，可重复传入；默认绘制两台设备",
    )
    return parser.parse_args()


def set_time_window(
    start: datetime, end: datetime, device_names: list[str] | None = None
) -> None:
    global WINDOW_START, WINDOW_END, TIME_WINDOW, TIME_WINDOW_SLUG, SENSORS
    WINDOW_START = start
    WINDOW_END = end
    TIME_WINDOW = f"{WINDOW_START:%Y-%m-%d %H:%M} 至 {WINDOW_END:%Y-%m-%d %H:%M}"
    TIME_WINDOW_SLUG = window_slug(WINDOW_START, WINDOW_END)
    SENSORS = build_sensors(TIME_WINDOW_SLUG, device_names)


def main() -> None:
    args = parse_args()
    start = WINDOW_START
    end = WINDOW_END
    if args.start or args.end:
        if not args.start or not args.end:
            raise SystemExit("--start 和 --end 必须同时提供")
        start = parse_local_datetime(args.start)
        end = parse_local_datetime(args.end)

    set_time_window(start, end, args.device)

    configure_matplotlib()
    FIGURE_DIR.mkdir(parents=True, exist_ok=True)
    plot_combined()


if __name__ == "__main__":
    main()
