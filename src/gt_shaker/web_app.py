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

from flask import Flask, render_template, request, jsonify
import json, threading, pyaudio, time
from .main import ShakerEngine, play_test_tone
from .tire_processor import process_tires, TireProcessor

app = Flask(__name__)
CONFIG_FILE = "config.json"

# Initialize the tire processor for slip-ratio calculations
tire_processor = TireProcessor()

# FIXED: Corrected dictionary structure with all braces closed
default_config = {
    "ps5_ip": "192.168.1.116",
    "master_volume": 0.5,
    "shaker_mode": 2,
    "units": "metric",
    "audio": {
        "device_index": -1,
        "sample_rate": 48000
    },
    "effects": {
        "rpm": {
            "enabled": True, "volume": 0.25, "pit_boost": 0.80, "balance": 0.5,
            "min_freq": 25.0, "max_freq": 60.0, "profile": "v8"
        },
        "gear_shift": {"enabled": True, "volume": 1.0, "balance": 0.5},
        "suspension": {
            "enabled": True, "balance": 0.5, "threshold": 0.2, "impact_threshold": 3.0,
            "road_volume": 1.0, "impact_volume": 1.0, "priority": False, "rpm_dim": 0.5
        },
        "traction": {
            "enabled": True, "threshold": 0.05, "sensitivity": 0.15,
            "use_autocalib": True, "volume": 0.8, "front_freq": 58.0, "rear_freq": 42.0
        },
        "sim_road": {
            "enabled": False,
                "volume": 0.5,
                "texture_volume": 0.5,
                "texture_freq": 30.0,
                "roughness": 0.3
        }
    }
}

def save_config(cfg):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(cfg, f, indent=4)

def load_config():
    try:
        with open(CONFIG_FILE, 'r') as f:
            cfg = json.load(f)

            if "sim_road" not in cfg.get("effects", {}):
                cfg["effects"]["sim_road"] = default_config["effects"]["sim_road"]
            if "units" not in cfg: cfg["units"] = "metric"
            return cfg
    except:
        return default_config

current_config = load_config()
engine = None

# Sync the tire_processor with the loaded config values
if "traction" in current_config.get("effects", {}):
    t_cfg = current_config["effects"]["traction"]
    tire_processor.threshold = t_cfg.get("threshold", 0.05)
    tire_processor.sensitivity = t_cfg.get("sensitivity", 0.15)
    tire_processor.use_autocalib = t_cfg.get("use_autocalib", True)

@app.route('/')
def index():
    p = pyaudio.PyAudio(); devices = []
    for i in range(p.get_device_count()):
        try:
            info = p.get_device_info_by_index(i)
            if info['maxOutputChannels'] > 0: devices.append({'id': i, 'name': info['name']})
        except: pass
    p.terminate()
    return render_template('index.html', config=current_config, devices=devices)

def format_time(ms):
    """ Formaterer millisekunder til M:SS.ms (f.eks. 1:24.503) """
    if ms <= 0 or ms == 0xFFFFFFFF: return "--:--.---"
    m = ms // 60000
    s = (ms % 60000) // 1000
    ms_rem = ms % 1000
    return f"{m}:{s:02d}.{ms_rem:03d}"

