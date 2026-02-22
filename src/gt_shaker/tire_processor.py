# GT7 Shaker for Linux 1.41
# Copyright (C) 2026 Soeren Helskov
# https://github.com/Helskov/GT7-Shaker-for-linux
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.
import numpy as np

try:
    from numba import njit
except ImportError:
    def njit(f=None, *args, **kwargs):
        if callable(f): return f
        def decorator(func): return func
        return decorator

@njit(fastmath=True, cache=True)
def jit_traction_calc(v_car, wheel_speeds, wheel_radii, calib, threshold, sensitivity, is_braking, abs_offset):
    tc_f, tc_r = 0.0, 0.0
    abs_f, abs_r = 0.0, 0.0

    if v_car < 1.0: return 0.0, 0.0, 0.0, 0.0

    v_fl = wheel_speeds[0] * wheel_radii[0] * calib[0]
    v_fr = wheel_speeds[1] * wheel_radii[1] * calib[1]
    v_rl = wheel_speeds[2] * wheel_radii[2] * calib[2]
    v_rr = wheel_speeds[3] * wheel_radii[3] * calib[3]

    diff_fl = v_fl - v_car; diff_fr = v_fr - v_car
    diff_rl = v_rl - v_car; diff_rr = v_rr - v_car

    # --- FRONT AXLE ---
    if is_braking:
        slip_fl = max(0.0, -diff_fl / v_car); slip_fr = max(0.0, -diff_fr / v_car)
        max_slip_f = max(slip_fl, slip_fr)
        if max_slip_f > (threshold + abs_offset):
            abs_f = min(1.0, (max_slip_f - (threshold + abs_offset)) / sensitivity)
    else:
        slip_fl = max(0.0, diff_fl / v_car); slip_fr = max(0.0, diff_fr / v_car)
        max_slip_f = max(slip_fl, slip_fr)
        if max_slip_f > threshold:
            tc_f = min(1.0, (max_slip_f - threshold) / sensitivity)

    # --- REAR AXLE ---
    if is_braking:
        slip_rl = max(0.0, -diff_rl / v_car); slip_rr = max(0.0, -diff_rr / v_car)
        max_slip_r = max(slip_rl, slip_rr)
        if max_slip_r > (threshold + abs_offset):
            abs_r = min(1.0, (max_slip_r - (threshold + abs_offset)) / sensitivity)
    else:
        slip_rl = max(0.0, diff_rl / v_car); slip_rr = max(0.0, diff_rr / v_car)
        max_slip_r = max(slip_rl, slip_rr)
        if max_slip_r > threshold:
            tc_r = min(1.0, (max_slip_r - threshold) / sensitivity)

    return tc_f, tc_r, abs_f, abs_r

def get_tire_color(temp, base=72.0, spread=12.0):
    """ Returns dynamic color hex based on user settings """
    half_spread = spread / 2.0
    optimal_low = base - half_spread
    optimal_high = base + half_spread

    if temp <= 0: return "#ffffff" # Hvid (Ingen data)
    elif temp < optimal_low: return "#007acc" # Kold (Blå)
    elif optimal_low <= temp <= optimal_high: return "#4caf50" # Optimal (Grøn)
    else: return "#f44336" # Varm (Rød)

def process_tires(data, base=72.0, spread=12.0):
    """ Processes telemetry data with dynamic temperature window """
    tire_map = [{"t": "tire_temp_FL"}, {"t": "tire_temp_FR"}, {"t": "tire_temp_RL"}, {"t": "tire_temp_RR"}]
    processed = []
    for tire in tire_map:
        temp = getattr(data, tire["t"], 0)
        col = get_tire_color(temp, base, spread)
        processed.append({"temp": round(temp, 1), "temp_color": col})
    return processed

class TireProcessor:
    def __init__(self):
        self.threshold = 0.05
        self.sensitivity = 0.15
        self.abs_offset = 0.09
        self.use_autocalib = True
        self.calib = np.array([1.0, 1.0, 1.0, 1.0], dtype=np.float32)

    def get_traction_triggers(self, d):
        if not d or d.speed_kmh < 5.0: return 0.0, 0.0, 0.0, 0.0
        v_car = d.speed_kmh / 3.6
        is_braking = d.brake > 0
        ws = np.array([abs(d.wheel_speed_FL), abs(d.wheel_speed_FR), abs(d.wheel_speed_RL), abs(d.wheel_speed_RR)], dtype=np.float32)
        wr = np.array([d.wheel_radius_FL, d.wheel_radius_FR, d.wheel_radius_RL, d.wheel_radius_RR], dtype=np.float32)

        if self.use_autocalib and not is_braking and 0 <= d.throttle < 30 and abs(ws[0] - ws[1]) < 0.1:
            alpha = 0.001
            for i in range(4):
                if ws[i] > 0.1:
                    factor = v_car / (ws[i] * wr[i])
                    self.calib[i] = (1 - alpha) * self.calib[i] + alpha * factor

        return jit_traction_calc(v_car, ws, wr, self.calib, self.threshold, self.sensitivity, is_braking, self.abs_offset)
