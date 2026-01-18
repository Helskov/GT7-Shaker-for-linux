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

import time, threading, numpy as np, pyaudio
from .network_manager import TurismoClient
from .audio_processor import AudioProcessor

BUFFER_SIZE = 3072
CHANNELS = 2

class ShakerEngine:
    def __init__(self, cfg):
        """ Initializes the shaker engine with full state preservation """
        self.cfg = cfg
        self.running = False
        self.thread_active = False

        self.chosen_rate = int(self.cfg['audio'].get('sample_rate', 48000))
        self.processor = AudioProcessor(self.chosen_rate)

        self.current_data = None
        self.live_debug = {'road_noise': 0.0, 'g_force': 0.0, 'sim_road': 0.0}

        # Shared triggers for the web API
        self.last_traction_triggers = (0.0, 0.0)

        # Timers
        self.last_packet_time = time.time()
        self.last_rpm_val = -1.0
        self.last_speed_val = -1.0
        self.last_data_change_time = time.time()
        self.stagnation_timeout = 1.5

        # Watchdog Timer init
        self.last_audio_callback_time = time.time()

        # Placeholder for external processors injected via web_app
        self.tire_processor = None

    def _start_audio_stream(self, pa):
        """ Helper to start/restart the audio stream cleanly """
        try:
            idx = self.cfg['audio'].get('device_index', -1)
            stream = pa.open(
                format=pyaudio.paFloat32,
                channels=CHANNELS,
                rate=self.chosen_rate,
                output=True,
                output_device_index=None if idx == -1 else idx,
                stream_callback=self.audio_callback,
                frames_per_buffer=BUFFER_SIZE
            )
            stream.start_stream()
            # Reset watchdog on start
            self.last_audio_callback_time = time.time()
            print("INFO: Audio stream started (Fresh Connection).")
            return stream
        except Exception as e:
            print(f"ERROR: Failed to start audio stream: {e}")
            return None

    def run(self, target_ip):
        """ Main engine loop with Dynamic Stream Management """
        self.thread_active = True
        self.running = True

        pa = pyaudio.PyAudio()
        stream = None

        self.client = TurismoClient(target_ip)
        self.client.start()

        # Initialize timers
        self.last_packet_time = time.time()

        try:
            while self.running:
                now = time.time()

                # Fetch data from network
                new_telem = self.client.telemetry

                if new_telem is not None:
                    self.last_packet_time = now
                    self.current_data = new_telem
                    self.client.telemetry = None # Clear buffer

                    # Stagnation check (Track change / Pause menu detection)
                    if abs(new_telem.engine_rpm - self.last_rpm_val) > 0.1 or abs(new_telem.speed_kmh - self.last_speed_val) > 0.1:
                        self.last_rpm_val = new_telem.engine_rpm
                        self.last_speed_val = new_telem.speed_kmh
                        self.last_data_change_time = now

                # --- DYNAMIC STREAM LOGIC ---
                time_since_data = now - self.last_packet_time

                if time_since_data < 10.0:
                    # SITUATION A: We are "Live" (Data is less than 10s old)

                    # 1. Ensure stream is running
                    if stream is None or not stream.is_active():
                        print("Creating new audio stream (Wake Up)...")
                        if stream:
                            try: stream.close()
                            except: pass
                        stream = self._start_audio_stream(pa)

                    # 2. WATCHDOG CHECK
                    # If stream SHOULD be running but hasn't called back in 2.0s
                    time_since_audio = now - self.last_audio_callback_time
                    if stream is not None and time_since_audio > 2.0:
                        print(f"WATCHDOG: Audio froze for {time_since_audio:.2f}s! Force restarting...")
                        try:
                            stream.stop_stream()
                            stream.close()
                        except: pass
                        stream = self._start_audio_stream(pa)

                else:
                    # SITUATION B: No data for 10s -> Sleep Mode
                    if stream is not None:
                        print("No data for 10s. Closing audio stream (Sleep Mode).")
                        try:
                            stream.stop_stream()
                            stream.close()
                        except: pass
                        stream = None

                # Short sleep to save CPU in main loop
                time.sleep(0.01)

        except Exception as e:
            print(f"AUDIO ENGINE CRITICAL ERROR: {e}")
        finally:
            self.running = False
            if stream:
                try: stream.stop_stream(); stream.close()
                except: pass
            if hasattr(self, 'client') and self.client:
                self.client.stop()
            pa.terminate()
            self.thread_active = False

    def audio_callback(self, in_data, frame_count, time_info, status):
        """ Callback runs only when stream is open (i.e., when we have data) """
        try:
            now = time.time()
            self.last_audio_callback_time = now

            d = self.current_data
            allow_replays = self.cfg.get('allow_replays', False)

            # --- MUTE LOGIC ---
            if allow_replays:
                # REPLAY MODE (Permissive)
                # If replays are allowed, we ignore 'Paused' and 'In Race' flags.
                # We only mute if the engine stops or game is loading (black screen).
                should_be_silent = (
                    not self.running or
                    d is None or
                    getattr(d, 'is_loading', False)
                )
            else:
                # NORMAL MODE (Strict)
                # Standard racing behavior: Mute on Pause, Menu, Replay or Loading.
                should_be_silent = (
                    not self.running or
                    d is None or
                    d.is_paused or
                    getattr(d, 'is_loading', False) or
                    not d.in_race
                )

            # If silence is required, return empty buffer immediately
            if should_be_silent:
                return (np.zeros(frame_count * CHANNELS, dtype=np.float32).tobytes(), pyaudio.paContinue)

            # Stagnation Check (Safety: If data values haven't changed for 1.5s, mute)
            # This handles the case where you pause the replay (values stop changing).
            is_stagnant = (now - self.last_data_change_time > self.stagnation_timeout)

            if is_stagnant:
                return (np.zeros(frame_count * CHANNELS, dtype=np.float32).tobytes(), pyaudio.paContinue)

            # --- DATA PROCESSING ---

            # 1. Tire Physics (Get TC and ABS values)
            tc_f, tc_r, abs_f, abs_r = 0.0, 0.0, 0.0, 0.0

            if hasattr(self, 'tire_processor') and self.tire_processor:
                try:
                    # Expects 4 values now (TC_F, TC_R, ABS_F, ABS_R)
                    tc_f, tc_r, abs_f, abs_r = self.tire_processor.get_traction_triggers(d)
                except Exception:
                    tc_f, tc_r, abs_f, abs_r = 0.0, 0.0, 0.0, 0.0

                # Save for Web API (Combine TC and ABS for simple visualization)
                self.last_traction_triggers = (max(tc_f, abs_f), max(tc_r, abs_r))

            # Combine triggers for the audio engine
            trig_f = max(tc_f, abs_f)
            trig_r = max(tc_r, abs_r)

            # Determine braking state for ABS sound logic
            is_braking = d.brake > 0

            # 2. Audio Generation
            ch0, ch1 = self.processor.process(
                self.current_data, self.cfg, frame_count, self.live_debug,
                is_muted=False, # Mute is handled by returns above
                traction_triggers=(trig_f, trig_r),
                is_braking=is_braking
            )

            # Interleave stereo channels
            return (np.column_stack((ch0, ch1)).flatten().astype(np.float32).tobytes(), pyaudio.paContinue)

        except Exception as e:
            # Failsafe silence
            return (np.zeros(frame_count * CHANNELS, dtype=np.float32).tobytes(), pyaudio.paContinue)
