# Scientific Plotting Templates｜科研绘图模板

Reusable scientific plots for particle activity, jump metrics, size distributions, and COMSOL trajectories.

从原代码库筛选出四类可复用图：颗粒活跃度 PAI 岭线图、起跳指标与压强对比、粒径累计分布及 D10/D50/D90、COMSOL 颗粒轨迹与荷电图。各模板在独立子目录中，输入列和运行方法如下。示例数据由 `generate_demo_data.py` 确定性生成，**仅供版式与流程演示，不是实验或仿真结果**。

![合成数据的 PAI 岭线示例](examples/expected/pai_ridgeline.png)

## 快速开始

```powershell
python -m pip install -r requirements.txt
python generate_demo_data.py
python templates/pai_ridgeline/plot_pai_ridgeline.py
python templates/jump_metrics/plot_jump_metrics.py
python templates/particle_size_distribution/plot_particle_size_distribution.py --input templates/particle_size_distribution/data/synthetic_particle_size_distribution.xlsx --output templates/particle_size_distribution/psd_demo.png
python templates/comsol_trajectories/plot_comsol_trajectories.py templates/comsol_trajectories/data/synthetic_comsol_particle_dataset.xlsx --output-dir templates/comsol_trajectories/demo_plots --dpi 150 --png-only
```

PAI 脚本还提供 `plot_pai_peak_aligned.py`，用于比较峰值时间对齐后的形状；它与标准版的科学问题不同，不能把对齐后的横坐标当作原始事件时间。更多预览在 `examples/expected/`。

| 模板 | 所需输入 | 示例所在位置 |
|---|---|---|
| PAI 岭线 | `P1`–`P4` 各目录下按压强命名的 CSV，例如 `3000pa.csv`；列为 `time_ms_based_on_capture_fps`、`particle_activity_index` | `templates/pai_ridgeline/input_pai_groups/` |
| 起跳指标 | 每组一个 CSV/XLSX；列为 `pressure_Pa`、`segment_id`、`jump_height_mm`、`horizontal_displacement_mm_abs` | `templates/jump_metrics/input_data/` |
| 粒径分布 | Excel 前 8 列按四组排列：每组“粒径 μm、累计百分比” | `templates/particle_size_distribution/data/` |
| COMSOL 轨迹 | Excel `Data_Long` 工作表；列为 `Particle_Index`、`Pm`、`Time_s`、`qx_m`、`qy_m`、`Velocity_m_per_s`、`Charge_Number_Z` | `templates/comsol_trajectories/data/` |

模板输出默认是高分辨率图片，有的还会生成 PDF 或 CSV。仓库保留了原脚本的绘图逻辑；真正用于论文前，应检查单位、粒径组名、压强范围、统计重复层级及图中的推断边界。

## 版本取舍

PAI 保留标准和峰值对齐两种有明确用途的版本；起跳指标只保留通用多文件版；原压缩包中 CO₂ 特定版、早期力图版和大量已生成图件未混入模板。COMSOL 综合轨迹图保留，因为其周期边界还原和多指标图具有独立用途。示例表格由 `generate_demo_data.py` 生成；原始代码由作者保留。