@app.route('/api/telemetry')
def get_telemetry():
    """ Henter og formaterer telemetry-data til dashboardet """
    if engine and engine.running:
        # SIKKERHEDSTJEK: Forhindrer crash hvis websiden spørger før klienten er klar
        if not hasattr(engine, 'client') or engine.client is None:
            return jsonify({'active': True, 'is_live': False, 'status': 'connecting'})

        if engine.current_data:
            d = engine.current_data
            rpm = d.engine_rpm
            shift_raw = d.car_shift_rpm
            max_raw = d.car_max_rpm

            # 1. Watchdog (is_live) - Tjekker om data er friske
            packet_age = time.time() - engine.client.last_packet_time
            is_data_fresh = packet_age < 2.5

            # 2. Shift & Rev-Limit Logic
            red_start = max_raw - 50
            is_at_limit = (max_raw > 0 and rpm >= red_start) or bool(d.rev_limiter_active)
            green_start = shift_raw - 100
            green_end = red_start - 100
            is_shift_point = (rpm >= green_start and rpm < green_end) and not is_at_limit

            # 3. Processering af dæk-data (Temp & Wear)
            tire_data = process_tires(d)

            # 4. Traction Loss beregning
            trig_f, trig_r = tire_processor.get_traction_triggers(d)

            # FIX: Nulstil traction-værdier til grafen, hvis effekten er deaktiveret i menuen
            if not current_config['effects']['traction'].get('enabled', True):
                trig_f, trig_r = 0.0, 0.0

            # 5. Hent debug-værdier fra audio_processor (inkl. sim_road)
            debug = getattr(engine, 'live_debug', {'road_noise': 0.0, 'g_force': 0.0, 'sim_road': 0.0})

            return jsonify({
                'active': True,
                'is_live': is_data_fresh,
                'heartbeat': time.time(),
                'units': current_config.get('units', 'metric'),
                'rpm': round(d.engine_rpm),
                'max_rpm': d.car_max_rpm or 8000,
                'speed': d.speed_kmh,
                'gear': d.gear,
                'throttle': d.throttle,
                'brake': d.brake,
                'tires': tire_data,
                'rev_limiter': is_at_limit,
                'shift_indicator': is_shift_point,
                'shift_rpm': d.car_shift_rpm or 7500,

                # --- LØBS-DATA (Side 1) ---
                'position': getattr(d, 'position', 0),
                'best_lap': format_time(getattr(d, 'best_lap_ms', -1)),
                'last_lap': format_time(getattr(d, 'last_lap_ms', -1)),

                # --- SHAKER ANALYSE (Side 2) ---
                'analysis': {
                    'road': debug['road_noise'],
                    'impact': debug['g_force'],
                    'sim_road': debug.get('sim_road', 0.0)
                },
                'traction_triggers': {
                    'front': round(trig_f, 2),
                    'rear': round(trig_r, 2)
                }
            })

    # Standard-retur hvis motoren ikke kører
    return jsonify({'active': engine.running if engine else False, 'is_live': False})

@app.route('/api/update', methods=['POST'])
def update_settings():
    data = request.json
    try:
        current_config['master_volume'] = float(data.get('master_volume', current_config['master_volume']))
        current_config['ps5_ip'] = data.get('ps5_ip', current_config['ps5_ip'])
        current_config['units'] = data.get('units', current_config.get('units', 'metric'))
        current_config['shaker_mode'] = int(data.get('shaker_mode', current_config['shaker_mode']))

        if 'audio' in data:
            current_config['audio']['device_index'] = int(data['audio'].get('device_index', -1))
            current_config['audio']['sample_rate'] = int(data['audio'].get('sample_rate', 48000))

        # Loop through all effects including the new 'sim_road'
        for effect in ['rpm', 'suspension', 'gear_shift', 'traction', 'sim_road']:
            if effect in data:
                for key, val in data[effect].items():
                    # Handle numeric conversion for sliders and inputs
                    if isinstance(val, str) and (val.replace('.','',1).isdigit() or (val.startswith('-') and val[1:].replace('.','',1).isdigit())):
                        current_config['effects'][effect][key] = float(val)
                    else:
                        current_config['effects'][effect][key] = val

        # Update the live tire_processor object for traction triggers
        if 'traction' in data:
            t_data = data['traction']
            if 'threshold' in t_data: tire_processor.threshold = float(t_data['threshold'])
            if 'sensitivity' in t_data: tire_processor.sensitivity = float(t_data['sensitivity'])

        save_config(current_config)
        if engine: engine.cfg = current_config
        return jsonify({'status': 'updated'})
    except Exception as e:
        print(f"Update error: {e}")
        return jsonify({'status': 'error'})

@app.route('/api/toggle', methods=['POST'])
def toggle_engine():
    global engine
    data = request.json
    action = data.get('action')

    if action == 'start':
        # Tjek om en motor allerede kører eller er ved at lukke ned
        if engine and engine.thread_active:
            print("WARNING: Engine is already running or shutting down. Wait a second.")
            return jsonify({'status': 'busy'})

        current_config['ps5_ip'] = data.get('ip', current_config['ps5_ip'])
        save_config(current_config)

        engine = ShakerEngine(current_config)
        engine.tire_processor = tire_processor
        threading.Thread(target=engine.run, args=(current_config['ps5_ip'],), daemon=True).start()
        return jsonify({'status': 'ok'})

    elif action == 'stop':
        if engine:
            engine.running = False
            # Vi venter ikke her (for ikke at blokere UI),
            # men thread_active vil forhindre genstart før den er helt ude.
        return jsonify({'status': 'ok'})

    return jsonify({'status': 'error'})

@app.route('/api/test', methods=['POST'])
def test_shaker():
    data = request.json
    threading.Thread(target=play_test_tone, args=(current_config, data.get('side', 0)), daemon=True).start()
    return jsonify({'status': 'ok'})

@app.route('/manual')
def manual():
    return render_template('manual.html')

def main():
    """ Entry point for the gt-shaker command """
    app.run(host='0.0.0.0', port=5000)

if __name__ == '__main__':
    main()


