#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""COMSOL 颗粒轨迹数据科研绘图程序。

功能
----
1. 读取此前生成的 Data_Long 格式 Excel 数据集；
2. 按“压力–粒子”独立还原 x=0–3 mm 周期边界下的连续 qx；
3. 到达左右各扩展 5 个周期的边界后冻结 qx；
4. 计算逐粒子轨迹、速度、荷电和跨界统计量；
5. 批量输出 600 dpi PNG 与矢量 PDF 科研图。

直接运行
--------
python plot_comsol_particle_dataset.py combined_COMSOL_particle_dataset.xlsx

不带文件参数运行时会弹出文件选择窗口。
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

# Matplotlib 缓存必须指向可写目录；应在导入 matplotlib 前设置。
os.environ.setdefault(
    "MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "comsol_particle_plot_mpl_cache")
)

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import LogNorm
from matplotlib.lines import Line2D
from matplotlib.ticker import AutoMinorLocator, ScalarFormatter


REQUIRED_COLUMN_ORDER = [
    "Particle_Index",
    "Pm",
    "Time_s",
    "qx_m",
    "qy_m",
    "Velocity_m_per_s",
    "Charge_Number_Z",
]
REQUIRED_COLUMNS = set(REQUIRED_COLUMN_ORDER)


@dataclass
class PlotConfig:
    sheet_name: str = "Data_Long"
    left_boundary_mm: float = 0.0
    right_boundary_mm: float = 3.0
    expansion_periods: int = 5
    crossing_threshold_fraction: float = 0.5
    relative_y_for_trajectory: bool = True
    dpi: int = 600
    export_png: bool = True
    export_pdf: bool = True

    @property
    def period_mm(self) -> float:
        return self.right_boundary_mm - self.left_boundary_mm

    @property
    def lower_limit_mm(self) -> float:
        return self.left_boundary_mm - self.expansion_periods * self.period_mm

    @property
    def upper_limit_mm(self) -> float:
        return self.right_boundary_mm + self.expansion_periods * self.period_mm

    @property
    def crossing_threshold_mm(self) -> float:
        return self.period_mm * self.crossing_threshold_fraction


def choose_excel_file() -> Path | None:
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        selected = filedialog.askopenfilename(
            title="选择合并后的 COMSOL Excel 数据集",
            filetypes=[("Excel files", "*.xlsx"), ("All files", "*.*")],
        )
        root.destroy()
        return Path(selected) if selected else None
    except Exception:
        return None


