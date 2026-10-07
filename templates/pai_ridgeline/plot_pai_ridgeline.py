#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
四组颗粒PAI二维错层岭线图。

推荐的真实数据目录结构：

input_pai_groups/
├─ P1/
│  ├─ 500pa.csv
│  ├─ 1000pa.csv
│  └─ ...
├─ P2/
│  └─ ...
├─ P3/
│  └─ ...
└─ P4/
   └─ ...

每个CSV至少包含：
    time_ms_based_on_capture_fps
    particle_activity_index

将 DEMO_MODE 改为 False 后，程序会读取上述四个真实数据文件夹。
"""

from pathlib import Path
import os
import re
import tempfile

_mpl_cache = Path(tempfile.gettempdir()) / "four_group_pai_ridge_cache"
_mpl_cache.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(_mpl_cache))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.colors import LogNorm
from matplotlib.cm import ScalarMappable
import numpy as np
import pandas as pd


# ========================== 用户参数区 ==========================
SCRIPT_DIR = Path(__file__).resolve().parent

# True：使用当前一组数据生成四组版式示意图；P2–P4为模拟数据。
# False：读取 DATA_ROOT 下P1、P2、P3、P4四个真实数据文件夹。
DEMO_MODE = False

DATA_ROOT = SCRIPT_DIR / "input_pai_groups"
GROUP_NAMES = ("P1", "P2", "P3", "P4")

OUTPUT_DIR = SCRIPT_DIR / "four_group_pai_results"
OUTPUT_NAME = "four_group_pai_ridgeline_schematic.png"

# 统一时间范围与处理参数
TIME_MIN_S = 0.0
TIME_MAX_S = 10.0
SMOOTH_WINDOW_MS = 100.0
RESAMPLE_INTERVAL_MS = 25.0

# "log"推荐用于PAI跨越多个数量级的情况；"linear"直接显示PAI
PAI_DISPLAY_MODE = "linear"

# 全部子图必须共用同一高度比例，才能比较不同颗粒组的绝对强弱
USE_SHARED_GLOBAL_SCALE = False

# 图形参数
DPI = 600
FIGURE_SIZE = (13.0, 9.0)
PRESSURE_CMAP = "viridis"
RIDGE_HEIGHT = 0.72
FILL_ALPHA = 0.20
LINE_WIDTH = 1.15

# 是否显示右侧共享压强色标
SHOW_PRESSURE_COLORBAR = True
# ==============================================================


TIME_COLUMN = "time_ms_based_on_capture_fps"
PAI_COLUMN = "particle_activity_index"


def choose_roman_font() -> str:
    """优先使用Times New Roman。"""
    installed = {item.name for item in font_manager.fontManager.ttflist}
    for name in ("Times New Roman", "Nimbus Roman", "Liberation Serif", "DejaVu Serif"):
        if name in installed:
            return name
    return "serif"


def pressure_from_filename(path: Path) -> float | None:
    """从500pa.csv一类文件名中提取压强。"""
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*pa", path.stem, flags=re.IGNORECASE)
    return float(match.group(1)) if match else None


def find_pressure_files(folder: Path) -> list[tuple[float, Path]]:
    """查找并按压强从小到大排列。"""
    result = []
    if not folder.is_dir():
        return result
    for path in folder.glob("*.csv"):
        pressure = pressure_from_filename(path)
        if pressure is not None:
            result.append((pressure, path))
    return sorted(result, key=lambda item: item[0])


def display_transform(values: np.ndarray) -> np.ndarray:
    """将PAI转换为绘图高度。"""
    values = np.maximum(np.asarray(values, dtype=float), 0.0)
    if PAI_DISPLAY_MODE == "log":
        return np.log10(1.0 + values)
    if PAI_DISPLAY_MODE == "linear":
        return values
    raise ValueError('PAI_DISPLAY_MODE只能是"log"或"linear"。')


def pressure_label(pressure_pa: float) -> str:
    """压强标签。"""
    if pressure_pa >= 1000:
        return f"{pressure_pa / 1000:g} kPa"
    return f"{pressure_pa:g} Pa"


def make_time_grid() -> np.ndarray:
    """建立四组数据共用的时间网格。"""
    dt = RESAMPLE_INTERVAL_MS / 1000.0
    return np.arange(TIME_MIN_S, TIME_MAX_S + dt * 0.5, dt)


def read_one_curve(path: Path, time_grid: np.ndarray) -> np.ndarray:
    """读取、平滑并插值一条PAI曲线。"""
    table = pd.read_csv(path, encoding="utf-8-sig")
    missing = [column for column in (TIME_COLUMN, PAI_COLUMN) if column not in table]
    if missing:
        raise KeyError(f"{path.name}缺少列：{missing}")

    time_s = pd.to_numeric(table[TIME_COLUMN], errors="coerce") / 1000.0
    pai = pd.to_numeric(table[PAI_COLUMN], errors="coerce")
    valid = time_s.notna() & pai.notna() & (pai >= 0)
    data = pd.DataFrame({"time_s": time_s[valid], "pai": pai[valid]}).sort_values("time_s")
    data = data[(data["time_s"] >= TIME_MIN_S) & (data["time_s"] <= TIME_MAX_S)]
    if len(data) < 2:
        raise ValueError(f"{path.name}在指定时间范围内数据不足")

    dt_ms = float(np.median(np.diff(data["time_s"].to_numpy())) * 1000.0)
    smooth_points = max(1, int(round(SMOOTH_WINDOW_MS / dt_ms)))
    smoothed = data["pai"].rolling(
        window=smooth_points,
        center=True,
        min_periods=1,
    ).mean()
    return np.interp(time_grid, data["time_s"].to_numpy(), smoothed.to_numpy())


def load_group(folder: Path, time_grid: np.ndarray) -> dict[float, np.ndarray]:
    """读取一个颗粒组下的全部压强文件。"""
    curves = {}
    for pressure, path in find_pressure_files(folder):
        curves[pressure] = read_one_curve(path, time_grid)
    if not curves:
        raise FileNotFoundError(f"{folder}中没有有效的压强CSV文件")
    return curves


def find_demo_folder() -> Path:
    """在当前环境中定位已有的一组PAI数据。"""
    candidates = [SCRIPT_DIR / "input_pai", SCRIPT_DIR, SCRIPT_DIR / "upload"]
    for folder in candidates:
        if find_pressure_files(folder):
            return folder
    raise FileNotFoundError("没有找到用于生成示意图的PAI CSV文件。")


def shift_curve(curve: np.ndarray, shift_points: int) -> np.ndarray:
    """平移曲线，用于生成版式示意数据。"""
    if shift_points == 0:
        return curve.copy()
    shifted = np.roll(curve, shift_points)
    if shift_points > 0:
        shifted[:shift_points] = 0.0
    else:
        shifted[shift_points:] = 0.0
    return shifted


def build_demo_groups(base: dict[float, np.ndarray]) -> dict[str, dict[float, np.ndarray]]:
    """
    由现有一组数据生成P2–P4示意数据。
    这些变换只用于展示四面板的视觉效果，不代表真实实验结果。
    """
    groups: dict[str, dict[float, np.ndarray]] = {"P1": {p: y.copy() for p, y in base.items()}}
    transformations = {
        "P2": (0.78, 4),
        "P3": (0.52, -3),
        "P4": (1.10, 7),
    }

    for group_name, (scale, shift) in transformations.items():
        group_curves = {}
        for index, (pressure, curve) in enumerate(sorted(base.items())):
            # 加入轻微、平滑且可重复的幅值变化，使四个面板便于视觉比较
            pressure_factor = 1.0 + 0.08 * np.sin(index * 0.85 + len(group_name))
            transformed = shift_curve(curve, shift) * scale * pressure_factor
            group_curves[pressure] = np.maximum(transformed, 0.0)
        groups[group_name] = group_curves
    return groups


def load_all_groups(time_grid: np.ndarray) -> dict[str, dict[float, np.ndarray]]:
    """根据DEMO_MODE读取示意数据或四组真实数据。"""
    if DEMO_MODE:
        base_folder = find_demo_folder()
        print(f"示意图基础数据：{base_folder.resolve()}")
        return build_demo_groups(load_group(base_folder, time_grid))

    groups = {}
    for group_name in GROUP_NAMES:
        folder = DATA_ROOT / group_name
        groups[group_name] = load_group(folder, time_grid)
        print(f"已读取 {group_name}: {folder.resolve()}")
    return groups


def get_all_pressures(groups: dict[str, dict[float, np.ndarray]]) -> np.ndarray:
    """获取四组数据中出现过的所有压强。"""
    pressures = sorted({pressure for curves in groups.values() for pressure in curves})
    return np.asarray(pressures, dtype=float)


def compute_scale_max(groups: dict[str, dict[float, np.ndarray]]) -> float:
    """计算全部子图共用的PAI高度上限。"""
    maxima = [
        float(np.nanmax(display_transform(curve)))
        for curves in groups.values()
        for curve in curves.values()
    ]
    return max(max(maxima), 1e-12)


def plot_one_panel(
    ax: plt.Axes,
    time_grid: np.ndarray,
    curves: dict[float, np.ndarray],
    pressures: np.ndarray,
    color_norm: LogNorm,
    global_max: float,
    group_name: str,
    panel_label: str,
) -> None:
    """绘制一个颗粒组的岭线面板。"""
    cmap = plt.get_cmap(PRESSURE_CMAP)
    positions = np.arange(len(pressures), dtype=float)

    if USE_SHARED_GLOBAL_SCALE:
        panel_max = global_max
    else:
        panel_values = [display_transform(curve) for curve in curves.values()]
        panel_max = max(float(np.nanmax(values)) for values in panel_values)

    for position, pressure in zip(positions, pressures):
        baseline = np.full_like(time_grid, position)
        ax.axhline(position, color="#D7D7D7", linewidth=0.45, zorder=0)
        if pressure not in curves:
            continue

        height = display_transform(curves[pressure]) / max(panel_max, 1e-12) * RIDGE_HEIGHT
        color = cmap(color_norm(pressure))
        ax.fill_between(
            time_grid,
            baseline,
            baseline + height,
            color=color,
            alpha=FILL_ALPHA,
            linewidth=0,
            zorder=1,
        )
        ax.plot(
            time_grid,
            baseline + height,
            color=color,
            linewidth=LINE_WIDTH,
            zorder=2,
        )

    ax.set_xlim(TIME_MIN_S, TIME_MAX_S)
    ax.set_ylim(-0.12, len(pressures) - 1 + 0.86)
    ax.set_yticks(positions)
    ax.set_yticklabels([pressure_label(value) for value in pressures])
    ax.grid(False)
    ax.text(
        0.025,
        0.965,
        f"{panel_label}  {group_name}",
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=11.5,
        fontweight="bold",
    )


def create_figure(
    time_grid: np.ndarray,
    groups: dict[str, dict[float, np.ndarray]],
) -> Path:
    """绘制2×2四组颗粒岭线图。"""
    pressures = get_all_pressures(groups)
    global_max = compute_scale_max(groups)
    color_norm = LogNorm(vmin=float(pressures.min()), vmax=float(pressures.max()))

    fig, axes = plt.subplots(
        2,
        2,
        figsize=FIGURE_SIZE,
        sharex=True,
        sharey=True,
    )
    panel_labels = ("(a)", "(b)", "(c)", "(d)")

    for ax, group_name, panel_label in zip(axes.flat, GROUP_NAMES, panel_labels):
        plot_one_panel(
            ax,
            time_grid,
            groups[group_name],
            pressures,
            color_norm,
            global_max,
            group_name,
            panel_label,
        )

    # 左列显示压强标签；下排显示时间标签
    axes[0, 0].set_ylabel("Pressure")
    axes[1, 0].set_ylabel("Pressure")
    axes[1, 0].set_xlabel("Time (s)")
    axes[1, 1].set_xlabel("Time (s)")
    axes[0, 1].tick_params(labelleft=False)
    axes[1, 1].tick_params(labelleft=False)

    # 说明四个面板共用同一PAI高度比例
    scale_text = (
        r" "
        if PAI_DISPLAY_MODE == "log"
        else " "
    )
    fig.text(0.50, 0.018, scale_text, ha="center", va="bottom", fontsize=9.5)

    if DEMO_MODE:
        fig.text(
            0.50,
            0.988,
            "Layout demonstration — P2–P4 are synthetic",
            ha="center",
            va="top",
            fontsize=10,
        )

    fig.subplots_adjust(
        left=0.105,
        right=0.875 if SHOW_PRESSURE_COLORBAR else 0.97,
        bottom=0.085,
        top=0.945,
        wspace=0.10,
        hspace=0.12,
    )

    if SHOW_PRESSURE_COLORBAR:
        scalar = ScalarMappable(norm=color_norm, cmap=plt.get_cmap(PRESSURE_CMAP))
        scalar.set_array([])
        # 使用独立色标坐标轴，避免色标覆盖右侧两个子图
        colorbar_axis = fig.add_axes([0.905, 0.23, 0.018, 0.56])
        colorbar = fig.colorbar(scalar, cax=colorbar_axis)
        colorbar.set_label("Pressure")
        colorbar_ticks = np.asarray(
            [500, 1000, 2000, 5000, 10000, 20000, 50000, 100000],
            dtype=float,
        )
        colorbar_ticks = colorbar_ticks[
            (colorbar_ticks >= pressures.min()) & (colorbar_ticks <= pressures.max())
        ]
        colorbar.set_ticks(colorbar_ticks)
        colorbar.set_ticklabels([pressure_label(value) for value in colorbar_ticks])

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / OUTPUT_NAME
    fig.savefig(output_path, dpi=DPI, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return output_path


def main() -> None:
    """程序入口。"""
    plt.rcParams.update(
        {
            "font.family": choose_roman_font(),
            "font.size": 9.5,
            "axes.labelsize": 10.5,
            "xtick.labelsize": 8.5,
            "ytick.labelsize": 8.5,
            "axes.linewidth": 0.9,
            "xtick.direction": "in",
            "ytick.direction": "in",
            "xtick.top": True,
            "ytick.right": True,
        }
    )

    time_grid = make_time_grid()
    groups = load_all_groups(time_grid)
    output = create_figure(time_grid, groups)
    print(f"图像已保存：{output.resolve()}")
    if DEMO_MODE:
        print("注意：P2–P4仅为版式示意数据，不代表真实实验结果。")


if __name__ == "__main__":
    main()
