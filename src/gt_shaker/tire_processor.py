# GT7 Shaker for Linux 1.30
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
    def njit(f): return f

# --- JIT OPTIMIZED PHYSICS KERNEL ---
@njit(fastmath=True, cache=True)
def jit_traction_calc(v_car, wheel_speeds, wheel_radii, calib, threshold, sensitivity):
    """ Calculates slip ratios and triggers using machine code """
    # 1. Calculate Actual Wheel Speeds
    v_fl = wheel_speeds[0] * wheel_radii[0] * calib[0]
    v_fr = wheel_speeds[1] * wheel_radii[1] * calib[1]
    v_rl = wheel_speeds[2] * wheel_radii[2] * calib[2]
    v_rr = wheel_speeds[3] * wheel_radii[3] * calib[3]

    # 2. Slip Ratios (Normalized to Car Speed)
    slip_f = np.maximum(np.abs(v_car - v_fl), np.abs(v_car - v_fr)) / v_car
    slip_r = np.maximum(np.abs(v_car - v_rl), np.abs(v_car - v_rr)) / v_car

    # 3. Scale to Trigger Values (0.0 to 1.0)
    trig_f = np.minimum(1.0, (slip_f - threshold) / sensitivity) if slip_f > threshold else 0.0
    trig_r = np.minimum(1.0, (slip_r - threshold) / sensitivity) if slip_r > threshold else 0.0

    return trig_f, trig_r

def get_tire_color(temp):
    """ Returns color hex based on temperature thresholds """
    if temp <= 0: return "#ffffff"
    elif temp < 72: return "#007acc"
    elif 72 <= temp <= 95: return "#4caf50"
    else: return "#f44336"

def process_tires(data):
    """ Processes telemetry data safely into UI-ready formats """
    tire_map = [{"t": "tire_temp_FL"}, {"t": "tire_temp_FR"}, {"t": "tire_temp_RL"}, {"t": "tire_temp_RR"}]
    processed = []
    for tire in tire_map:
        temp = getattr(data, tire["t"], 0)
        processed.append({"temp": round(temp, 1), "temp_color": get_tire_color(temp)})
    return processed

class TireProcessor:
    def __init__(self):
        self.threshold = 0.05
        self.sensitivity = 0.15
        self.use_autocalib = True
        # Calibration factors as NumPy array for JIT
        self.calib = np.array([1.0, 1.0, 1.0, 1.0], dtype=np.float32)

    def get_traction_triggers(self, d):
        if not d or d.speed_kmh < 5.0: return 0.0, 0.0
        v_car = d.speed_kmh / 3.6

        wheel_speeds = np.array([abs(d.wheel_speed_FL), abs(d.wheel_speed_FR), abs(d.wheel_speed_RL), abs(d.wheel_speed_RR)], dtype=np.float32)
        wheel_radii = np.array([d.wheel_radius_FL, d.wheel_radius_FR, d.wheel_radius_RL, d.wheel_radius_RR], dtype=np.float32)

        # 1. Autocalibration (Straight driving detection)
        if self.use_autocalib and d.brake == 0 and 0 <= d.throttle < 30 and abs(wheel_speeds[0] - wheel_speeds[1]) < 0.1:
            alpha = 0.001
            for i in range(4):
                if wheel_speeds[i] > 0.1:
                    factor = v_car / (wheel_speeds[i] * wheel_radii[i])
                    self.calib[i] = (1 - alpha) * self.calib[i] + alpha * factor

        # 2. JIT Optimized Calculation
        return jit_traction_calc(v_car, wheel_speeds, wheel_radii, self.calib, self.threshold, self.sensitivity)
