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
from .Simulated_Road import RoadSimulator

try:
    from numba import njit
except ImportError:
    def njit(f=None, *args, **kwargs):
        if callable(f): return f
        def decorator(func): return func
        return decorator

# --- JIT OPTIMIZED DSP KERNELS ---

@njit(fastmath=True, cache=True)
def jit_suspension_logic(curr, last_pos, last_vel, road_thresh, impact_thresh):
    """ High-performance 4-wheel suspension analyzer """
    r_f, r_r, i_f, i_r = 0.0, 0.0, 0.0, 0.0
    new_pos = np.zeros(4, dtype=np.float32)
    new_vel = np.zeros(4, dtype=np.float32)

    for i in range(4):
        v = curr[i] - last_pos[i]
        a = np.abs(v - last_vel[i])
        new_vel[i] = v; new_pos[i] = curr[i]

        road_val = (np.maximum(0.0, a - road_thresh) * 400.0)**1.2
        imp_val = np.maximum(0.0, a - impact_thresh) * 180.0

        if i < 2: r_f += road_val; i_f = np.maximum(i_f, imp_val)
        else: r_r += road_val; i_r = np.maximum(i_r, imp_val)

    return r_f, r_r, i_f, i_r, new_pos, new_vel

@njit(fastmath=True, cache=True)
def jit_engine_core(p_buf, profile_idx, rpm_ratio):
    """ V8, Boxer and Sine synthesis in machine code """
    if profile_idx == 1: # v8
        p = np.sign(np.sin(p_buf)) * (np.abs(np.sin(p_buf))**4.0)
        g = 0.8 * np.sin(p_buf * 0.5) + 0.4 * np.cos(p_buf * 0.25 + 0.5)
        return np.tanh((p * (1.0 + 0.5 * g) + (0.5 * np.sin(p_buf * 0.5))) * 1.5)
    elif profile_idx == 2: # boxer
        return np.sin(p_buf) * (0.6 + 0.5 * np.sin(p_buf * 0.5))
    else: # sine
        return np.sin(p_buf) + (rpm_ratio * 0.4) * np.sin(p_buf * 2.0)

@njit(fastmath=True, cache=True)
def jit_limiter(ch0, ch1, threshold=0.85):
    """ Fast soft-limiter """
    c0 = np.where(np.abs(ch0) > threshold, np.tanh(ch0), ch0)
    c1 = np.where(np.abs(ch1) > threshold, np.tanh(ch1), ch1)
    return c0, c1

