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


import socket
import struct
import threading
import sys
import time
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

        # --- FLAGS ---
        flags = data[0x8E]
        self.in_race = bool(flags & 1)
        self.is_paused = bool(flags & 2)

        # --- ESSENTIEL FYSIK ---
        self.vel_y = struct.unpack('<f', data[0x14:0x18])[0]
        self.engine_rpm = struct.unpack('<f', data[0x3C:0x40])[0]
        self.car_shift_rpm = struct.unpack('<H', data[0x88:0x8A])[0]
        self.car_max_rpm = struct.unpack('<H', data[0x8A:0x8C])[0]
        self.speed_kmh = (struct.unpack('<f', data[0x4C:0x50])[0]) * 3.6
        self.gear = data[0x90] & 0x0F
        self.throttle = (data[0x91] / 255.0) * 100
        self.brake = (data[0x92] / 255.0) * 100
        self.rev_limiter_active = bool(data[0x93] & 0x20)

        # --- DÆK DATA ---
        self.tire_temp_FL = struct.unpack('<f', data[0x60:0x64])[0]
        self.tire_temp_FR = struct.unpack('<f', data[0x64:0x68])[0]
        self.tire_temp_RL = struct.unpack('<f', data[0x68:0x6C])[0]
        self.tire_temp_RR = struct.unpack('<f', data[0x6C:0x70])[0]

        # --- HJUL & AFFJEDRING ---
        self.wheel_speed_FL = abs(struct.unpack('<f', data[0xA4:0xA8])[0])
        self.wheel_speed_FR = abs(struct.unpack('<f', data[0xA8:0xAC])[0])
        self.wheel_speed_RL = abs(struct.unpack('<f', data[0xAC:0xB0])[0])
        self.wheel_speed_RR = abs(struct.unpack('<f', data[0xB0:0xB4])[0])

        self.suspension_height_FL = struct.unpack('<f', data[0xC4:0xC8])[0]
        self.suspension_height_FR = struct.unpack('<f', data[0xC8:0xCC])[0]
        self.suspension_height_RL = struct.unpack('<f', data[0xCC:0xD0])[0]
        self.suspension_height_RR = struct.unpack('<f', data[0xD0:0xD4])[0]

        self.wheel_radius_FL = struct.unpack('<f', data[0xB4:0xB8])[0]
        self.wheel_radius_FR = struct.unpack('<f', data[0xB8:0xBC])[0]
        self.wheel_radius_RL = struct.unpack('<f', data[0xBC:0xC0])[0]
        self.wheel_radius_RR = struct.unpack('<f', data[0xC0:0xC4])[0]


class TurismoClient:
    def __init__(self, ip_addr='192.168.1.116'):
        self.ip_addr = ip_addr
        self.ps5_port = 33739
        self.recv_port = 33740

        self.sock_send = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock_recv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        # FIX 1: Timeout forhindrer at tråden låser sig fast ved baneskift
        self.sock_recv.settimeout(2.0)
        self.sock_recv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        try:
            self.sock_recv.bind(('0.0.0.0', self.recv_port))
        except Exception as e:
            print(f"Socket bind warning: {e}")

        self.running = False
        self.telemetry = None
        self.last_packet_time = 0.0
        self.rpm_history = deque(maxlen=20)

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
        """ Robust heartbeat der holder forbindelsen åben """
        while self.running:
            try:
                # Send standard heartbeat ('A')
                self.sock_send.sendto(b'A', (self.ip_addr, self.ps5_port))

                # FIX 2: VÆKKE-LOGIK
                # Hvis ikke har modtaget data i 5 sekunder (f.eks. lobby/pause),
                # send et ekstra signal for at holde NAT-tabellen i routeren åben.
                if time.time() - self.last_packet_time > 5.0:
                    self.sock_send.sendto(b'A', (self.ip_addr, self.ps5_port))

                time.sleep(1.0)
            except Exception as e:
                print(f"Heartbeat error: {e}")
                time.sleep(1)

    def _run_recv(self):
        """ Modtager-løkke der tåler pauser """
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
                        self.last_packet_time = time.time()
                        self.telemetry = GTData(decrypted)

                        # RPM Smoothing
                        self.rpm_history.append(self.telemetry.engine_rpm)
                        self.telemetry.engine_rpm = sum(self.rpm_history) / len(self.rpm_history)

            except socket.timeout:
                # FIX 3: Håndtering af timeout
                # Når data stopper (baneskift), lander vi her.
                # 'continue' får løkken til at starte forfra med det samme,
                # så den er klar til at modtage data ØJEBLIKKELIGT når de kommer igen.
                continue
            except OSError:
                break
            except Exception as e:
                print(f"Recv error: {e}")
