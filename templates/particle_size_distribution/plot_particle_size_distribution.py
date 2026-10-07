"""
绘制四组粒径数据的：
1. 线性累计粒径分布曲线；
2. D10-D90特征粒径区间及D50中位粒径。

使用方法：
    1) 将本程序与“四个粒径分布(1).xlsx”放在同一文件夹；
    2) 安装依赖：pip install matplotlib numpy pandas openpyxl
    3) 运行：python plot_linear_cumulative_psd.py

也可以指定输入和输出路径：
    python plot_linear_cumulative_psd.py --input 数据.xlsx --output 结果.png
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

# 使用非交互式后端，适合批处理和无界面环境。
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib import font_manager
from matplotlib.lines import Line2D
from matplotlib.ticker import AutoMinorLocator


# ======================== 用户常用修改区 ========================
DEFAULT_INPUT_NAME = "四个粒径分布(1).xlsx"
DEFAULT_OUTPUT_NAME = "linear_cumulative_psd_D10_D50_D90.png"

# 图片分辨率；论文图片建议使用600 dpi。
FIGURE_DPI = 600

# 图中字体。Windows系统通常已经安装Times New Roman。
FONT_NAME = "Times New Roman"

# 四组样品的颜色和点形；需要改变配色时修改这里。
COLORS = ["#0072B2", "#D55E00", "#009E73", "#CC79A7"]
MARKERS = ["o", "s", "^", "D"]

# 图像尺寸，单位为inch。双栏论文通常可使用7.0～7.3 inch宽度。
FIGURE_SIZE = (7.25, 3.35)
# ===============================================================


def parse_args() -> argparse.Namespace:
    """读取命令行参数；不指定时默认读取脚本同目录下的Excel文件。"""
    script_dir = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="绘制线性累计粒径分布及D10/D50/D90区间图")
    parser.add_argument(
        "--input",
        type=Path,
        default=script_dir / DEFAULT_INPUT_NAME,
        help="输入Excel文件路径",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=script_dir / DEFAULT_OUTPUT_NAME,
        help="输出PNG图片路径",
    )
    return parser.parse_args()


def load_particle_size_data(input_file: Path) -> list[dict]:
    """
    读取Excel中的四组成对数据：粒径、累计百分比。

    程序按前8列解析：
        A-B列=P1，C-D列=P2，E-F列=P3，G-H列=P4。
    单位行和空白单元格会自动转为NaN并删除。
    """
    raw = pd.read_excel(input_file, sheet_name=0)
    if raw.shape[1] < 8:
        raise ValueError("输入文件至少需要8列：四组‘粒径-累计百分比’数据。")

    series = []
    for index, label in enumerate(["P1", "P2", "P3", "P4"]):
        diameter = pd.to_numeric(raw.iloc[:, index * 2], errors="coerce")
        cumulative = pd.to_numeric(raw.iloc[:, index * 2 + 1], errors="coerce")
        valid = diameter.notna() & cumulative.notna()

        diameter = diameter[valid].to_numpy(dtype=float)
        cumulative = cumulative[valid].to_numpy(dtype=float)

        # 按粒径从小到大排序，确保累计曲线连接顺序正确。
        order = np.argsort(diameter)
        diameter = diameter[order]
        cumulative = cumulative[order]

        if len(diameter) < 2:
            raise ValueError(f"{label}的有效数据点少于2个。")
        if np.any(np.diff(cumulative) < -1e-10):
            raise ValueError(f"{label}的累计百分比不是单调递增数据。")
        if cumulative.min() > 10 or cumulative.max() < 90:
            raise ValueError(f"{label}没有完整覆盖D10-D90所需范围。")

        series.append(
            {
                "label": label,
                "diameter": diameter,
                "cumulative": cumulative,
            }
        )
    return series


def interpolate_characteristic_diameter(
    diameter: np.ndarray,
    cumulative: np.ndarray,
    percentile: float,
) -> float:
    """
    在线性“粒径-累计百分比”坐标中计算D10、D50或D90。

    当累计百分比存在重复平台值时，先取这些粒径的算术平均值，
    再进行分段线性插值，以避免重复横坐标导致插值不稳定。
    """
    frame = pd.DataFrame({"diameter": diameter, "cumulative": cumulative})
    grouped = (
        frame.groupby("cumulative", as_index=False, sort=True)["diameter"]
        .mean()
        .sort_values("cumulative")
    )
    return float(
        np.interp(
            percentile,
            grouped["cumulative"].to_numpy(dtype=float),
            grouped["diameter"].to_numpy(dtype=float),
        )
    )


def calculate_characteristic_diameters(series: list[dict]) -> pd.DataFrame:
    """计算每组数据的D10、D50和D90。"""
    rows = []
    for item in series:
        values = {
            f"D{percentile}": interpolate_characteristic_diameter(
                item["diameter"], item["cumulative"], percentile
            )
            for percentile in (10, 50, 90)
        }
        item.update(values)
        rows.append(
            {
                "Sample": item["label"],
                "D10 (um)": item["D10"],
                "D50 (um)": item["D50"],
                "D90 (um)": item["D90"],
            }
        )
    return pd.DataFrame(rows)


def configure_matplotlib() -> None:
    """设置论文绘图风格，所有图中文字统一使用Times New Roman。"""
    installed_fonts = {font.name for font in font_manager.fontManager.ttflist}
    if FONT_NAME in installed_fonts:
        selected_font = FONT_NAME
    elif "Nimbus Roman" in installed_fonts:
        # 仅用于未安装Times New Roman的Linux环境；Windows通常会直接使用新罗马。
        selected_font = "Nimbus Roman"
        print("提示：当前系统未安装Times New Roman，预览图暂用Nimbus Roman。")
    else:
        selected_font = "DejaVu Serif"
        print("提示：当前系统未安装Times New Roman，预览图暂用DejaVu Serif。")

    plt.rcParams.update(
        {
            "font.family": selected_font,
            # 数学变量也使用同一字体，避免坐标轴中的d、D与正文风格不一致。
            "mathtext.fontset": "custom",
            "mathtext.rm": selected_font,
            "mathtext.it": f"{selected_font}:italic",
            "mathtext.bf": f"{selected_font}:bold",
            "font.size": 9,
            "axes.labelsize": 10,
            "axes.linewidth": 0.9,
            "xtick.direction": "in",
            "ytick.direction": "in",
            "xtick.top": True,
            "ytick.right": True,
            "xtick.major.width": 0.9,
            "ytick.major.width": 0.9,
            "xtick.minor.width": 0.7,
            "ytick.minor.width": 0.7,
            "legend.frameon": False,
            "axes.unicode_minus": False,
        }
    )


def plot_figure(series: list[dict], output_file: Path) -> None:
    """绘制双面板论文图并保存为PNG。"""
    configure_matplotlib()

    fig, (ax_curve, ax_summary) = plt.subplots(
        1,
        2,
        figsize=FIGURE_SIZE,
        gridspec_kw={"width_ratios": [1.45, 1.0], "wspace": 0.32},
    )

    # ---------------- (a) 线性累计粒径分布曲线 ----------------
    for item, color, marker in zip(series, COLORS, MARKERS):
        point_count = len(item["diameter"])
        mark_every = max(1, point_count // 11)
        ax_curve.plot(
            item["diameter"],
            item["cumulative"],
            color=color,
            lw=1.7,
            marker=marker,
            markevery=mark_every,
            ms=4.2,
            mfc="white",
            mec=color,
            mew=0.9,
            label=item["label"],
        )

        # 在累计百分比50%处标记D50。
        ax_curve.scatter(
            item["D50"],
            50,
            s=28,
            color=color,
            marker=marker,
            zorder=4,
        )

    # D10、D50、D90对应的水平辅助线。
    for percentile in (10, 50, 90):
        ax_curve.axhline(
            percentile,
            color="0.76",
            lw=0.7,
            ls=(0, (3, 3)),
            zorder=0,
        )

    maximum_diameter = max(float(item["diameter"].max()) for item in series)
    ax_curve.set_xlim(0, maximum_diameter * 1.04)
    ax_curve.set_ylim(0, 100)
    ax_curve.set_xticks(np.arange(0, 321, 40))
    ax_curve.set_yticks(np.arange(0, 101, 20))
    ax_curve.xaxis.set_minor_locator(AutoMinorLocator(2))
    ax_curve.yaxis.set_minor_locator(AutoMinorLocator(2))
    ax_curve.set_xlabel(r"Particle diameter, $d$ ($\mu$m)")
    ax_curve.set_ylabel("Cumulative undersize (%)")
    # 图例放在右下方空白区域，避免遮挡P1-P3的主要上升段。
    ax_curve.legend(loc="lower right", ncol=1, handlelength=2.5)
    ax_curve.text(
        0.02,
        0.97,
        "(a)",
        transform=ax_curve.transAxes,
        ha="left",
        va="top",
        fontweight="bold",
    )

    # ---------------- (b) D10-D90区间与D50 ----------------
    y_positions = np.arange(len(series))[::-1]
    for y, item, color, marker in zip(y_positions, series, COLORS, MARKERS):
        # 横线表示D10-D90主要粒径区间。
        ax_summary.hlines(y, item["D10"], item["D90"], color=color, lw=2.2)

        # 空心端点分别表示D10和D90。
        ax_summary.scatter(
            [item["D10"], item["D90"]],
            [y, y],
            s=30,
            facecolor="white",
            edgecolor=color,
            lw=1.1,
            zorder=3,
        )

        # 实心点表示D50。
        ax_summary.scatter(
            item["D50"],
            y,
            s=42,
            color=color,
            marker=marker,
            zorder=4,
        )

    maximum_d90 = max(float(item["D90"]) for item in series)
    ax_summary.set_xlim(0, maximum_d90 * 1.15)
    ax_summary.set_ylim(-0.65, len(series) - 0.35)
    ax_summary.set_yticks(y_positions)
    ax_summary.set_yticklabels([item["label"] for item in series])
    ax_summary.xaxis.set_minor_locator(AutoMinorLocator(2))
    ax_summary.set_xlabel(r"Characteristic diameter ($\mu$m)")
    ax_summary.text(
        0.02,
        0.97,
        "(b)",
        transform=ax_summary.transAxes,
        ha="left",
        va="top",
        fontweight="bold",
    )

    # 右图图例：空心端点为D10/D90，实心点为D50。
    legend_handles = [
        Line2D(
            [0],
            [0],
            color="0.25",
            lw=2.0,
            marker="o",
            mfc="white",
            label=r"$D_{10}$-$D_{90}$",
        ),
        Line2D(
            [0],
            [0],
            color="none",
            marker="o",
            markerfacecolor="0.25",
            markeredgecolor="0.25",
            label=r"$D_{50}$",
        ),
    ]
    ax_summary.legend(handles=legend_handles, loc="lower left", fontsize=8)

    output_file.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_file, dpi=FIGURE_DPI, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def main() -> None:
    args = parse_args()
    input_file = args.input.resolve()
    output_file = args.output.resolve()

    if not input_file.exists():
        raise FileNotFoundError(
            f"未找到输入文件：{input_file}\n"
            f"请将{DEFAULT_INPUT_NAME}与程序放在同一文件夹，或使用--input指定路径。"
        )

    series = load_particle_size_data(input_file)
    characteristic_table = calculate_characteristic_diameters(series)
    plot_figure(series, output_file)

    print("\nD10/D50/D90计算结果（线性插值）：")
    print(characteristic_table.to_string(index=False, float_format=lambda value: f"{value:.3f}"))
    print(f"\n图片已保存：{output_file}")


if __name__ == "__main__":
    main()
