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


import socket
import struct
import threading
import sys
import time
import math
from collections import deque

try:
    from Crypto.Cipher import Salsa20
except ImportError:
    print("ERROR: Missing pycryptodome. Run: pip install pycryptodome")
    sys.exit()

class GTData:
    def __init__(self, data):
        # --- LØBS-DATA ---
        self.current_lap = struct.unpack('<h', data[0x74:0x74 + 2])[0]
        self.best_lap_ms = struct.unpack('<i', data[0x78:0x78 + 4])[0]
        self.last_lap_ms = struct.unpack('<i', data[0x7C:0x7C + 4])[0]
        self.position = struct.unpack('<h', data[0x84:0x84 + 2])[0]

        raw_flags = struct.unpack('<H', data[0x8E:0x90])[0]
        # Bit 0: Car On Track (1)
        self.in_race = bool(raw_flags & 1)

        # Bit 1: Paused (2)
        self.is_paused = bool(raw_flags & 2)

        # Bit 2: Loading/Processing (4) - NYT: Sikrer stilhed under load
        self.is_loading = bool(raw_flags & 4)

        # --- VEKTORER ---
        self.velocity_x = struct.unpack('<f', data[0x10:0x14])[0]
        self.vel_y      = struct.unpack('<f', data[0x14:0x18])[0]
        self.velocity_z = struct.unpack('<f', data[0x18:0x1C])[0]
        self.yaw        = struct.unpack('<f', data[0x20:0x24])[0]

        self.engine_rpm = struct.unpack('<f', data[0x3C:0x40])[0]
        self.car_shift_rpm = struct.unpack('<H', data[0x88:0x8A])[0]
        self.car_max_rpm = struct.unpack('<H', data[0x8A:0x8C])[0]
        self.speed_kmh = (struct.unpack('<f', data[0x4C:0x50])[0]) * 3.6
        self.gear = data[0x90] & 0x0F
        self.throttle = (data[0x91] / 255.0) * 100
        self.brake = (data[0x92] / 255.0) * 100
        self.rev_limiter_active = bool(data[0x93] & 0x20)

        # FYSIK PLACEHOLDERS
        self.surge_g = 0.0 # Frem/Tilbage
        self.sway_g  = 0.0 # Højre/Venstre (NY)

        # --- DÆK & HJUL ---
        self.tire_temp_FL = struct.unpack('<f', data[0x60:0x64])[0]
        self.tire_temp_FR = struct.unpack('<f', data[0x64:0x68])[0]
        self.tire_temp_RL = struct.unpack('<f', data[0x68:0x6C])[0]
        self.tire_temp_RR = struct.unpack('<f', data[0x6C:0x70])[0]

        self.wheel_speed_FL = abs(struct.unpack('<f', data[0xA4:0xA8])[0])
        self.wheel_speed_FR = abs(struct.unpack('<f', data[0xA8:0xAC])[0])
        self.wheel_speed_RL = abs(struct.unpack('<f', data[0xAC:0xB0])[0])
        self.wheel_speed_RR = abs(struct.unpack('<f', data[0xB0:0xB4])[0])

        self.wheel_radius_FL = struct.unpack('<f', data[0xB4:0xB8])[0]
        self.wheel_radius_FR = struct.unpack('<f', data[0xB8:0xBC])[0]
        self.wheel_radius_RL = struct.unpack('<f', data[0xBC:0xC0])[0]
        self.wheel_radius_RR = struct.unpack('<f', data[0xC0:0xC4])[0]

        self.suspension_height_FL = struct.unpack('<f', data[0xC4:0xC8])[0]
        self.suspension_height_FR = struct.unpack('<f', data[0xC8:0xCC])[0]
        self.suspension_height_RL = struct.unpack('<f', data[0xCC:0xD0])[0]
        self.suspension_height_RR = struct.unpack('<f', data[0xD0:0xD4])[0]


