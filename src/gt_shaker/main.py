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

# GT7 Shaker for Linux 1.30
# Copyright (C) 2026 Soeren Helskov
# https://github.com/Helskov/GT7-Shaker-for-linux

import time, threading, numpy as np, pyaudio
from .network_manager import TurismoClient
from .audio_processor import AudioProcessor

BUFFER_SIZE = 2048
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
        self.last_packet_time = time.time() # Start med nuværende tid
        self.last_rpm_val = -1.0
        self.last_speed_val = -1.0
        self.last_data_change_time = time.time()
        self.stagnation_timeout = 1.5

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

        # Initialiser tidspunkter så den ikke timer ud med det samme
        self.last_packet_time = time.time()

        try:
            while self.running:
                now = time.time()

                # Hent data fra netværk
                new_telem = self.client.telemetry

                if new_telem is not None:

                    self.last_packet_time = now
                    self.current_data = new_telem
                    self.client.telemetry = None # Ryd buffer

                    # Stagnation check (Baneskift/Pause menu)
                    if abs(new_telem.engine_rpm - self.last_rpm_val) > 0.1 or abs(new_telem.speed_kmh - self.last_speed_val) > 0.1:
                        self.last_rpm_val = new_telem.engine_rpm
                        self.last_speed_val = new_telem.speed_kmh
                        self.last_data_change_time = now

                # --- DYNAMIC STREAM LOGIC ---
                time_since_data = now - self.last_packet_time

                if time_since_data < 10.0:
                    # SITUATION A: Vi er "Live" (Data er mindre end 10 sek gammel)
                    # Sørg for at streamen kører!
                    if stream is None or not stream.is_active():
                        print("Creating new audio stream (Wake Up)...")
                        if stream:
                            try: stream.close()
                            except: pass
                        stream = self._start_audio_stream(pa)

                else:

                    # Luk streamen for at frigive lydkortet og undgå zombie-tilstand
                    if stream is not None:
                        print("No data for 10s. Closing audio stream (Sleep Mode).")
                        try:
                            stream.stop_stream()
                            stream.close()
                        except: pass
                        stream = None

                # Kort pause for CPU venlighed
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
        """ Callback kører kun når streamen er åben (dvs. når vi har data) """
        try:
            now = time.time()



            # Tjek kun for stagnation (baneskift/pause-menu)
            is_stagnant = (now - self.last_data_change_time > self.stagnation_timeout)

            mute_condition = not self.running or is_stagnant

            if not self.current_data or mute_condition:
                return (np.zeros(frame_count * CHANNELS, dtype=np.float32).tobytes(), pyaudio.paContinue)

            # --- PROCESSERING ---
            trig_f, trig_r = 0.0, 0.0
            if hasattr(self, 'tire_processor') and self.tire_processor:
                try:
                    trig_f, trig_r = self.tire_processor.get_traction_triggers(self.current_data)
                except Exception:
                    trig_f, trig_r = 0.0, 0.0
                self.last_traction_triggers = (trig_f, trig_r)

            ch0, ch1 = self.processor.process(
                self.current_data, self.cfg, frame_count, self.live_debug,
                is_muted=mute_condition, traction_triggers=(trig_f, trig_r)
            )

            return (np.column_stack((ch0, ch1)).flatten().astype(np.float32).tobytes(), pyaudio.paContinue)

        except Exception as e:
            return (np.zeros(frame_count * CHANNELS, dtype=np.float32).tobytes(), pyaudio.paContinue)
