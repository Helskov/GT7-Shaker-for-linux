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
import pyaudio

def play_test_tone(cfg, side):
    """ 
    Hardware verification function.
    Generates a short 60Hz burst for testing rear/front shaker output.
    """
    pa = pyaudio.PyAudio()
    idx = cfg['audio'].get('device_index', -1)
    rate = int(cfg['audio'].get('sample_rate', 48000))
    vol = float(cfg.get('master_volume', 0.5))
    buffer_size = 2048
    
    try:
        stream = pa.open(
            format=pyaudio.paFloat32, 
            channels=2, 
            rate=rate, 
            output=True, 
            output_device_index=None if idx == -1 else idx
        )
        steps = np.arange(buffer_size)
        phase = 0.0
        trigger = 1.0
        
        # Generate 25 buffers of fading 60Hz tone
        for _ in range(25):
            tone = np.sin(phase + (steps * 2 * np.pi * 60.0 / rate)) * (vol * 0.95) * trigger
            phase = (phase + (buffer_size * 2 * np.pi * 60.0 / rate)) % (2 * np.pi)

            # 0 = Rear (Left/Ch0), 1 = Front (Right/Ch1)
            if side == 0:
                out = np.column_stack((tone, np.zeros(buffer_size, dtype=np.float32)))
            else:
                out = np.column_stack((np.zeros(buffer_size, dtype=np.float32), tone))
                
            stream.write(np.clip(out, -0.95, 0.95).astype(np.float32).tobytes())
            trigger *= 0.90
            
        stream.stop_stream()
        stream.close()
    except Exception as e:
        print(f"Hardware test error: {e}")
    finally:
        pa.terminate()
