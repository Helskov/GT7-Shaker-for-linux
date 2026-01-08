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


import numpy as np
import random
from .Simulated_Road import RoadSimulator

class AudioProcessor:
    def __init__(self, sample_rate):
        self.sample_rate = sample_rate
        self.road_sim = RoadSimulator(sample_rate)
        self.rpm_phase = 0.0
        self.susp_phase_road = 0.0
        self.susp_phase_imp = 0.0
        self.bump_phase = 0.0
        self.bump_trigger = 0.0
        self.traction_phase_r = 0.0
        self.traction_phase_f = 0.0
        self.smooth_rpm = 1000.0
        self.last_gear = 0
        self.last_susp_pos = [0.0] * 4
        self.last_susp_vel = [0.0] * 4
        self.last_car_vel_y = 0.0
        self.current_gain = 0.0
        self.reduction_smooth = 1.0

    def get_stereo_gain(self, bal):
        bal = float(bal)
        return (1.0, bal * 2.0) if bal <= 0.5 else ((1.0 - bal) * 2.0, 1.0)

    def process(self, data, cfg, frame_count, live_debug, is_muted=False, traction_triggers=(0.0, 0.0)):
        mix_ch0 = np.zeros(frame_count, dtype=np.float32)
        mix_ch1 = np.zeros(frame_count, dtype=np.float32)
        steps = np.arange(frame_count)

        target_gain = 0.0 if is_muted or not data else 1.0
        gain_envelope = np.linspace(self.current_gain, target_gain, frame_count)
        self.current_gain = target_gain

        if not data and self.current_gain == 0:
            return mix_ch0, mix_ch1

        headroom = float(cfg.get('output_headroom', 0.45))
        safe_gain = float(cfg.get('master_volume', 0.5)) * headroom

        # --- 0. BEREGN TRACTION DUCKING (SKAL BRUGES AF BÅDE SUSP & RPM) ---
        trig_f, trig_r = traction_triggers
        max_slip = max(trig_f, trig_r)
        trac_cfg = cfg['effects'].get('traction', {})
        t_priority = trac_cfg.get('priority', False)

        t_duck_full = 1.0 # Bruges til RPM (100% styrke)
        t_duck_half = 1.0 # Bruges til Suspension (50% styrke)

        if t_priority and max_slip > 0.01:
            # Multiplikativ reduktion: Jo mere slip, jo dybere ducking. Max 80% dæmpning.
            t_duck_full = max(0.2, 1.0 - (max_slip * 0.9))
            # Halv reduktion for suspension (50% af traction-effekten)
            t_duck_half = 1.0 - ((1.0 - t_duck_full) * 0.5)

        # --- 1. SUSPENSION (MED DOBBELT DUCKING) ---
        susp_cfg = cfg['effects']['suspension']
        if susp_cfg['enabled'] and data.speed_kmh > 4.0:
            curr = [data.suspension_height_FL, data.suspension_height_FR, data.suspension_height_RL, data.suspension_height_RR]
            if self.last_susp_pos[0] == 0.0: self.last_susp_pos = list(curr)

            active_road_thresh = float(susp_cfg.get('threshold', 0.5)) * 0.012
            real_impact_thresh = (float(susp_cfg.get('impact_threshold', 3.0)) / 40.0) * 0.040
            road_vol_mult = float(susp_cfg.get('road_volume', 1.0))
            impact_vol_mult = float(susp_cfg.get('impact_volume', 1.0))

            r_f, r_r = 0.0, 0.0
            i_f, i_r = 0.0, 0.0

            for i in range(4):
                v = curr[i] - self.last_susp_pos[i]
                a = abs(v - self.last_susp_vel[i])
                self.last_susp_vel[i] = v; self.last_susp_pos[i] = curr[i]
                road_val = (max(0, a - active_road_thresh) * 400.0)**1.2
                imp_val = max(0, a - real_impact_thresh) * 180.0
                if i < 2: r_f += road_val; i_f = max(i_f, imp_val)
                else: r_r += road_val; i_r = max(i_r, imp_val)

            g_body = abs(data.vel_y - self.last_car_vel_y)
            self.last_car_vel_y = data.vel_y
            if g_body > 0.05:
                body_impact = g_body * 15.0; i_f += body_impact; i_r += body_impact

            live_debug['road_noise'] = min((r_f + r_r), 2.0)
            live_debug['g_force'] = min((i_f + i_r), 4.0)

            # Ducking: Impacts (store slag) dæmper Road Rumble (vejstøj)
            priority_enabled = susp_cfg.get('priority', False)
            impact_ducking = max(0.1, 1.0 - (max(i_f, i_r) * 0.25)) if priority_enabled else 1.0

            s_road = 2 * np.pi * 30.0 / self.sample_rate
            t_road = np.sin(self.susp_phase_road + (steps * s_road)) * safe_gain
            self.susp_phase_road = (self.susp_phase_road + (frame_count * s_road)) % (2 * np.pi)

            s_imp = 2 * np.pi * 52.0 / self.sample_rate
            t_imp = np.abs(np.sin(self.susp_phase_imp + (steps * s_imp))) * safe_gain
            self.susp_phase_imp = (self.susp_phase_imp + (frame_count * s_imp)) % (2 * np.pi)

            gR_susp, gF_susp = self.get_stereo_gain(susp_cfg.get('balance', 0.5))

            # KOMBINERET DUCKING: Impact ducking + Traction ducking (halv styrke)
            mix_ch0 += ((t_road * r_r * road_vol_mult * gR_susp * impact_ducking) + (t_imp * i_r * impact_vol_mult * gR_susp)) * t_duck_half
            mix_ch1 += ((t_road * r_f * road_vol_mult * gF_susp * impact_ducking) + (t_imp * i_f * impact_vol_mult * gF_susp)) * t_duck_half
        else:
            live_debug['road_noise'] = 0.0; live_debug['g_force'] = 0.0

        # --- 1.5 SIMULATED ROAD TEXTURE ---
        if cfg['effects']['sim_road'].get('enabled', True):
            sim_cfg = cfg['effects']['sim_road']
            road_f, road_r = self.road_sim.generate_bumps(
                data.speed_kmh, float(sim_cfg.get('roughness', 0.3)),
                float(sim_cfg.get('texture_volume', 0.5)), float(sim_cfg.get('volume', 1.0)),
                float(sim_cfg.get('texture_freq', 30.0)), data.gear == 0, frame_count
            )
            mix_ch0 += road_r * 0.7 * safe_gain
            mix_ch1 += road_f * 0.7 * safe_gain


            live_debug['sim_road'] = float(np.max(np.abs(road_f)) + np.max(np.abs(road_r)))

        # --- 2. ENGINE RPM (KOMPLEKS V8 + SNAPPY GEARS + TRACTION PRIORITY) ---
        rpm_cfg = cfg['effects']['rpm']
        if rpm_cfg['enabled'] and data.engine_rpm > 10.0:
            # GEAR SNAP LOGIK (BEVARET)
            if data.gear != self.last_gear:
                self.smooth_rpm = data.engine_rpm
            else:
                self.smooth_rpm = (self.smooth_rpm * 0.2) + (data.engine_rpm * 0.8)

            max_r = data.car_max_rpm if data.car_max_rpm > 500 else 8000
            rpm_ratio = min(max(self.smooth_rpm, 0) / max_r, 1.0)
            rpm_freq = float(rpm_cfg.get('min_freq', 25.0)) + (rpm_ratio * (float(rpm_cfg.get('max_freq', 90.0)) - float(rpm_cfg.get('min_freq', 25.0))))

            s_rad = 2 * np.pi * rpm_freq / self.sample_rate
            p_buf = self.rpm_phase + (steps * s_rad)
            prof = rpm_cfg.get('profile', 'sine')

            if prof == 'v8':
                # DIN ORIGINALE KOMPLEKSE V8 (BEVARET)
                p = np.sign(np.sin(p_buf)) * (np.abs(np.sin(p_buf))**4.0)
                g = 0.8 * np.sin(p_buf * 0.5) + 0.4 * np.cos(p_buf * 0.25 + 0.5)
                wave = np.tanh((p * (1.0 + 0.5 * g) + (0.5 * np.sin(p_buf * 0.5))) * 1.5)
            elif prof == 'boxer':
                # STABIL BOXER MODULATION (BEVARET)
                modulation = 0.6 + 0.5 * np.sin(p_buf * 0.5)
                wave = np.sin(p_buf) * modulation
            else:
                wave = np.sin(p_buf) + (rpm_ratio * 0.4) * np.sin(p_buf * 2.0)

            self.rpm_phase = (self.rpm_phase + (frame_count * s_rad)) % (2 * np.pi)

            # MULTIPLIKATIV DUCKING: Suspension Prioritet + Traction Prioritet (Fuld)
            target_reduction = 1.0
            if cfg['effects']['suspension'].get('priority', False) and live_debug['g_force'] > 0.1:
                dim_factor = float(cfg['effects']['suspension'].get('rpm_dim', 0.5))
                target_reduction *= (1.0 - (dim_factor * min(live_debug['g_force'], 0.75)))

            target_reduction *= t_duck_full # Traction prioritet påvirker RPM 100%
            self.reduction_smooth = (self.reduction_smooth * 0.8) + (max(0.15, target_reduction) * 0.2)

            drive_vol, idle_vol = float(rpm_cfg.get('volume', 0.5)), float(rpm_cfg.get('pit_boost', 0.8))
            eff_vol = (idle_vol * (1.0 - min(data.speed_kmh / 8.0, 1.0))) + (drive_vol * min(data.speed_kmh / 8.0, 1.0))
            amp = (0.6 + (rpm_ratio ** 1.5) * 0.8) * eff_vol * safe_gain * self.reduction_smooth

            gR_rpm, gF_rpm = self.get_stereo_gain(rpm_cfg.get('balance', 0.5))
            mix_ch0 += wave * amp * gR_rpm; mix_ch1 += wave * amp * gF_rpm

        # --- 3. GEAR SHIFT THUMP ---
        if cfg['effects'].get('gear_shift', {}).get('enabled') and data.gear != self.last_gear:
            self.bump_trigger = 2.5
        if self.bump_trigger > 0:
            b_step = 2 * np.pi * 32.0 / self.sample_rate
            b_wave = np.sin(self.bump_phase + (steps * b_step)) * self.bump_trigger * float(cfg['effects']['gear_shift'].get('volume', 1.0)) * safe_gain
            self.bump_phase = (self.bump_phase + (frame_count * b_step)) % (2 * np.pi)
            gR_gear, gF_gear = self.get_stereo_gain(cfg['effects']['gear_shift'].get('balance', 0.5))
            mix_ch0 += b_wave * gR_gear; mix_ch1 += b_wave * gF_gear
            self.bump_trigger = max(0, self.bump_trigger - 0.15)

        # --- 4. TRACTION & LOCKUP (MED JUSTERBARE FREKVENSER) ---
        if trac_cfg.get('enabled', True):
            r_freq, f_freq = float(trac_cfg.get('rear_freq', 42.0)), float(trac_cfg.get('front_freq', 58.0))
            if trig_r > 0.001: # Rear Wheelspin
                sr = 2 * np.pi * r_freq / self.sample_rate
                mix_ch0 += np.sin(self.traction_phase_r + (steps * sr)) * safe_gain * trig_r * float(trac_cfg.get('volume', 1.0)) * 2.5
                self.traction_phase_r = (self.traction_phase_r + (frame_count * sr)) % (2 * np.pi)
            if trig_f > 0.001: # Front Lockup
                sf = 2 * np.pi * f_freq / self.sample_rate
                mix_ch1 += np.sin(self.traction_phase_f + (steps * sf)) * safe_gain * trig_f * float(trac_cfg.get('volume', 1.0)) * 2.5
                self.traction_phase_f = (self.traction_phase_f + (frame_count * sf)) % (2 * np.pi)

        self.last_gear = data.gear

        # --- 5. OUTPUT ROUTING & LIMITER ---
        if int(cfg.get('shaker_mode', 2)) == 1:
            mono = (mix_ch0 + mix_ch1) * 0.75
            mix_ch0 = mono; mix_ch1 = mono

        l_t = 0.85
        mix_ch0 = np.where(np.abs(mix_ch0) > l_t, np.tanh(mix_ch0), mix_ch0)
        mix_ch1 = np.where(np.abs(mix_ch1) > l_t, np.tanh(mix_ch1), mix_ch1)

        return np.clip(mix_ch0 * gain_envelope, -0.98, 0.98), np.clip(mix_ch1 * gain_envelope, -0.98, 0.98)
