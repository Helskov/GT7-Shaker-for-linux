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
from .Simulated_Road import RoadSimulator

try:
    from numba import njit
except ImportError:
    def njit(f=None, *args, **kwargs):
        if callable(f): return f
        def decorator(func): return func
        return decorator

# --- JIT KERNELS (Uændret) ---
@njit(fastmath=True, cache=True)
def jit_suspension_logic(curr, last_pos, last_vel, road_thresh, impact_thresh):
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
    if profile_idx == 1:
        p = np.sign(np.sin(p_buf)) * (np.abs(np.sin(p_buf))**4.0)
        g = 0.8 * np.sin(p_buf * 0.5) + 0.4 * np.cos(p_buf * 0.25 + 0.5)
        return np.tanh((p * (1.0 + 0.5 * g) + (0.5 * np.sin(p_buf * 0.5))) * 1.5)
    elif profile_idx == 2:
        return np.sin(p_buf) * (0.6 + 0.5 * np.sin(p_buf * 0.5))
    else:
        return np.sin(p_buf) + (rpm_ratio * 0.4) * np.sin(p_buf * 2.0)

@njit(fastmath=True, cache=True)
def jit_limiter(ch0, ch1, threshold=0.85):
    c0 = np.where(np.abs(ch0) > threshold, np.tanh(ch0), ch0)
    c1 = np.where(np.abs(ch1) > threshold, np.tanh(ch1), ch1)
    return c0, c1