class TurismoClient:
    def __init__(self, ip_addr='192.168.1.116'):
        self.ip_addr = ip_addr
        self.ps5_port = 33739
        self.recv_port = 33740

        self.sock_send = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock_recv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock_recv.settimeout(2.0)
        self.sock_recv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        try:
            self.sock_recv.bind(('0.0.0.0', self.recv_port))
        except Exception as e:
            print(f"Socket bind warning: {e}")

        self.running = False
        self.telemetry = None
        self.last_packet_time = 0.0
        self.rpm_history = deque(maxlen=10)

        # State variabler til G-kraft
        self.last_v_x = 0.0
        self.last_v_z = 0.0
        self.last_calc_time = time.time()
        self.last_surge_g = 0.0
        self.last_sway_g  = 0.0 # NY: Husker side-G

    def start(self):
        if not self.running:
            self.running = True
            threading.Thread(target=self._run_heartbeat, daemon=True).start()
            threading.Thread(target=self._run_recv, daemon=True).start()
            print(f"Client started. Target IP: {self.ip_addr}")

    def stop(self):
        self.running = False
        try:
            self.sock_recv.close()
            self.sock_send.close()
        except: pass

    def _run_heartbeat(self):
        while self.running:
            try:
                self.sock_send.sendto(b'A', (self.ip_addr, self.ps5_port))
                if time.time() - self.last_packet_time > 5.0:
                    self.sock_send.sendto(b'A', (self.ip_addr, self.ps5_port))
                time.sleep(1.0)
            except Exception as e:
                print(f"Heartbeat error: {e}")
                time.sleep(1)

    def _run_recv(self):
        print("Receiver thread active")
        while self.running:
            try:
                data, _ = self.sock_recv.recvfrom(4096)
                if len(data) >= 0x128:
                    iv1 = struct.unpack('<I', data[0x40:0x44])[0]
                    nonce = (iv1 ^ 0xDEADBEAF).to_bytes(4, 'little') + iv1.to_bytes(4, 'little')
                    key = b'Simulator Interface Packet GT7 v'
                    cipher = Salsa20.new(key=key, nonce=nonce)
                    decrypted = cipher.decrypt(data)

                    if decrypted[0:4] in [b'G7S0', b'\x30\x53\x37\x47']:
                        now = time.time()
                        self.last_packet_time = now

                        new_data = GTData(decrypted)

                        # --- 2D FYSIK MOTOR ---
                        dt = now - self.last_calc_time

                        if dt > 0.010:
                            ax_world = (new_data.velocity_x - self.last_v_x) / dt
                            az_world = (new_data.velocity_z - self.last_v_z) / dt

                            sin_y = math.sin(new_data.yaw)
                            cos_y = math.cos(new_data.yaw)

                            # 1. Surge (Frem/Tilbage)
                            raw_surge = (az_world * cos_y) + (ax_world * sin_y)

                            # 2. Sway (Højre/Venstre) - NY BEREGNING
                            raw_sway = (ax_world * cos_y) - (az_world * sin_y)

                            # Peak Hold / Decay for BEGGE retninger
                            # Surge
                            if abs(raw_surge) > abs(self.last_surge_g):
                                self.last_surge_g = raw_surge
                            else:
                                self.last_surge_g *= 0.90

                            # Sway
                            if abs(raw_sway) > abs(self.last_sway_g):
                                self.last_sway_g = raw_sway
                            else:
                                self.last_sway_g *= 0.90

                            new_data.surge_g = self.last_surge_g
                            new_data.sway_g  = self.last_sway_g

                            self.last_v_x = new_data.velocity_x
                            self.last_v_z = new_data.velocity_z
                            self.last_calc_time = now
                        else:
                            new_data.surge_g = self.last_surge_g
                            new_data.sway_g = self.last_sway_g

                        self.rpm_history.append(new_data.engine_rpm)
                        new_data.engine_rpm = sum(self.rpm_history) / len(self.rpm_history)

                        self.telemetry = new_data

            except socket.timeout:
                continue
            except OSError:
                break
            except Exception as e:
                print(f"Recv error: {e}")
