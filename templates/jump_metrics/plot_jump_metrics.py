#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量读取多个 Excel/CSV 文件，在同一张图中比较：
1. jump_height_mm 随压强的变化；
2. horizontal_displacement_mm_abs 随压强的变化。

每个文件对应一条数据曲线，图例名称默认采用文件名（不含扩展名）。
默认采用“片段均值 + 95%置信带”：先在每个 segment_id 内求均值，
再以片段为独立重复计算总体均值和置信区间。
"""

from pathlib import Path
import os
import tempfile
import warnings

# 将 Matplotlib 缓存写入系统临时目录，避免无写权限环境产生警告
_mpl_cache = Path(tempfile.gettempdir()) / "multi_excel_jump_plot_cache"
_mpl_cache.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(_mpl_cache))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.lines import Line2D
from matplotlib.ticker import FuncFormatter, LogLocator, NullFormatter
import numpy as np
import pandas as pd


# ========================== 用户参数区 ==========================
SCRIPT_DIR = Path(__file__).resolve().parent

# 数据文件夹：推荐在脚本旁建立 input_data 文件夹，并把所有 Excel 放进去。
# 如果该文件夹不存在，程序会自动尝试读取脚本所在目录。
DATA_FOLDER = SCRIPT_DIR / "input_data"

# 支持的文件类型；如果只读取 Excel，可删去 "*.csv"
FILE_PATTERNS = ("*.xlsx", "*.xls", "*.csv")

# Excel 工作表：0 表示读取第一个工作表；也可填写工作表名称，如 "Sheet1"
SHEET_NAME = 0

# 输出文件夹
OUTPUT_DIR = SCRIPT_DIR / "multi_file_jump_results"

# 统计单位：
# "segment" = 先对同一片段内的全部颗粒求均值，再以片段作为独立重复（推荐）
# "trajectory" = 把每条颗粒轨迹直接作为独立样本
AGGREGATION_LEVEL = "segment"

# 不确定性范围："std"=标准差；"sem"=标准误；"ci95"=95%置信区间半宽
ERROR_MODE = "ci95"

# 不确定性呈现形式：
# "band" = 半透明置信带（多曲线对比推荐）
# "errorbar" = 传统误差棒
# "none" = 只显示均值曲线
UNCERTAINTY_STYLE = "band"

# 横坐标：推荐 "log"；如需线性压强坐标，改为 "linear"
X_SCALE = "log"

# 两个子图的纵坐标范围，可分别修改：格式为（下限, 上限）
# 例如 (0.0, 1.2) 表示纵坐标从 0.0 到 1.2 mm。
# 如果希望上限由程序自动确定，可写成 (0.0, None)。
JUMP_HEIGHT_YLIM = (0.0, 1.2)
HORIZONTAL_DISPLACEMENT_YLIM = (0.2, 1.1)

# 是否显示原始散点。多文件叠加时通常建议关闭，以保持图面清晰。
SHOW_RAW_POINTS = False

# 若开启原始散点，每个“文件—压强”最多显示的点数。
# 该参数只影响散点显示，不影响均值和误差计算。
MAX_RAW_POINTS_PER_PRESSURE = 120

# 是否额外输出两个指标的独立图片；默认只输出一张双面板组图
SAVE_INDIVIDUAL_FIGURES = False

# 图片参数
DPI = 600
COMBINED_FIGURE_SIZE = (12.0, 5.2)
INDIVIDUAL_FIGURE_SIZE = (7.2, 5.2)
LINE_WIDTH = 1.8
MARKER_SIZE = 6.0
ERROR_CAP_SIZE = 3.5
BAND_ALPHA = 0.12
RAW_POINT_SIZE = 7
RAW_POINT_ALPHA = 0.10

# 图例列数；设置为 None 时根据文件数量自动确定
LEGEND_COLUMNS = None

# 可选：手动替换某些文件在图例中的名称。
# 左侧必须是“不含扩展名的文件名”，右侧是希望显示的图例名称。
# 例如：{"125-180-a": "125–180 μm", "180-250-a": "180–250 μm"}
LEGEND_NAME_MAP = {}

# 若论文不需要图内标题，保持空字符串
JUMP_TITLE = ""
DISPLACEMENT_TITLE = ""
# ==============================================================


METRICS = {
    "jump_height_mm": {
        "ylabel": "Jump height (mm)",
        "panel": "(a)",
        "title": JUMP_TITLE,
        "filename": "multi_file_jump_height_vs_pressure.png",
        "ylim": JUMP_HEIGHT_YLIM,
    },
    "horizontal_displacement_mm_abs": {
        "ylabel": "Absolute horizontal displacement (mm)",
        "panel": "(b)",
        "title": DISPLACEMENT_TITLE,
        "filename": "multi_file_horizontal_displacement_vs_pressure.png",
        "ylim": HORIZONTAL_DISPLACEMENT_YLIM,
    },
}


def choose_roman_font() -> str:
    """优先使用 Times New Roman，缺失时采用相近的衬线字体。"""
    installed = {item.name for item in font_manager.fontManager.ttflist}
    for name in ("Times New Roman", "Nimbus Roman", "Liberation Serif", "DejaVu Serif"):
        if name in installed:
            return name
    return "serif"


def resolve_data_folder() -> Path:
    """依次尝试用户指定目录、脚本目录和当前交付环境的 upload 目录。"""
    candidates = [DATA_FOLDER, SCRIPT_DIR, SCRIPT_DIR / "upload"]
    for folder in candidates:
        if not folder.is_dir():
            continue
        has_file = any(
            any(not path.name.startswith("~$") for path in folder.glob(pattern))
            for pattern in FILE_PATTERNS
        )
        if has_file:
            return folder
    raise FileNotFoundError(
        "没有找到 Excel/CSV 文件。请把数据文件放入 input_data 文件夹，"
        "或修改代码顶部的 DATA_FOLDER。"
    )


def find_data_files(folder: Path) -> list[Path]:
    """搜索数据文件，忽略 Excel 打开时产生的 ~$ 临时文件。"""
    files: set[Path] = set()
    for pattern in FILE_PATTERNS:
        files.update(path for path in folder.glob(pattern) if not path.name.startswith("~$"))
    return sorted(files, key=lambda path: path.name.lower())


def read_table(path: Path) -> pd.DataFrame:
    """根据扩展名读取 Excel 或 CSV。"""
    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(path, sheet_name=SHEET_NAME)
    if suffix == ".csv":
        return pd.read_csv(path, encoding="utf-8-sig")
    raise ValueError(f"不支持的文件类型：{path.suffix}")


def clean_one_file(path: Path) -> pd.DataFrame:
    """读取单个文件，并保留压强和两个目标指标。"""
    table = read_table(path)
    required = ["pressure_Pa", *METRICS.keys()]
    missing = [column for column in required if column not in table.columns]
    if missing:
        raise KeyError(f"缺少列 {missing}")

    # segment_id 用于按实验片段进行分层统计；若文件没有该列则保留为空值
    selected_columns = required + (["segment_id"] if "segment_id" in table.columns else [])
    data = table[selected_columns].copy()
    if "segment_id" not in data.columns:
        data["segment_id"] = np.nan
    for column in required:
        data[column] = pd.to_numeric(data[column], errors="coerce")
    data = data.dropna(subset=required)
    data = data[data["pressure_Pa"] > 0]
    if data.empty:
        raise ValueError("清洗后没有有效数据")

    # source_name 决定图例中显示的文字
    default_name = path.stem
    data["source_file"] = path.name
    data["source_name"] = LEGEND_NAME_MAP.get(default_name, default_name)
    return data


def load_all_files(folder: Path) -> tuple[pd.DataFrame, list[str]]:
    """批量读取文件；列结构不正确的文件会被跳过并给出提示。"""
    valid_tables = []
    loaded_names = []

    for path in find_data_files(folder):
        try:
            data = clean_one_file(path)
        except Exception as exc:
            warnings.warn(f"跳过文件 {path.name}：{exc}")
            continue

        source_name = str(data["source_name"].iloc[0])
        valid_tables.append(data)
        loaded_names.append(source_name)
        print(f"已读取：{path.name}，有效数据 {len(data)} 条")

    if not valid_tables:
        raise ValueError(
            "未找到包含 pressure_Pa、jump_height_mm 和 "
            "horizontal_displacement_mm_abs 三列的有效文件。"
        )

    # 保留文件搜索顺序，避免图例顺序发生变化
    return pd.concat(valid_tables, ignore_index=True), loaded_names


def calculate_statistics(data: pd.DataFrame) -> pd.DataFrame:
    """按文件和压强计算统计量，可选择轨迹级或片段级独立重复。"""
    if AGGREGATION_LEVEL not in {"segment", "trajectory"}:
        raise ValueError('AGGREGATION_LEVEL 只能设为 "segment" 或 "trajectory"。')

    all_statistics = []

    for metric in METRICS:
        for (source_file, source_name), source_data in data.groupby(
            ["source_file", "source_name"], sort=False
        ):
            trajectory_counts = source_data.groupby("pressure_Pa")[metric].count()

            use_segment = (
                AGGREGATION_LEVEL == "segment"
                and source_data["segment_id"].notna().any()
            )
            if use_segment:
                # 先求每个片段内全部轨迹的平均值，避免轨迹多的片段权重过高
                independent_values = (
                    source_data.dropna(subset=["segment_id"])
                    .groupby(["pressure_Pa", "segment_id"], as_index=False)[metric]
                    .mean()
                )
                level_name = "segment"
            else:
                independent_values = source_data[["pressure_Pa", metric]].copy()
                level_name = "trajectory"

            grouped = (
                independent_values.groupby("pressure_Pa", as_index=False)[metric]
                .agg(
                    n_independent="count",
                    mean="mean",
                    median="median",
                    std="std",
                    q1=lambda values: values.quantile(0.25),
                    q3=lambda values: values.quantile(0.75),
                )
                .sort_values("pressure_Pa")
            )
            grouped["n_trajectory"] = grouped["pressure_Pa"].map(trajectory_counts)
            grouped["sem"] = grouped["std"] / np.sqrt(grouped["n_independent"])
            # 采用正态近似的双侧95%置信区间半宽
            grouped["ci95"] = 1.96 * grouped["sem"]
            grouped.insert(0, "source_file", source_file)
            grouped.insert(1, "source_name", source_name)
            grouped.insert(2, "metric", metric)
            grouped.insert(3, "aggregation_level", level_name)
            all_statistics.append(grouped)

    return pd.concat(all_statistics, ignore_index=True)


def pressure_formatter(value: float, _position: int | None = None) -> str:
    """将对数坐标中的 1000、10000 显示为 1k、10k。"""
    if value >= 1000:
        return f"{value / 1000:g}k"
    return f"{value:g}"


def configure_axis(ax: plt.Axes) -> None:
    """设置坐标轴格式。"""
    if X_SCALE == "log":
        ax.set_xscale("log")
        ax.xaxis.set_major_locator(LogLocator(base=10, subs=(1.0, 2.0, 5.0)))
        ax.xaxis.set_major_formatter(FuncFormatter(pressure_formatter))
        ax.xaxis.set_minor_locator(LogLocator(base=10, subs=np.arange(1, 10) * 0.1))
        ax.xaxis.set_minor_formatter(NullFormatter())
    elif X_SCALE != "linear":
        raise ValueError('X_SCALE 只能设为 "log" 或 "linear"。')

    ax.set_xlabel("Pressure (Pa)")
    ax.set_ylim(bottom=0)  # 高度和位移绝对值均不存在负值物理意义
    ax.grid(axis="y", color="#D9D9D9", linewidth=0.65, alpha=0.70)
    ax.margins(x=0.05, y=0.10)


def make_style_maps(source_names: list[str]) -> tuple[dict, dict, dict]:
    """采用色盲友好的 Okabe–Ito 配色，并配合不同点型和线型。"""
    okabe_ito = [
        "#0072B2",  # 深蓝
        "#D55E00",  # 朱红
        "#009E73",  # 蓝绿
        "#CC79A7",  # 紫红
        "#E69F00",  # 橙色
        "#56B4E9",  # 天蓝
        "#7A7A7A",  # 中性灰（替代过亮黄色）
        "#000000",  # 黑色
    ]
    markers = ["o", "s", "^", "D", "v", "P", "X", "<", ">", "h", "*", "p"]
    line_styles = ["-", "--", "-.", ":"]

    colors = {
        name: okabe_ito[index % len(okabe_ito)]
        for index, name in enumerate(source_names)
    }
    marker_map = {name: markers[index % len(markers)] for index, name in enumerate(source_names)}
    line_style_map = {
        name: line_styles[index % len(line_styles)]
        for index, name in enumerate(source_names)
    }
    return colors, marker_map, line_style_map


def add_raw_points(
    ax: plt.Axes,
    source_data: pd.DataFrame,
    metric: str,
    color,
    random_seed: int,
) -> None:
    """可选：抽样叠加某一文件的原始数据点。"""
    if not SHOW_RAW_POINTS:
        return

    rng = np.random.default_rng(random_seed)
    pressure_span = source_data["pressure_Pa"].max() - source_data["pressure_Pa"].min()

    for pressure, group in source_data.groupby("pressure_Pa", sort=True):
        if len(group) > MAX_RAW_POINTS_PER_PRESSURE:
            group = group.sample(MAX_RAW_POINTS_PER_PRESSURE, random_state=random_seed)

        if X_SCALE == "log":
            x_values = pressure * np.exp(rng.normal(0, 0.015, len(group)))
        else:
            jitter = max(pressure_span * 0.002, 1e-12)
            x_values = pressure + rng.normal(0, jitter, len(group))

        ax.scatter(
            x_values,
            group[metric],
            s=RAW_POINT_SIZE,
            color=color,
            alpha=RAW_POINT_ALPHA,
            edgecolors="none",
            rasterized=True,
            zorder=1,
        )


def draw_metric(
    ax: plt.Axes,
    data: pd.DataFrame,
    statistics: pd.DataFrame,
    metric: str,
    source_names: list[str],
    colors: dict,
    markers: dict,
    line_styles: dict,
    show_panel_label: bool,
) -> None:
    """在一个坐标轴中绘制所有文件对应的曲线。"""
    error_names = {"std": "SD", "sem": "SEM", "ci95": "95% CI"}
    if ERROR_MODE not in error_names:
        raise ValueError('ERROR_MODE 只能设为 "std"、"sem" 或 "ci95"。')
    if UNCERTAINTY_STYLE not in {"band", "errorbar", "none"}:
        raise ValueError(
            'UNCERTAINTY_STYLE 只能设为 "band"、"errorbar" 或 "none"。'
        )

    info = METRICS[metric]

    for index, source_name in enumerate(source_names):
        source_data = data[data["source_name"] == source_name]
        source_stats = statistics[
            (statistics["source_name"] == source_name)
            & (statistics["metric"] == metric)
        ].sort_values("pressure_Pa")

        add_raw_points(
            ax,
            source_data,
            metric,
            colors[source_name],
            random_seed=2026 + index,
        )

        x = source_stats["pressure_Pa"].to_numpy(dtype=float)
        mean = source_stats["mean"].to_numpy(dtype=float)
        error = source_stats[ERROR_MODE].to_numpy(dtype=float)

        # 推荐模式：半透明置信带。它比多组竖直误差棒更容易辨认曲线趋势。
        if UNCERTAINTY_STYLE == "band":
            lower = np.maximum(mean - error, 0)
            upper = mean + error
            ax.fill_between(
                x,
                lower,
                upper,
                color=colors[source_name],
                alpha=BAND_ALPHA,
                linewidth=0,
                zorder=1,
            )

        if UNCERTAINTY_STYLE == "errorbar":
            ax.errorbar(
                x,
                mean,
                yerr=error,
                fmt=markers[source_name],
                linestyle=line_styles[source_name],
                color=colors[source_name],
                ecolor=colors[source_name],
                markersize=MARKER_SIZE,
                linewidth=LINE_WIDTH,
                elinewidth=0.95,
                capsize=ERROR_CAP_SIZE,
                capthick=0.95,
                markerfacecolor="white",
                markeredgewidth=1.25,
                zorder=3,
            )
        else:
            # band 和 none 模式均绘制清晰的中心均值曲线
            ax.plot(
                x,
                mean,
                marker=markers[source_name],
                linestyle=line_styles[source_name],
                color=colors[source_name],
                markersize=MARKER_SIZE,
                linewidth=LINE_WIDTH,
                markerfacecolor="white",
                markeredgewidth=1.25,
                zorder=3,
            )

    configure_axis(ax)
    # 根据 METRICS 中的设置，分别控制左右两个子图的纵坐标范围
    ax.set_ylim(*info["ylim"])
    ax.set_ylabel(info["ylabel"])
    if info["title"]:
        ax.set_title(info["title"], pad=8)
    if show_panel_label:
        ax.text(
            0.025,
            0.965,
            info["panel"],
            transform=ax.transAxes,
            ha="left",
            va="top",
            fontsize=12,
            fontweight="bold",
        )


def create_legend_handles(
    source_names: list[str],
    colors: dict,
    markers: dict,
    line_styles: dict,
) -> list[Line2D]:
    """建立以文件名为标签的统一图例。"""
    return [
        Line2D(
            [0],
            [0],
            color=colors[name],
            marker=markers[name],
            linestyle=line_styles[name],
            linewidth=LINE_WIDTH,
            markersize=MARKER_SIZE,
            markerfacecolor="white",
            markeredgewidth=1.25,
            label=name,
        )
        for name in source_names
    ]


def save_combined_figure(
    data: pd.DataFrame,
    statistics: pd.DataFrame,
    source_names: list[str],
    colors: dict,
    markers: dict,
    line_styles: dict,
) -> Path:
    """保存两面板、多文件对比组图。"""
    fig, axes = plt.subplots(1, 2, figsize=COMBINED_FIGURE_SIZE)

    for ax, metric in zip(axes, METRICS):
        draw_metric(
            ax,
            data,
            statistics,
            metric,
            source_names,
            colors,
            markers,
            line_styles,
            show_panel_label=True,
        )

    handles = create_legend_handles(source_names, colors, markers, line_styles)
    columns = LEGEND_COLUMNS or min(4, len(source_names))
    fig.legend(
        handles=handles,
        loc="upper center",
        bbox_to_anchor=(0.5, 1.00),
        ncol=columns,
        frameon=False,
        columnspacing=2.0,
        handlelength=3.5,
        handletextpad=0.7,
    )
    # 顶部留出空间放置整张组图共用的图例
    fig.tight_layout(rect=(0, 0, 1, 0.90), w_pad=2.0)

    output_path = OUTPUT_DIR / "multi_file_jump_metrics_comparison.png"
    fig.savefig(output_path, dpi=DPI, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return output_path


def save_individual_figures(
    data: pd.DataFrame,
    statistics: pd.DataFrame,
    source_names: list[str],
    colors: dict,
    markers: dict,
    line_styles: dict,
) -> list[Path]:
    """可选：分别保存起跳高度图和水平位移图。"""
    output_paths = []
    handles = create_legend_handles(source_names, colors, markers, line_styles)

    for metric, info in METRICS.items():
        fig, ax = plt.subplots(figsize=INDIVIDUAL_FIGURE_SIZE)
        draw_metric(
            ax,
            data,
            statistics,
            metric,
            source_names,
            colors,
            markers,
            line_styles,
            show_panel_label=False,
        )
        ax.legend(handles=handles, frameon=False, loc="best")
        fig.tight_layout()
        output_path = OUTPUT_DIR / info["filename"]
        fig.savefig(output_path, dpi=DPI, bbox_inches="tight", facecolor="white")
        plt.close(fig)
        output_paths.append(output_path)

    return output_paths


def main() -> None:
    """程序入口。"""
    plt.rcParams.update(
        {
            "font.family": choose_roman_font(),
            "font.size": 10,
            "axes.labelsize": 11,
            "xtick.labelsize": 9.5,
            "ytick.labelsize": 9.5,
            "axes.linewidth": 1.0,
            "xtick.direction": "in",
            "ytick.direction": "in",
            "xtick.top": True,
            "ytick.right": True,
        }
    )

    data_folder = resolve_data_folder()
    print(f"数据目录：{data_folder.resolve()}")
    data, source_names = load_all_files(data_folder)
    statistics = calculate_statistics(data)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    statistics_path = OUTPUT_DIR / "multi_file_jump_metrics_statistics.csv"
    statistics.to_csv(
        statistics_path,
        index=False,
        encoding="utf-8-sig",
        float_format="%.6f",
    )

    colors, markers, line_styles = make_style_maps(source_names)
    combined_path = save_combined_figure(
        data,
        statistics,
        source_names,
        colors,
        markers,
        line_styles,
    )

    output_paths = [combined_path, statistics_path]
    if SAVE_INDIVIDUAL_FIGURES:
        output_paths.extend(
            save_individual_figures(
                data,
                statistics,
                source_names,
                colors,
                markers,
                line_styles,
            )
        )

    print(f"\n成功读取 {len(source_names)} 个数据文件，共 {len(data)} 条有效数据。")
    print(f"统计单位：{AGGREGATION_LEVEL}")
    print(f"不确定性：{ERROR_MODE.upper()}，显示形式：{UNCERTAINTY_STYLE}")
    print("图例名称：" + "；".join(source_names))
    print("\n输出文件：")
    for path in output_paths:
        print(path.resolve())


if __name__ == "__main__":
    main()