class AudioProcessor:
    def __init__(self, sample_rate):
        self.sample_rate = sample_rate
        self.road_sim = RoadSimulator(sample_rate)
        self.steps_cache = np.arange(2048, dtype=np.float32)
        self.steps_cache_large = np.arange(3072, dtype=np.float32)

        self.rpm_phase = 0.0; self.susp_phase_road = 0.0; self.susp_phase_imp = 0.0
        self.bump_phase = 0.0; self.bump_trigger = 0.0; self.traction_phase_r = 0.0
        self.traction_phase_f = 0.0; self.smooth_rpm = 1000.0; self.last_gear = 0
        self.last_susp_pos = np.zeros(4, dtype=np.float32)
        self.last_susp_vel = np.zeros(4, dtype=np.float32)
        self.last_car_vel_y = 0.0; self.current_gain = 0.0

        # Ducking State Variables
        self.reduction_smooth = 1.0     # Engine generic ducking
        self.traction_duck_smooth = 1.0 # Traction ducking (High Prio)
        self.susp_duck_smooth = 1.0     # Suspension ducking (Mid Prio)

        self.impact_f_trigger = 0.0
        self.impact_r_trigger = 0.0
        self.last_accel_z = 0.0

    def get_stereo_gain(self, bal):
        bal = float(bal); return (1.0, bal * 2.0) if bal <= 0.5 else ((1.0 - bal) * 2.0, 1.0)

    def process(self, data, cfg, frame_count, live_debug, is_muted=False, traction_triggers=(0.0, 0.0), is_braking=False):
        mix_ch0 = np.zeros(frame_count, dtype=np.float32)
        mix_ch1 = np.zeros(frame_count, dtype=np.float32)

        # Cache management
        if frame_count == 2048: steps = self.steps_cache
        elif frame_count == 3072: steps = self.steps_cache_large
        else: steps = np.arange(frame_count, dtype=np.float32)

        target_gain = 0.0 if is_muted or not data else 1.0
        gain_envelope = np.linspace(self.current_gain, target_gain, frame_count)
        self.current_gain = target_gain
        if not data and self.current_gain == 0: return mix_ch0, mix_ch1

        headroom = float(cfg.get('output_headroom', 0.45))
        safe_gain = float(cfg.get('master_volume', 0.5)) * headroom

        # ==========================================================
        # 1. HIERARKI BEREGNING (Priority Logic)
        # ==========================================================

        # --- A. TRACTION LOSS (Highest Priority) ---
        trig_f, trig_r = traction_triggers
        max_slip = max(trig_f, trig_r)
        trac_cfg = cfg['effects'].get('traction', {})

        # Beregn Traction Ducking (Hvor meget skal vi dæmpe ALT andet?)
        target_trac_duck = 1.0
        if trac_cfg.get('priority') and max_slip > 0.01:
            # 1.0 = Ingen dæmpning, 0.2 = Max dæmpning
            target_trac_duck = max(0.2, 1.0 - (max_slip * 2.0))

        self.traction_duck_smooth = (self.traction_duck_smooth * 0.85) + (target_trac_duck * 0.15)
        duck_from_traction = self.traction_duck_smooth


        # ==========================================================
        # 2. EFFEKT GENERERING
        # ==========================================================

        # --- IMPACT (Uheld/Kanter - Duckes IKKE) ---
        obs_cfg = cfg['effects'].get('obstacle_impact', {'enabled': True, 'volume': 1.0, 'threshold': 50.0})
        if obs_cfg['enabled'] and not is_muted:
            surge = getattr(data, 'surge_g', 0.0)
            sway  = getattr(data, 'sway_g', 0.0)
            thresh = float(obs_cfg.get('threshold', 50.0))
            scale_factor = 0.05

            if surge < -thresh:
                self.impact_f_trigger = max(self.impact_f_trigger, min(5.0, (abs(surge) - thresh) * scale_factor))
            elif surge > thresh:
                self.impact_r_trigger = max(self.impact_r_trigger, min(5.0, (abs(surge) - thresh) * scale_factor))
            if abs(sway) > thresh:
                side_val = min(5.0, (abs(sway) - thresh) * scale_factor)
                self.impact_f_trigger = max(self.impact_f_trigger, side_val)
                self.impact_r_trigger = max(self.impact_r_trigger, side_val)

        if self.impact_f_trigger > 0 or self.impact_r_trigger > 0:
            imp_freq = float(obs_cfg.get('freq', 30.0))
            imp_step = 2 * np.pi * imp_freq / self.sample_rate
            imp_vol = float(obs_cfg.get('volume', 1.0)) * safe_gain

            # Impact duckes ikke af nogen (det er en "ulykke")
            if self.impact_f_trigger > 0:
                mix_ch0 += np.sin(self.bump_phase + (steps * imp_step)) * self.impact_f_trigger * imp_vol
                self.impact_f_trigger = max(0, self.impact_f_trigger - 0.5)
            if self.impact_r_trigger > 0:
                mix_ch1 += np.sin(self.bump_phase + (steps * imp_step)) * self.impact_r_trigger * imp_vol
                self.impact_r_trigger = max(0, self.impact_r_trigger - 0.5)
            self.bump_phase = (self.bump_phase + (frame_count * imp_step)) % (2 * np.pi)

        # --- 1. SUSPENSION ---
        # (Ducks Engine/Road via 'duck_from_suspension', Ducked by Traction via 'duck_from_traction')
        susp_cfg = cfg['effects']['suspension']
        target_susp_duck = 1.0

        if susp_cfg['enabled'] and data.speed_kmh > 4.0:
            curr_susp = np.array([data.suspension_height_FL, data.suspension_height_FR, data.suspension_height_RL, data.suspension_height_RR], dtype=np.float32)
            r_f, r_r, i_f, i_r, self.last_susp_pos, self.last_susp_vel = jit_suspension_logic(
                curr_susp, self.last_susp_pos, self.last_susp_vel,
                float(susp_cfg.get('threshold', 0.5)) * 0.012,
                (float(susp_cfg.get('impact_threshold', 3.0)) / 40.0) * 0.040
            )
            g_body = abs(data.vel_y - self.last_car_vel_y); self.last_car_vel_y = data.vel_y
            if g_body > 0.05: i_f += g_body * 15.0; i_r += g_body * 15.0

            # --- NY DUCKING LOGIK (Noise Gated Impact) ---
            total_impact = i_f + i_r

            # Noise Gate: Ignorer impacts under 0.5 (små bump trigger ikke ducking)
            if total_impact < 0.5:
                susp_activity = 0.0
            else:
                # Skaler aktiviteten ned en smule, så den ikke er for aggressiv
                susp_activity = min(total_impact, 6.0)

            # Debug data viser stadig både road og impact til grafen
            live_debug['road_noise'] = min(r_f + r_r, 2.0); live_debug['g_force'] = min(i_f + i_r, 4.0)

            # Beregn ducking faktor (kun baseret på IMPACT nu)
            if susp_cfg.get('priority'):
                dim_strength = float(susp_cfg.get('rpm_dim', 0.5))
                # Formel: 1.0 minus (Styrke * Impact)
                target_susp_duck = 1.0 - (dim_strength * min(susp_activity * 0.3, 0.8))

            s_road = 2 * np.pi * 30.0 / self.sample_rate
            t_road = np.sin(self.susp_phase_road + (steps * s_road)) * safe_gain
            self.susp_phase_road = (self.susp_phase_road + (frame_count * s_road)) % (2 * np.pi)
            s_imp = 2 * np.pi * 52.0 / self.sample_rate
            t_imp = np.abs(np.sin(self.susp_phase_imp + (steps * s_imp))) * safe_gain
            self.susp_phase_imp = (self.susp_phase_imp + (frame_count * s_imp)) % (2 * np.pi)
            gR_susp, gF_susp = self.get_stereo_gain(susp_cfg.get('balance', 0.5))

            # PÅFØR TRACTION DUCKING PÅ SUSPENSION
            # Suspension bliver KUN dæmpet af Traction Loss (duck_from_traction)
            susp_vol = float(susp_cfg.get('road_volume', 1.0)) * duck_from_traction
            imp_vol = float(susp_cfg.get('impact_volume', 1.0)) * duck_from_traction

            mix_ch0 += ((t_road * r_r * susp_vol * gR_susp) + (t_imp * i_r * imp_vol * gR_susp))
            mix_ch1 += ((t_road * r_f * susp_vol * gF_susp) + (t_imp * i_f * imp_vol * gF_susp))

        # Opdater Suspension Ducking Smooth (Sender værdien videre til Engine/Road sektionerne)
        self.susp_duck_smooth = (self.susp_duck_smooth * 0.8) + (target_susp_duck * 0.2)
        duck_from_suspension = self.susp_duck_smooth
        # Opdater Suspension Ducking Smooth
        self.susp_duck_smooth = (self.susp_duck_smooth * 0.8) + (target_susp_duck * 0.2)
        duck_from_suspension = self.susp_duck_smooth

        # --- SIM ROAD (Ducked by Traction AND Suspension) ---
        if cfg['effects']['sim_road'].get('enabled', True):
            sim_cfg = cfg['effects']['sim_road']
            road_f, road_r = self.road_sim.generate_bumps(
                data.speed_kmh, float(sim_cfg.get('roughness', 0.3)),
                float(sim_cfg.get('texture_volume', 0.5)), float(sim_cfg.get('volume', 1.0)),
                float(sim_cfg.get('texture_freq', 30.0)), data.gear == 0, frame_count
            )

            # PÅFØR DOBBELT DUCKING (Traction * Suspension)
            # Hvis Traction siger 0.2 og Susp siger 0.5 -> Road får 0.1 (Meget stille)
            road_duck_factor = duck_from_traction * duck_from_suspension

            mix_ch0 += road_r * 0.7 * safe_gain * road_duck_factor
            mix_ch1 += road_f * 0.7 * safe_gain * road_duck_factor
            live_debug['sim_road'] = float(np.max(np.abs(road_f)) + np.max(np.abs(road_r)))

        # --- ENGINE (Ducked by Traction AND Suspension) ---
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

            # PÅFØR DOBBELT DUCKING (Traction * Suspension)
            total_duck_factor = duck_from_traction * duck_from_suspension

            # Smooth overgangen en smule mere for motorlyden for at undgå "hak"
            self.reduction_smooth = (self.reduction_smooth * 0.8) + (max(0.15, total_duck_factor) * 0.2)

            eff_vol = (float(rpm_cfg.get('pit_boost', 0.8)) * (1.0 - min(data.speed_kmh / 8.0, 1.0))) + (float(rpm_cfg.get('volume', 0.5)) * min(data.speed_kmh / 8.0, 1.0))
            amp = (0.6 + (rpm_ratio ** 1.5) * 0.8) * eff_vol * safe_gain * self.reduction_smooth
            gR_rpm, gF_rpm = self.get_stereo_gain(rpm_cfg.get('balance', 0.5))
            mix_ch0 += wave * amp * gR_rpm; mix_ch1 += wave * amp * gF_rpm

        # --- GEAR SHIFT (Ducked by Traction) ---
        if cfg['effects'].get('gear_shift', {}).get('enabled') and data.gear != self.last_gear: self.bump_trigger = 2.5
        if self.bump_trigger > 0:
            b_step = 2 * np.pi * 32.0 / self.sample_rate
            # Gear shift skal mærkes, men vi lader Traction loss ducke den lidt, hvis det går helt galt
            gear_duck = max(0.5, duck_from_traction)
            b_wave = np.sin(self.bump_phase + (steps * b_step)) * self.bump_trigger * float(cfg['effects']['gear_shift'].get('volume', 1.0)) * safe_gain * gear_duck
            self.bump_phase = (self.bump_phase + (frame_count * b_step)) % (2 * np.pi)
            gR_gear, gF_gear = self.get_stereo_gain(cfg['effects']['gear_shift'].get('balance', 0.5))
            mix_ch0 += b_wave * gR_gear; mix_ch1 += b_wave * gF_gear
            self.bump_trigger = max(0, self.bump_trigger - 0.15)

        # --- TRACTION / ABS (Ingen ducking - den er kongen) ---
        if trac_cfg.get('enabled', True):
            # Hent altid frekvenserne fra din config (skyderne)
            f_freq = float(trac_cfg.get('front_freq', 58.0))
            r_freq = float(trac_cfg.get('rear_freq', 42.0))

            if is_braking:
                # Vi beholder volumen-boostet ved bremsning, da ABS skal være kraftig
                t_vol = float(trac_cfg.get('volume', 0.8)) * safe_gain * 1.2
            else:
                t_vol = float(trac_cfg.get('volume', 0.8)) * safe_gain

            if trig_r > 0.001:
                sr = 2 * np.pi * r_freq / self.sample_rate
                wave = np.sin(self.traction_phase_r + (steps * sr))
                if is_braking: wave = np.sign(wave) * 0.5 + wave * 0.5
                mix_ch0 += wave * t_vol * trig_r * 3.0
                self.traction_phase_r = (self.traction_phase_r + (frame_count * sr)) % (2 * np.pi)
            if trig_f > 0.001:
                sf = 2 * np.pi * f_freq / self.sample_rate
                wave = np.sin(self.traction_phase_f + (steps * sf))
                if is_braking: wave = np.sign(wave) * 0.5 + wave * 0.5
                mix_ch1 += wave * t_vol * trig_f * 3.0
                self.traction_phase_f = (self.traction_phase_f + (frame_count * sf)) % (2 * np.pi)

        self.last_gear = data.gear
        mix_ch0, mix_ch1 = jit_limiter(mix_ch0, mix_ch1, 0.85)
        return np.clip(mix_ch0 * gain_envelope, -0.98, 0.98), np.clip(mix_ch1 * gain_envelope, -0.98, 0.98)
