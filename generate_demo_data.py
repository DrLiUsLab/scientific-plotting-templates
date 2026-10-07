"""Create small synthetic inputs for each retained plotting template.

All values are illustrative. They are not experimental or simulation results.
"""

from pathlib import Path
from csv import writer
from math import exp, sin, pi
from openpyxl import Workbook

root = Path(__file__).resolve().parent / "templates"


def make_pai() -> None:
    base = root / "pai_ridgeline" / "input_pai_groups"
    for group_index, group in enumerate(("P1", "P2", "P3", "P4")):
        for pressure in (500, 1500, 3000, 5000):
            folder = base / group
            folder.mkdir(parents=True, exist_ok=True)
            with (folder / f"{pressure}pa.csv").open("w", newline="", encoding="utf-8") as file:
                out = writer(file)
                out.writerow(("time_ms_based_on_capture_fps", "particle_activity_index"))
                for ms in range(0, 10001, 100):
                    time_s = ms / 1000
                    amplitude = (0.25 + 0.15 * group_index) * (1.0 if pressure == 3000 else 0.62)
                    value = 0.02 + amplitude * exp(-((time_s - 5.0 - 0.12 * group_index) / 1.1) ** 2)
                    out.writerow((ms, round(value, 6)))


def make_jump() -> None:
    folder = root / "jump_metrics" / "input_data"
    folder.mkdir(parents=True, exist_ok=True)
    for group_index, group in enumerate(("P1", "P2")):
        with (folder / f"{group}.csv").open("w", newline="", encoding="utf-8") as file:
            out = writer(file)
            out.writerow(("pressure_Pa", "segment_id", "jump_height_mm", "horizontal_displacement_mm_abs"))
            for pressure in (500, 1500, 3000, 5000, 10000):
                for segment in range(1, 5):
                    for particle in range(5):
                        peak = exp(-((pressure - 3000) / 3600) ** 2)
                        jitter = (segment - 2.5) * 0.017 + (particle - 2) * 0.009
                        height = max(0.03, 0.13 + peak * (0.42 + 0.09 * group_index) + jitter)
                        displacement = max(0.02, 0.22 + peak * (0.35 + 0.06 * group_index) + jitter)
                        out.writerow((pressure, f"segment_{segment:03d}", round(height, 5), round(displacement, 5)))


def make_psd() -> None:
    folder = root / "particle_size_distribution" / "data"
    folder.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Synthetic PSD"
    sheet.append([value for group in range(1, 5) for value in (f"P{group}_diameter_um", f"P{group}_cumulative_pct")])
    for row in range(21):
        fraction = row / 20
        sheet.append([value for group in range(4) for value in (round(25 + group * 40 + fraction * 150, 3), round(fraction * 100, 3))])
    workbook.save(folder / "synthetic_particle_size_distribution.xlsx")


def make_comsol() -> None:
    folder = root / "comsol_trajectories" / "data"
    folder.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Data_Long"
    sheet.append(("Particle_Index", "Pm", "Time_s", "qx_m", "qy_m", "Velocity_m_per_s", "Charge_Number_Z"))
    for pressure in (500, 3000, 10000):
        pressure_factor = {500: 0.65, 3000: 1.0, 10000: 0.78}[pressure]
        for particle in (1, 2, 3):
            for step in range(25):
                time_s = step * 0.002
                x_mm = (0.4 + particle * 0.25 + pressure_factor * step * 0.22) % 3.0
                y_mm = 0.15 + pressure_factor * (0.12 + 0.30 * sin(pi * step / 24) ** 2)
                velocity = 0.015 + pressure_factor * 0.008 * abs(sin(pi * step / 24))
                charge = 1000 + pressure_factor * 1800 * (1 - exp(-step / 6))
                sheet.append((particle, pressure, time_s, x_mm / 1000, y_mm / 1000, velocity, charge))
    workbook.save(folder / "synthetic_comsol_particle_dataset.xlsx")


if __name__ == "__main__":
    make_pai()
    make_jump()
    make_psd()
    make_comsol()
    print("Generated four synthetic plotting datasets under templates/")