class AudioProcessor:
    def __init__(self, sample_rate):
        self.sample_rate = sample_rate
        self.road_sim = RoadSimulator(sample_rate)
        # Pre-allocate cached steps array
        self.steps_cache = np.arange(2048, dtype=np.float32)
        self.rpm_phase = 0.0; self.susp_phase_road = 0.0; self.susp_phase_imp = 0.0
        self.bump_phase = 0.0; self.bump_trigger = 0.0; self.traction_phase_r = 0.0
        self.traction_phase_f = 0.0; self.smooth_rpm = 1000.0; self.last_gear = 0
        self.last_susp_pos = np.zeros(4, dtype=np.float32)
        self.last_susp_vel = np.zeros(4, dtype=np.float32)
        self.last_car_vel_y = 0.0; self.current_gain = 0.0; self.reduction_smooth = 1.0

    def get_stereo_gain(self, bal):
        bal = float(bal); return (1.0, bal * 2.0) if bal <= 0.5 else ((1.0 - bal) * 2.0, 1.0)

    def process(self, data, cfg, frame_count, live_debug, is_muted=False, traction_triggers=(0.0, 0.0)):
        mix_ch0 = np.zeros(frame_count, dtype=np.float32)
        mix_ch1 = np.zeros(frame_count, dtype=np.float32)
        steps = self.steps_cache if frame_count == 2048 else np.arange(frame_count, dtype=np.float32)

        target_gain = 0.0 if is_muted or not data else 1.0
        gain_envelope = np.linspace(self.current_gain, target_gain, frame_count)
        self.current_gain = target_gain
        if not data and self.current_gain == 0: return mix_ch0, mix_ch1

        headroom = float(cfg.get('output_headroom', 0.45))
        safe_gain = float(cfg.get('master_volume', 0.5)) * headroom

        # --- 0. TRACTION DUCKING ---
        trig_f, trig_r = traction_triggers
        max_slip = max(trig_f, trig_r)
        trac_cfg = cfg['effects'].get('traction', {})
        t_duck_full = max(0.2, 1.0 - (max_slip * 0.9)) if (trac_cfg.get('priority') and max_slip > 0.01) else 1.0

        # --- 1. SUSPENSION (JIT Optimized) ---
        susp_cfg = cfg['effects']['suspension']
        if susp_cfg['enabled'] and data.speed_kmh > 4.0:
            curr_susp = np.array([data.suspension_height_FL, data.suspension_height_FR, data.suspension_height_RL, data.suspension_height_RR], dtype=np.float32)
            r_f, r_r, i_f, i_r, self.last_susp_pos, self.last_susp_vel = jit_suspension_logic(
                curr_susp, self.last_susp_pos, self.last_susp_vel,
                float(susp_cfg.get('threshold', 0.5)) * 0.012,
                (float(susp_cfg.get('impact_threshold', 3.0)) / 40.0) * 0.040
            )
            # Body motion
            g_body = abs(data.vel_y - self.last_car_vel_y); self.last_car_vel_y = data.vel_y
            if g_body > 0.05: i_f += g_body * 15.0; i_r += g_body * 15.0

            live_debug['road_noise'] = min(r_f + r_r, 2.0); live_debug['g_force'] = min(i_f + i_r, 4.0)

            s_road = 2 * np.pi * 30.0 / self.sample_rate
            t_road = np.sin(self.susp_phase_road + (steps * s_road)) * safe_gain
            self.susp_phase_road = (self.susp_phase_road + (frame_count * s_road)) % (2 * np.pi)

            s_imp = 2 * np.pi * 52.0 / self.sample_rate
            t_imp = np.abs(np.sin(self.susp_phase_imp + (steps * s_imp))) * safe_gain
            self.susp_phase_imp = (self.susp_phase_imp + (frame_count * s_imp)) % (2 * np.pi)

            gR_susp, gF_susp = self.get_stereo_gain(susp_cfg.get('balance', 0.5))
            mix_ch0 += ((t_road * r_r * float(susp_cfg.get('road_volume', 1.0)) * gR_susp) + (t_imp * i_r * float(susp_cfg.get('impact_volume', 1.0)) * gR_susp))
            mix_ch1 += ((t_road * r_f * float(susp_cfg.get('road_volume', 1.0)) * gF_susp) + (t_imp * i_f * float(susp_cfg.get('impact_volume', 1.0)) * gF_susp))

        # --- 1.5 SIM ROAD TEXTURE ---
        if cfg['effects']['sim_road'].get('enabled', True):
            sim_cfg = cfg['effects']['sim_road']
            road_f, road_r = self.road_sim.generate_bumps(
                data.speed_kmh, float(sim_cfg.get('roughness', 0.3)),
                float(sim_cfg.get('texture_volume', 0.5)), float(sim_cfg.get('volume', 1.0)),
                float(sim_cfg.get('texture_freq', 30.0)), data.gear == 0, frame_count
            )
            mix_ch0 += road_r * 0.7 * safe_gain; mix_ch1 += road_f * 0.7 * safe_gain
            live_debug['sim_road'] = float(np.max(np.abs(road_f)) + np.max(np.abs(road_r)))

        # --- 2. ENGINE (JIT Core) ---
        rpm_cfg = cfg['effects']['rpm']
        if rpm_cfg['enabled'] and data.engine_rpm > 10.0:
            if data.gear != self.last_gear: self.smooth_rpm = data.engine_rpm
            else: self.smooth_rpm = (self.smooth_rpm * 0.2) + (data.engine_rpm * 0.8)

            rpm_ratio = min(max(self.smooth_rpm, 0) / (data.car_max_rpm or 8000), 1.0)
            rpm_freq = float(rpm_cfg.get('min_freq', 25.0)) + (rpm_ratio * (float(rpm_cfg.get('max_freq', 90.0)) - float(rpm_cfg.get('min_freq', 25.0))))
            s_rad = 2 * np.pi * rpm_freq / self.sample_rate
            p_idx = 1 if rpm_cfg.get('profile') == 'v8' else (2 if rpm_cfg.get('profile') == 'boxer' else 0)

            wave = jit_engine_core(self.rpm_phase + (steps * s_rad), p_idx, rpm_ratio)
            self.rpm_phase = (self.rpm_phase + (frame_count * s_rad)) % (2 * np.pi)

            target_red = t_duck_full
            if susp_cfg.get('priority') and live_debug['g_force'] > 0.1:
                target_red *= (1.0 - (float(susp_cfg.get('rpm_dim', 0.5)) * min(live_debug['g_force'], 0.75)))
            self.reduction_smooth = (self.reduction_smooth * 0.8) + (max(0.15, target_red) * 0.2)

            eff_vol = (float(rpm_cfg.get('pit_boost', 0.8)) * (1.0 - min(data.speed_kmh / 8.0, 1.0))) + (float(rpm_cfg.get('volume', 0.5)) * min(data.speed_kmh / 8.0, 1.0))
            amp = (0.6 + (rpm_ratio ** 1.5) * 0.8) * eff_vol * safe_gain * self.reduction_smooth
            gR_rpm, gF_rpm = self.get_stereo_gain(rpm_cfg.get('balance', 0.5))
            mix_ch0 += wave * amp * gR_rpm; mix_ch1 += wave * amp * gF_rpm

        # --- 3. GEAR SHIFT ---
        if cfg['effects'].get('gear_shift', {}).get('enabled') and data.gear != self.last_gear: self.bump_trigger = 2.5
        if self.bump_trigger > 0:
            b_step = 2 * np.pi * 32.0 / self.sample_rate
            b_wave = np.sin(self.bump_phase + (steps * b_step)) * self.bump_trigger * float(cfg['effects']['gear_shift'].get('volume', 1.0)) * safe_gain
            self.bump_phase = (self.bump_phase + (frame_count * b_step)) % (2 * np.pi)
            gR_gear, gF_gear = self.get_stereo_gain(cfg['effects']['gear_shift'].get('balance', 0.5))
            mix_ch0 += b_wave * gR_gear; mix_ch1 += b_wave * gF_gear
            self.bump_trigger = max(0, self.bump_trigger - 0.15)

        # --- 4. TRACTION FREQUENCIES ---
        if trac_cfg.get('enabled', True):
            if trig_r > 0.001:
                sr = 2 * np.pi * float(trac_cfg.get('rear_freq', 42.0)) / self.sample_rate
                mix_ch0 += np.sin(self.traction_phase_r + (steps * sr)) * safe_gain * trig_r * float(trac_cfg.get('volume', 1.0)) * 2.5
                self.traction_phase_r = (self.traction_phase_r + (frame_count * sr)) % (2 * np.pi)
            if trig_f > 0.001:
                sf = 2 * np.pi * float(trac_cfg.get('front_freq', 58.0)) / self.sample_rate
                mix_ch1 += np.sin(self.traction_phase_f + (steps * sf)) * safe_gain * trig_f * float(trac_cfg.get('volume', 1.0)) * 2.5
                self.traction_phase_f = (self.traction_phase_f + (frame_count * sf)) % (2 * np.pi)

        self.last_gear = data.gear
        mix_ch0, mix_ch1 = jit_limiter(mix_ch0, mix_ch1, 0.85)
        return np.clip(mix_ch0 * gain_envelope, -0.98, 0.98), np.clip(mix_ch1 * gain_envelope, -0.98, 0.98)