def configure_matplotlib() -> None:
    plt.rcParams.update(
        {
            "font.family": "serif",
            "font.serif": ["Times New Roman", "Times", "DejaVu Serif"],
            "font.size": 8.5,
            "axes.labelsize": 9,
            "axes.titlesize": 9,
            "xtick.labelsize": 7.5,
            "ytick.labelsize": 7.5,
            "legend.fontsize": 7,
            "axes.linewidth": 0.8,
            "xtick.direction": "in",
            "ytick.direction": "in",
            "xtick.top": True,
            "ytick.right": True,
            "xtick.major.width": 0.8,
            "ytick.major.width": 0.8,
            "xtick.minor.width": 0.6,
            "ytick.minor.width": 0.6,
            "lines.linewidth": 1.0,
            "savefig.bbox": "tight",
            "savefig.pad_inches": 0.04,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )


def pressure_label(pressure_pa: float) -> str:
    if pressure_pa < 1000:
        return f"{pressure_pa:g} Pa"
    return f"{pressure_pa / 1000:g} kPa"


def load_dataset(path: Path, sheet_name: str) -> pd.DataFrame:
    if not path.is_file():
        raise FileNotFoundError(f"文件不存在：{path}")

    data = pd.read_excel(path, sheet_name=sheet_name, engine="openpyxl")
    missing = REQUIRED_COLUMNS.difference(data.columns)
    if missing:
        raise ValueError(f"缺少必要列：{', '.join(sorted(missing))}")

    data = data[REQUIRED_COLUMN_ORDER].copy()
    for column in REQUIRED_COLUMN_ORDER:
        data[column] = pd.to_numeric(data[column], errors="coerce")

    invalid = data[REQUIRED_COLUMN_ORDER].isna().any(axis=1)
    if invalid.any():
        rows = (np.flatnonzero(invalid.to_numpy()) + 2)[:10]
        raise ValueError(f"存在无效或缺失数值，Excel 行号示例：{rows.tolist()}")

    data["Particle_Index"] = data["Particle_Index"].astype(int)
    data = data.sort_values(["Pm", "Particle_Index", "Time_s"]).reset_index(drop=True)

    duplicated = data.duplicated(["Pm", "Particle_Index", "Time_s"])
    if duplicated.any():
        raise ValueError(f"存在 {int(duplicated.sum())} 条重复的压力–粒子–时间记录。")
    return data


def unwrap_periodic_trajectories(
    data: pd.DataFrame, config: PlotConfig
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if config.period_mm <= 0:
        raise ValueError("右周期边界必须大于左周期边界。")
    if not 0 < config.crossing_threshold_fraction <= 1:
        raise ValueError("跨界阈值比例必须位于 (0, 1]。")

    result_parts: list[pd.DataFrame] = []
    diagnostic_rows: list[dict] = []

    for (pressure, particle), group in data.groupby(
        ["Pm", "Particle_Index"], sort=True
    ):
        group = group.sort_values("Time_s").copy()
        raw_x_mm = group["qx_m"].to_numpy(dtype=float) * 1000.0
        raw_delta_mm = np.diff(raw_x_mm)

        step_change = np.zeros(len(group), dtype=int)
        step_change[1:][raw_delta_mm < -config.crossing_threshold_mm] = 1
        step_change[1:][raw_delta_mm > config.crossing_threshold_mm] = -1
        shift_count = np.cumsum(step_change)
        unwrapped_x_mm = raw_x_mm + shift_count * config.period_mm

        event = np.full(len(group), "", dtype=object)
        right_indices = np.flatnonzero(raw_delta_mm < -config.crossing_threshold_mm) + 1
        left_indices = np.flatnonzero(raw_delta_mm > config.crossing_threshold_mm) + 1
        event[right_indices] = "Right_crossing_3_to_0"
        event[left_indices] = "Left_crossing_0_to_3"

        frozen = np.zeros(len(group), dtype=bool)
        frozen_boundary = np.full(len(group), np.nan)
        limit_indices = np.flatnonzero(
            (unwrapped_x_mm <= config.lower_limit_mm)
            | (unwrapped_x_mm >= config.upper_limit_mm)
        )
        freeze_time_s = np.nan
        if limit_indices.size:
            first = int(limit_indices[0])
            boundary = (
                config.lower_limit_mm
                if unwrapped_x_mm[first] <= config.lower_limit_mm
                else config.upper_limit_mm
            )
            unwrapped_x_mm[first:] = boundary
            frozen[first:] = True
            frozen_boundary[first:] = boundary
            freeze_time_s = float(group["Time_s"].iloc[first])
            suffix = "Freeze_left" if boundary == config.lower_limit_mm else "Freeze_right"
            event[first] = f"{event[first]};{suffix}" if event[first] else suffix
            event[first + 1 :] = "Frozen"

        qy_mm = group["qy_m"].to_numpy(dtype=float) * 1000.0
        group["qx_raw_mm"] = raw_x_mm
        group["qx_unwrapped_mm"] = unwrapped_x_mm
        group["qy_mm"] = qy_mm
        group["dx_mm"] = unwrapped_x_mm - unwrapped_x_mm[0]
        group["dy_mm"] = qy_mm - qy_mm[0]
        group["Period_Shift_Count"] = shift_count
        group["Boundary_Event"] = event
        group["Frozen_At_Limit"] = frozen
        group["Frozen_Boundary_mm"] = frozen_boundary
        result_parts.append(group)

        corrected_step = np.abs(np.diff(unwrapped_x_mm))
        diagnostic_rows.append(
            {
                "Pm": pressure,
                "Particle_Index": particle,
                "Records": len(group),
                "Boundary_Crossings": int(np.count_nonzero(step_change)),
                "Final_Shift_Count": int(shift_count[-1]),
                "Maximum_Corrected_Step_mm": (
                    float(np.max(corrected_step)) if corrected_step.size else 0.0
                ),
                "Frozen": bool(frozen.any()),
                "Freeze_Time_s": freeze_time_s,
            }
        )

    processed = pd.concat(result_parts, ignore_index=True)
    diagnostics = pd.DataFrame(diagnostic_rows)
    return processed, diagnostics


def calculate_particle_metrics(
    processed: pd.DataFrame, diagnostics: pd.DataFrame
) -> pd.DataFrame:
    metrics = []
    diagnostic_lookup = diagnostics.set_index(["Pm", "Particle_Index"])

    for (pressure, particle), group in processed.groupby(
        ["Pm", "Particle_Index"], sort=True
    ):
        group = group.sort_values("Time_s")
        x = group["qx_unwrapped_mm"].to_numpy(dtype=float)
        y = group["qy_mm"].to_numpy(dtype=float)
        speed = group["Velocity_m_per_s"].to_numpy(dtype=float)
        charge = group["Charge_Number_Z"].to_numpy(dtype=float)
        path_length = float(np.sum(np.hypot(np.diff(x), np.diff(y))))
        diag = diagnostic_lookup.loc[(pressure, particle)]

        metrics.append(
            {
                "Pm": pressure,
                "Particle_Index": particle,
                "Initial_qx_mm": x[0],
                "Final_qx_mm": x[-1],
                "Net_horizontal_displacement_mm": x[-1] - x[0],
                "Horizontal_range_mm": np.max(x) - np.min(x),
                "Maximum_absolute_horizontal_displacement_mm": np.max(
                    np.abs(x - x[0])
                ),
                "Initial_qy_mm": y[0],
                "Maximum_vertical_rise_mm": np.max(y - y[0]),
                "Vertical_range_mm": np.max(y) - np.min(y),
                "Path_length_mm": path_length,
                "Mean_speed_m_per_s": np.mean(speed),
                "Peak_speed_m_per_s": np.max(speed),
                "Initial_charge_number_Z": charge[0],
                "Final_charge_number_Z": charge[-1],
                "Maximum_absolute_charge_number_Z": np.max(np.abs(charge)),
                "Charge_change_Z": charge[-1] - charge[0],
                "Boundary_crossings": int(diag["Boundary_Crossings"]),
                "Final_shift_count": int(diag["Final_Shift_Count"]),
                "Frozen": bool(diag["Frozen"]),
            }
        )
    return pd.DataFrame(metrics)


def add_panel_label(ax: plt.Axes, label: str) -> None:
    ax.text(
        0.02,
        0.96,
        label,
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontweight="bold",
        fontsize=9,
    )


def polish_axis(ax: plt.Axes, minor_x: bool = True, minor_y: bool = True) -> None:
    if minor_x:
        ax.xaxis.set_minor_locator(AutoMinorLocator())
    if minor_y:
        ax.yaxis.set_minor_locator(AutoMinorLocator())
    ax.tick_params(which="major", length=3.5)
    ax.tick_params(which="minor", length=2.0)


def save_figure(fig: plt.Figure, output_dir: Path, stem: str, config: PlotConfig) -> None:
    if config.export_png:
        fig.savefig(output_dir / f"{stem}.png", dpi=config.dpi, facecolor="white")
    if config.export_pdf:
        fig.savefig(output_dir / f"{stem}.pdf", facecolor="white")
    plt.close(fig)


def subplot_grid(pressures: list[float]):
    columns = 4 if len(pressures) > 4 else len(pressures)
    rows = int(math.ceil(len(pressures) / columns))
    fig, axes = plt.subplots(
        rows,
        columns,
        figsize=(7.2, 2.35 * rows),
        squeeze=False,
    )
    return fig, axes.ravel()


def plot_unwrapping_example(
    processed: pd.DataFrame,
    metrics: pd.DataFrame,
    output_dir: Path,
    config: PlotConfig,
) -> None:
    example = metrics.sort_values("Boundary_crossings", ascending=False).iloc[0]
    group = processed[
        (processed["Pm"] == example["Pm"])
        & (processed["Particle_Index"] == example["Particle_Index"])
    ].sort_values("Time_s")

    fig, ax = plt.subplots(figsize=(5.2, 2.8), constrained_layout=True)
    ax.plot(group["Time_s"], group["qx_raw_mm"], color="#9E9E9E", label="Raw periodic qx")
    ax.plot(
        group["Time_s"],
        group["qx_unwrapped_mm"],
        color="#006D77",
        label="Unwrapped qx",
    )
    crossing = group["Boundary_Event"].str.contains("crossing", case=False, na=False)
    crossing_indices = np.flatnonzero(crossing.to_numpy())
    # 跨界可能十分频繁，仅显示最多约 60 个标记以避免遮盖曲线。
    if crossing_indices.size > 60:
        crossing_indices = crossing_indices[:: int(math.ceil(crossing_indices.size / 60))]
    ax.scatter(
        group.iloc[crossing_indices]["Time_s"],
        group.iloc[crossing_indices]["qx_unwrapped_mm"],
        s=12,
        facecolors="white",
        edgecolors="#C43C39",
        linewidths=0.7,
        label="Detected crossing",
        zorder=3,
    )
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Horizontal position, qx (mm)")
    ax.set_title(
        f"Periodic-coordinate unwrapping: {pressure_label(example['Pm'])}, "
        f"particle {int(example['Particle_Index'])}"
    )
    ax.legend(frameon=False, ncol=3, loc="upper center")
    polish_axis(ax)
    save_figure(fig, output_dir, "Fig01_periodic_unwrapping_example", config)


def plot_xy_trajectories(
    processed: pd.DataFrame, output_dir: Path, config: PlotConfig
) -> None:
    pressures = sorted(processed["Pm"].unique())
    particles = sorted(processed["Particle_Index"].unique())
    colors = plt.get_cmap("tab10")(np.linspace(0, 0.8, len(particles)))
    fig, axes = subplot_grid(pressures)

    y_column = "dy_mm" if config.relative_y_for_trajectory else "qy_mm"
    y_label = "Vertical displacement, Δy (mm)" if config.relative_y_for_trajectory else "Vertical position, qy (mm)"
    global_y_min = float(processed[y_column].min())
    global_y_max = float(processed[y_column].max())
    global_y_span = max(global_y_max - global_y_min, 1e-9)
    common_y_limits = (
        global_y_min - 0.04 * global_y_span,
        global_y_max + 0.06 * global_y_span,
    )

    for panel_index, (ax, pressure) in enumerate(zip(axes, pressures)):
        pressure_data = processed[processed["Pm"] == pressure]
        for color, particle in zip(colors, particles):
            group = pressure_data[pressure_data["Particle_Index"] == particle]
            ax.plot(group["qx_unwrapped_mm"], group[y_column], color=color, alpha=0.9)
            ax.scatter(group["qx_unwrapped_mm"].iloc[0], group[y_column].iloc[0], s=9, color=color, marker="o", zorder=3)
            ax.scatter(group["qx_unwrapped_mm"].iloc[-1], group[y_column].iloc[-1], s=10, color=color, marker="s", zorder=3)
        ax.set_title(pressure_label(pressure))
        ax.set_ylim(*common_y_limits)
        add_panel_label(ax, f"({chr(97 + panel_index)})")
        polish_axis(ax)

    for ax in axes[len(pressures) :]:
        ax.set_visible(False)
    fig.supxlabel("Unwrapped horizontal position, qx (mm)")
    fig.supylabel(y_label)
    handles = [Line2D([0], [0], color=c, label=f"Particle {p}") for c, p in zip(colors, particles)]
    handles += [
        Line2D([0], [0], marker="o", color="black", linestyle="None", markersize=4, label="Start"),
        Line2D([0], [0], marker="s", color="black", linestyle="None", markersize=4, label="End"),
    ]
    fig.legend(
        handles=handles,
        loc="upper center",
        bbox_to_anchor=(0.5, 0.995),
        ncol=9,
        frameon=False,
    )
    fig.subplots_adjust(left=0.09, right=0.99, bottom=0.11, top=0.84, wspace=0.25, hspace=0.38)
    save_figure(fig, output_dir, "Fig02_particle_trajectories_xy", config)


def plot_time_grid(
    processed: pd.DataFrame,
    value_column: str,
    ylabel: str,
    filename: str,
    output_dir: Path,
    config: PlotConfig,
) -> None:
    pressures = sorted(processed["Pm"].unique())
    particles = sorted(processed["Particle_Index"].unique())
    colors = plt.get_cmap("tab10")(np.linspace(0, 0.8, len(particles)))
    fig, axes = subplot_grid(pressures)
    global_y_min = float(processed[value_column].min())
    global_y_max = float(processed[value_column].max())
    global_y_span = max(global_y_max - global_y_min, 1e-9)
    common_y_limits = (
        global_y_min - 0.04 * global_y_span,
        global_y_max + 0.06 * global_y_span,
    )

    for panel_index, (ax, pressure) in enumerate(zip(axes, pressures)):
        pressure_data = processed[processed["Pm"] == pressure]
        for color, particle in zip(colors, particles):
            group = pressure_data[pressure_data["Particle_Index"] == particle]
            ax.plot(group["Time_s"], group[value_column], color=color, alpha=0.9)
        ax.axhline(0, color="#666666", linewidth=0.6, linestyle="--", zorder=0)
        ax.set_ylim(*common_y_limits)
        ax.set_title(pressure_label(pressure))
        add_panel_label(ax, f"({chr(97 + panel_index)})")
        polish_axis(ax)

    for ax in axes[len(pressures) :]:
        ax.set_visible(False)
    fig.supxlabel("Time (s)")
    fig.supylabel(ylabel)
    handles = [Line2D([0], [0], color=c, label=f"Particle {p}") for c, p in zip(colors, particles)]
    fig.legend(
        handles=handles,
        loc="upper center",
        bbox_to_anchor=(0.5, 0.995),
        ncol=7,
        frameon=False,
    )
    fig.subplots_adjust(left=0.09, right=0.99, bottom=0.11, top=0.84, wspace=0.25, hspace=0.38)
    save_figure(fig, output_dir, filename, config)


def ensemble_mean_std(group: pd.DataFrame, value_column: str):
    pivot = group.pivot(index="Time_s", columns="Particle_Index", values=value_column)
    return pivot.index.to_numpy(), pivot.mean(axis=1).to_numpy(), pivot.std(axis=1, ddof=1).fillna(0).to_numpy()


def plot_ensemble_time_response(
    processed: pd.DataFrame, output_dir: Path, config: PlotConfig
) -> None:
    pressures = sorted(processed["Pm"].unique())
    norm = LogNorm(vmin=min(pressures), vmax=max(pressures))
    cmap = plt.get_cmap("viridis")
    panels = [
        ("dx_mm", "Horizontal displacement, Δx (mm)"),
        ("dy_mm", "Vertical displacement, Δy (mm)"),
        ("Velocity_m_per_s", "Particle speed (m s$^{-1}$)"),
        ("Charge_Number_Z", "Charge number, Z"),
    ]
    fig, axes = plt.subplots(2, 2, figsize=(7.2, 5.0), constrained_layout=True)

    for panel_index, (ax, (column, ylabel)) in enumerate(zip(axes.ravel(), panels)):
        for pressure in pressures:
            group = processed[processed["Pm"] == pressure]
            time, mean, std = ensemble_mean_std(group, column)
            color = cmap(norm(pressure))
            ax.plot(time, mean, color=color, label=pressure_label(pressure))
            ax.fill_between(time, mean - std, mean + std, color=color, alpha=0.10, linewidth=0)
        ax.set_xlabel("Time (s)")
        ax.set_ylabel(ylabel)
        add_panel_label(ax, f"({chr(97 + panel_index)})")
        polish_axis(ax)
        if column == "Charge_Number_Z":
            ax.ticklabel_format(axis="y", style="sci", scilimits=(0, 0))

    axes[0, 0].legend(frameon=False, ncol=2, loc="best")
    save_figure(fig, output_dir, "Fig05_ensemble_time_response_mean_sd", config)


def plot_pressure_metrics(
    metrics: pd.DataFrame, output_dir: Path, config: PlotConfig
) -> None:
    pressures = np.array(sorted(metrics["Pm"].unique()), dtype=float)
    panels = [
        ("Maximum_vertical_rise_mm", "Maximum vertical rise (mm)"),
        ("Horizontal_range_mm", "Horizontal range (mm)"),
        ("Net_horizontal_displacement_mm", "Net horizontal displacement (mm)"),
        ("Path_length_mm", "Trajectory length (mm)"),
        ("Mean_speed_m_per_s", "Mean speed (m s$^{-1}$)"),
        ("Peak_speed_m_per_s", "Peak speed (m s$^{-1}$)"),
        ("Final_charge_number_Z", "Final charge number, Z"),
        ("Boundary_crossings", "Periodic-boundary crossings"),
    ]
    fig, axes = plt.subplots(2, 4, figsize=(7.4, 4.3), constrained_layout=True)

    for panel_index, (ax, (column, ylabel)) in enumerate(zip(axes.ravel(), panels)):
        for pressure in pressures:
            values = metrics.loc[metrics["Pm"] == pressure, column].to_numpy(dtype=float)
            offsets = np.linspace(-0.028, 0.028, len(values))
            x_values = pressure * np.exp(offsets)
            ax.scatter(x_values, values, s=12, color="#6C879E", alpha=0.65, linewidths=0)

        summary = metrics.groupby("Pm")[column].agg(["mean", "std"]).reindex(pressures)
        ax.errorbar(
            pressures,
            summary["mean"],
            yerr=summary["std"].fillna(0),
            fmt="o-",
            markersize=3.5,
            color="#B33A3A",
            ecolor="#B33A3A",
            elinewidth=0.8,
            capsize=2,
            label="Mean ± SD",
            zorder=3,
        )
        ax.set_xscale("log")
        display_ticks = np.array([500, 1000, 3000, 10000, 100000], dtype=float)
        display_ticks = display_ticks[
            (display_ticks >= np.min(pressures)) & (display_ticks <= np.max(pressures))
        ]
        ax.set_xticks(display_ticks)
        ax.set_xticklabels([f"{p / 1000:g}" for p in display_ticks])
        ax.set_xlabel("Pressure (kPa)")
        ax.set_ylabel(ylabel)
        add_panel_label(ax, f"({chr(97 + panel_index)})")
        ax.tick_params(which="minor", bottom=False, top=False)
        polish_axis(ax, minor_x=False)
        if column == "Final_charge_number_Z":
            ax.ticklabel_format(axis="y", style="sci", scilimits=(0, 0))

    axes[0, 0].legend(frameon=False, loc="best")
    save_figure(fig, output_dir, "Fig06_pressure_response_particle_metrics", config)


def plot_transport_regime_map(
    metrics: pd.DataFrame, output_dir: Path, config: PlotConfig
) -> None:
    pressures = metrics["Pm"].to_numpy(dtype=float)
    norm = LogNorm(vmin=np.min(pressures), vmax=np.max(pressures))
    cmap = plt.get_cmap("viridis")
    particle_markers = {1: "o", 2: "s", 3: "^", 4: "D", 5: "v", 6: "P", 7: "X"}

    fig, ax = plt.subplots(figsize=(4.5, 3.4), constrained_layout=True)
    scatter_for_colorbar = None
    for particle, marker in particle_markers.items():
        subset = metrics[metrics["Particle_Index"] == particle]
        scatter_for_colorbar = ax.scatter(
            subset["Horizontal_range_mm"],
            subset["Maximum_vertical_rise_mm"],
            c=subset["Pm"],
            cmap=cmap,
            norm=norm,
            marker=marker,
            s=30,
            edgecolors="black",
            linewidths=0.35,
            label=f"Particle {particle}",
        )

    ax.set_xlabel("Horizontal range (mm)")
    ax.set_ylabel("Maximum vertical rise (mm)")
    ax.legend(frameon=False, ncol=2, loc="best")
    polish_axis(ax)
    colorbar = fig.colorbar(scatter_for_colorbar, ax=ax, pad=0.02)
    colorbar.set_label("Pressure (Pa)")
    colorbar.formatter = ScalarFormatter()
    colorbar.update_ticks()
    save_figure(fig, output_dir, "Fig07_horizontal_vertical_transport_map", config)


def write_outputs(
    processed: pd.DataFrame,
    diagnostics: pd.DataFrame,
    metrics: pd.DataFrame,
    output_dir: Path,
    input_path: Path,
    config: PlotConfig,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    processed.to_csv(output_dir / "processed_unwrapped_trajectory_data.csv", index=False, encoding="utf-8-sig")
    diagnostics.to_csv(output_dir / "periodic_unwrapping_diagnostics.csv", index=False, encoding="utf-8-sig")
    metrics.to_csv(output_dir / "particle_trajectory_metrics.csv", index=False, encoding="utf-8-sig")

    run_info = {
        "input_file": str(input_path.resolve()),
        "records": len(processed),
        "pressures_pa": sorted(float(value) for value in processed["Pm"].unique()),
        "particles": sorted(int(value) for value in processed["Particle_Index"].unique()),
        "total_boundary_crossings": int(diagnostics["Boundary_Crossings"].sum()),
        "frozen_groups": int(diagnostics["Frozen"].sum()),
        "maximum_corrected_step_mm": float(diagnostics["Maximum_Corrected_Step_mm"].max()),
        "config": asdict(config),
    }
    (output_dir / "run_summary.json").write_text(
        json.dumps(run_info, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def make_all_plots(
    processed: pd.DataFrame,
    metrics: pd.DataFrame,
    output_dir: Path,
    config: PlotConfig,
) -> None:
    plot_unwrapping_example(processed, metrics, output_dir, config)
    plot_xy_trajectories(processed, output_dir, config)
    plot_time_grid(
        processed,
        "dx_mm",
        "Horizontal displacement, Δx (mm)",
        "Fig03_horizontal_displacement_time",
        output_dir,
        config,
    )
    plot_time_grid(
        processed,
        "dy_mm",
        "Vertical displacement, Δy (mm)",
        "Fig04_vertical_displacement_time",
        output_dir,
        config,
    )
    plot_ensemble_time_response(processed, output_dir, config)
    plot_pressure_metrics(metrics, output_dir, config)
    plot_transport_regime_map(metrics, output_dir, config)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="COMSOL 颗粒数据周期还原与科研绘图")
    parser.add_argument("input_file", nargs="?", type=Path, help="合并后的 XLSX 数据集")
    parser.add_argument("--sheet", default="Data_Long", help="数据工作表名称")
    parser.add_argument("--output-dir", type=Path, default=None, help="输出文件夹")
    parser.add_argument("--left-mm", type=float, default=0.0, help="左周期边界，mm")
    parser.add_argument("--right-mm", type=float, default=3.0, help="右周期边界，mm")
    parser.add_argument("--expansion-periods", type=int, default=5, help="左右各扩展的周期数")
    parser.add_argument("--threshold-fraction", type=float, default=0.5, help="跨界阈值占周期长度的比例")
    parser.add_argument("--dpi", type=int, default=600, help="PNG 分辨率")
    parser.add_argument("--absolute-y", action="store_true", help="二维轨迹使用绝对 qy，而不是相对初始高度")
    parser.add_argument("--png-only", action="store_true", help="只输出 PNG，不输出 PDF")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    input_path = args.input_file or choose_excel_file()
    if input_path is None:
        print("未选择文件。", file=sys.stderr)
        return 1

    input_path = input_path.resolve()
    output_dir = (
        args.output_dir.resolve()
        if args.output_dir
        else input_path.parent / f"{input_path.stem}_plots"
    )
    config = PlotConfig(
        sheet_name=args.sheet,
        left_boundary_mm=args.left_mm,
        right_boundary_mm=args.right_mm,
        expansion_periods=args.expansion_periods,
        crossing_threshold_fraction=args.threshold_fraction,
        relative_y_for_trajectory=not args.absolute_y,
        dpi=args.dpi,
        export_png=True,
        export_pdf=not args.png_only,
    )

    configure_matplotlib()
    print(f"读取数据：{input_path}")
    data = load_dataset(input_path, config.sheet_name)
    print(f"数据行数：{len(data):,}")

    processed, diagnostics = unwrap_periodic_trajectories(data, config)
    metrics = calculate_particle_metrics(processed, diagnostics)
    write_outputs(processed, diagnostics, metrics, output_dir, input_path, config)
    make_all_plots(processed, metrics, output_dir, config)

    print(f"压力数量：{processed['Pm'].nunique()}")
    print(f"粒子–压力组合：{len(metrics)}")
    print(f"周期跨界总次数：{int(diagnostics['Boundary_Crossings'].sum())}")
    print(f"达到冻结边界的组合数：{int(diagnostics['Frozen'].sum())}")
    print(f"修正后最大单步水平位移：{diagnostics['Maximum_Corrected_Step_mm'].max():.6g} mm")
    print(f"输出目录：{output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
