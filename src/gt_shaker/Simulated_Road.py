# GT7 Shaker for Linux 1.31
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
import time

try:
    from numba import njit
except ImportError:
    def njit(func): return func

@njit(fastmath=True, cache=True)
def generate_texture_jit(steps, phase, jitter_phase, grain_rad, jitter_rad, texture_vol, speed_ramp):
    """ Generates road texture at C-speed """
    jitter = 0.3 * np.sin(jitter_phase + (steps * jitter_rad))
    texture_wave = np.sin(phase + (steps * grain_rad) + jitter)
    return np.tanh(texture_wave * 2.5) * texture_vol * speed_ramp * 0.8

class RoadSimulator:
    def __init__(self, sample_rate):
        self.sample_rate = sample_rate
        self.wheelbase = 2.75
        self.bump_queue = []
        self.last_bump_time = 0
        self.phase = 0.0
        self.texture_phase = 0.0
        self.jitter_phase = 0.0

    def generate_bumps(self, speed_kmh, roughness, texture_vol, effects_vol, texture_freq, is_reverse, frame_count):
        abs_speed = abs(speed_kmh)
        if abs_speed < 3.0: return np.zeros(frame_count, dtype=np.float32), np.zeros(frame_count, dtype=np.float32)

        speed_ramp = min(2.0, ((abs_speed - 3.0) / 197.0) ** 2.0)
        v_ms = abs_speed / 3.6
        steps = np.arange(frame_count, dtype=np.float32)
        front_sig = np.zeros(frame_count, dtype=np.float32); rear_sig = np.zeros(frame_count, dtype=np.float32)

        if texture_vol > 0:
            grain_rad = 2 * np.pi * (float(texture_freq) + (v_ms * 0.3)) / self.sample_rate
            jitter_rad = 2 * np.pi * 10.0 / self.sample_rate
            grain_wave = generate_texture_jit(steps, self.texture_phase, self.jitter_phase, grain_rad, jitter_rad, texture_vol, speed_ramp)
            front_sig += grain_wave; rear_sig += grain_wave
            self.texture_phase = (self.texture_phase + (frame_count * grain_rad)) % (2 * np.pi)
            self.jitter_phase = (self.jitter_phase + (frame_count * jitter_rad)) % (2 * np.pi)

        # Discrete Bumps handling (Standard Python is fine for low-frequency events)
        now = time.time()
        if roughness > 0 and effects_vol > 0:
            if np.random.random() < (roughness * 0.15 * v_ms * 0.05) and (now - self.last_bump_time) > 0.1:
                self.bump_queue.append({
                    'rear_trigger': now + (self.wheelbase / v_ms),
                    'intensity': np.random.uniform(0.5, 1.0) * roughness,
                    'front_samples_left': int(0.15 * self.sample_rate),
                    'rear_samples_left': int(0.15 * self.sample_rate),
                    'rear_active': False
                })
                self.last_bump_time = now

            step_rad = 2 * np.pi * 22.0 / self.sample_rate
            active_bumps = []
            for b in self.bump_queue:
                w = np.sin(self.phase + (steps * step_rad)) * b['intensity'] * effects_vol * speed_ramp * 2.0
                if b['front_samples_left'] > 0:
                    if not is_reverse: front_sig += w
                    else: rear_sig += w
                    b['front_samples_left'] -= frame_count
                if not b['rear_active'] and now >= b['rear_trigger']: b['rear_active'] = True
                if b['rear_active'] and b['rear_samples_left'] > 0:
                    if not is_reverse: rear_sig += w
                    else: front_sig += w
                    b['rear_samples_left'] -= frame_count
                if b['front_samples_left'] > 0 or b['rear_samples_left'] > 0 or not b['rear_active']: active_bumps.append(b)
            self.bump_queue = active_bumps
            self.phase = (self.phase + (frame_count * step_rad)) % (2 * np.pi)

        return front_sig, rear_sig
