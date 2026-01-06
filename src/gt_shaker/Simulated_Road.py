# GT7 Shaker for Linux 1.27
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

# GT7 Shaker for Linux
# Copyright (C) 2026 Soeren Helskov
# https://github.com/Helskov/GT7-Shaker-for-linux
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

import numpy as np
import time

class RoadSimulator:
    def __init__(self, sample_rate):
        self.sample_rate = sample_rate
        self.wheelbase = 2.75
        self.bump_queue = []
        self.last_bump_time = 0
        self.phase = 0.0
        self.texture_phase = 0.0
        self.last_noise = 0.0 # Filter memory

    def generate_bumps(self, speed_kmh, roughness, texture_vol, effects_vol, texture_freq, is_reverse, frame_count):
        abs_speed = abs(speed_kmh)

        # Start threshold: 3 km/h
        if abs_speed < 3.0:
            return np.zeros(frame_count, dtype=np.float32), np.zeros(frame_count, dtype=np.float32)

        # Hypercar Quadratic Ramp (1.0 at 200 km/h)
        speed_ramp = min(2.0, ((abs_speed - 3.0) / 197.0) ** 2.0)

        now = time.time()
        v_ms = abs_speed / 3.6
        steps = np.arange(frame_count)
        front_sig = np.zeros(frame_count, dtype=np.float32)
        rear_sig = np.zeros(frame_count, dtype=np.float32)

        # --- 1. SURFACE TEXTURE (Deep Brum) ---
        if texture_vol > 0:
            # Use User Frequency + speed scaling
            base_freq = float(texture_freq) + (v_ms * 0.45)
            grain_rad = 2 * np.pi * base_freq / self.sample_rate

            # Double-layered sine waves for "weight"
            main_sine = np.sin(self.texture_phase + (steps * grain_rad))
            sub_sine = 0.6 * np.sin((self.texture_phase * 0.5) + (steps * grain_rad * 0.5))

            # Deep Rumble Filter (Alpha 0.05)
            raw_noise = np.random.uniform(-1.0, 1.0, frame_count)
            filtered_noise = np.zeros(frame_count, dtype=np.float32)
            alpha = 0.05
            current_val = self.last_noise
            for i in range(frame_count):
                current_val = current_val + alpha * (raw_noise[i] - current_val)
                filtered_noise[i] = current_val
            self.last_noise = current_val

            # Combine into the final texture signal
            grain_wave = (main_sine + sub_sine + (filtered_noise * 3.5)) * 1.2 * texture_vol * speed_ramp
            front_sig += grain_wave
            rear_sig += grain_wave
            self.texture_phase = (self.texture_phase + (frame_count * grain_rad)) % (2 * np.pi)

        # --- 2. DISCRETE BUMPS (Road Effects) ---
        if roughness > 0 and effects_vol > 0:
            bump_chance = (roughness * 0.15) * (v_ms * 0.05)
            if np.random.random() < bump_chance and (now - self.last_bump_time) > 0.1:
                intensity = np.random.uniform(0.5, 1.0) * roughness
                delay = self.wheelbase / v_ms
                self.bump_queue.append({
                    'rear_trigger': now + delay,
                    'intensity': intensity,
                    'front_samples_left': int(0.15 * self.sample_rate),
                    'rear_samples_left': int(0.15 * self.sample_rate),
                    'rear_active': False
                })
                self.last_bump_time = now

            step_rad = 2 * np.pi * 22.0 / self.sample_rate # Deep 22Hz thumps
            remaining_bumps = []
            for bump in self.bump_queue:
                wave = np.sin(self.phase + (steps * step_rad)) * bump['intensity'] * effects_vol * speed_ramp
                if bump['front_samples_left'] > 0:
                    if not is_reverse: front_sig += wave
                    else: rear_sig += wave
                    bump['front_samples_left'] -= frame_count
                if not bump['rear_active'] and now >= bump['rear_trigger']:
                    bump['rear_active'] = True
                if bump['rear_active'] and bump['rear_samples_left'] > 0:
                    if not is_reverse: rear_sig += wave
                    else: front_sig += wave
                    bump['rear_samples_left'] -= frame_count
                if bump['front_samples_left'] > 0 or bump['rear_samples_left'] > 0 or not bump['rear_active']:
                    remaining_bumps.append(bump)
            self.bump_queue = remaining_bumps
            self.phase = (self.phase + (frame_count * step_rad)) % (2 * np.pi)

        return front_sig, rear_sig
