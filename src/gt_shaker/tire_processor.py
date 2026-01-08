# GT7 Shaker for Linux 1.28
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



#V1.27 Changed Auto calibration. Took to long.

import numpy as np

# --- ORIGINAL UI COLOR LOGIC ---

def get_tire_color(temp):
    """ Returns color hex based on temperature thresholds """
    if temp <= 0:
        return "#ffffff" # Invalid/No data: White
    elif temp < 72:
        return "#007acc" # Cold: Blue
    elif 72 <= temp <= 95:
        return "#4caf50" # Optimal: Green
    else:
        return "#f44336" # Too Hot: Red

def process_tires(data):
    """ Processes telemetry data safely into UI-ready formats """
    # Kun temperatur-adresser bevares
    tire_map = [
        {"t": "tire_temp_FL"},
        {"t": "tire_temp_FR"},
        {"t": "tire_temp_RL"},
        {"t": "tire_temp_RR"}
    ]

    processed = []
    for tire in tire_map:
        temp = getattr(data, tire["t"], 0)

        processed.append({
            "temp": round(temp, 1),
            "temp_color": get_tire_color(temp)
        })
    return processed

# --- TRACTION & LOCKUP PROCESSOR ---

class TireProcessor:
    def __init__(self):
        # Traction & Slip Settings
        self.threshold = 0.05       # 5% slip ratio before vibration starts
        self.sensitivity = 0.15     # Full vibration reached at 20% slip (0.05 + 0.15)
        self.use_autocalib = True   # Toggle for automatic radius correction

        # Correction factors for tire rolling radius (start at 1.0)
        self.calib = {"FL": 1.0, "FR": 1.0, "RL": 1.0, "RR": 1.0}

    def get_traction_triggers(self, d):
        """ Calculates vibration triggers (0.0 - 1.0) for front and rear axles """
        # Safety: Stop vibration at very low speeds or missing data
        if not d or d.speed_kmh < 5.0:
            return 0.0, 0.0

        v_car = d.speed_kmh / 3.6 # Convert car speed to m/s

        # 1. DEFINE STRAIGHT DRIVING
        # Define "straight" as a difference of less than 0.1 m/s between front wheels.
        # This variable is now defined and ready for use.
        is_driving_straight = abs(d.wheel_speed_FL - d.wheel_speed_FR) < 0.1

        # 2. AUTOCALIBRATION LOGIC
        # Use the variable we just defined to ensure only calibrate when going straight.
        if self.use_autocalib and d.brake == 0 and 0 <= d.throttle < 30 and is_driving_straight:
            alpha = 0.001 # Learning rate

            def calculate_factor(wheel_speed, nominal_radius):
                # Ratio: Actual Speed / Theoretical Speed
                return v_car / (abs(wheel_speed) * nominal_radius) if abs(wheel_speed) > 0.1 else 1.0

            # Update calibration factors using the new logic
            self.calib["FL"] = (1-alpha)*self.calib["FL"] + alpha*calculate_factor(d.wheel_speed_FL, d.wheel_radius_FL)
            self.calib["FR"] = (1-alpha)*self.calib["FR"] + alpha*calculate_factor(d.wheel_speed_FR, d.wheel_radius_FR)
            self.calib["RL"] = (1-alpha)*self.calib["RL"] + alpha*calculate_factor(d.wheel_speed_RL, d.wheel_radius_RL)
            self.calib["RR"] = (1-alpha)*self.calib["RR"] + alpha*calculate_factor(d.wheel_speed_RR, d.wheel_radius_RR)

        # 3. CALCULATE ACTUAL WHEEL SPEEDS (m/s)
        # Using corrected radius: Wheel Speed (rad/s) * Radius (m) * Calibration Factor
        v_fl = abs(d.wheel_speed_FL) * d.wheel_radius_FL * self.calib["FL"]
        v_fr = abs(d.wheel_speed_FR) * d.wheel_radius_FR * self.calib["FR"]
        v_rl = abs(d.wheel_speed_RL) * d.wheel_radius_RL * self.calib["RL"]
        v_rr = abs(d.wheel_speed_RR) * d.wheel_radius_RR * self.calib["RR"]

        # 4. CALCULATE SLIP RATIO
        # Formula: |Car Speed - Wheel Speed| / Car Speed
        slip_f = max(abs(v_car - v_fl), abs(v_car - v_fr)) / v_car
        slip_r = max(abs(v_car - v_rl), abs(v_car - v_rr)) / v_car

        # 5. SCALE TO TRIGGER VALUES (0.0 to 1.0)
        # Uses the sensitivity and threshold defined in __init__
        trig_f = min(1.0, (slip_f - self.threshold) / self.sensitivity) if slip_f > self.threshold else 0.0
        trig_r = min(1.0, (slip_r - self.threshold) / self.sensitivity) if slip_r > self.threshold else 0.0

        return trig_f, trig_r

        return trig_f, trig_r
