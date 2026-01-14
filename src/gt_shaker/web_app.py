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


from flask import Flask, render_template, request, jsonify
import json, threading, pyaudio, time, copy
from .main import ShakerEngine
from .tire_processor import process_tires, TireProcessor
from .audio_utils import play_test_tone

app = Flask(__name__)
CONFIG_FILE = "config.json"

# Initialize the tire processor
tire_processor = TireProcessor()

# Standard effekter brugt til profiler og fallback
default_effects = {
    "rpm": {
        "enabled": True, "volume": 0.25, "pit_boost": 0.80, "balance": 0.5,
        "min_freq": 25.0, "max_freq": 60.0, "profile": "v8"
    },
    "gear_shift": {"enabled": True, "volume": 1.0, "balance": 0.5},
    "suspension": {
        "enabled": True, "balance": 0.5, "threshold": 0.27, "impact_threshold": 35.0,
        "road_volume": 1.0, "impact_volume": 1.0, "priority": True, "rpm_dim": 0.5
    },
    "traction": {
        "enabled": True, "threshold": 0.15, "sensitivity": 0.06,
        "use_autocalib": True, "volume": 0.8, "front_freq": 38.0, "rear_freq": 34.0, "priority": True
    },
    "sim_road": {
        "enabled": False, "volume": 0.5, "texture_volume": 0.5, "texture_freq": 30.0, "roughness": 0.3
    }
}

default_config = {
    "ps5_ip": "192.168.1.116",
    "master_volume": 0.75,
    "output_headroom": 0.50,
    "shaker_mode": 2,
    "units": "metric",
    "active_profile_id": "1",
    "audio": {"device_index": -1, "sample_rate": 48000},
    "profiles": {
        "1": {"name": "Profil 1", "effects": copy.deepcopy(default_effects)},
        "2": {"name": "Profil 2", "effects": copy.deepcopy(default_effects)},
        "3": {"name": "Profil 3", "effects": copy.deepcopy(default_effects)},
        "4": {"name": "Profil 4", "effects": copy.deepcopy(default_effects)}
    },
    "effects": copy.deepcopy(default_effects)
}

def save_config(cfg):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(cfg, f, indent=4)

def load_config():
    try:
        with open(CONFIG_FILE, 'r') as f:
            cfg = json.load(f)

            # Sikrer at 'effects' sektionen findes
            if "effects" not in cfg:
                cfg["effects"] = copy.deepcopy(default_config["effects"]) # Brug deepcopy her

            # MIGRATION: Gennemgår alle profiler for at sikre, at de er isolerede
            if "profiles" not in cfg:
                cfg["profiles"] = copy.deepcopy(default_config["profiles"]) # Brug deepcopy her
                cfg["active_profile_id"] = "1"
            else:
                for p_id in cfg["profiles"]:
                    # Sørger for at hver profil har sit helt eget unikke 'effects' objekt
                    for eff_name, eff_data in default_config["effects"].items():
                        if eff_name not in cfg["profiles"][p_id]["effects"]:
                            cfg["profiles"][p_id]["effects"][eff_name] = copy.deepcopy(eff_data) # Brug deepcopy her
                        else:
                            for key, val in eff_data.items():
                                if key not in cfg["profiles"][p_id]["effects"][eff_name]:
                                    cfg["profiles"][p_id]["effects"][eff_name][key] = val

            if "units" not in cfg: cfg["units"] = "metric"
            return cfg
    except Exception as e:
        print(f"Config load error: {e}")
        return copy.deepcopy(default_config)

current_config = load_config()
engine = None

# Synkroniser tire_processor ved opstart
if "traction" in current_config.get("effects", {}):
    t_cfg = current_config["effects"]["traction"]
    tire_processor.threshold = float(t_cfg.get("threshold", 0.15))
    tire_processor.sensitivity = float(t_cfg.get("sensitivity", 0.06))
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
    if ms <= 0 or ms == 0xFFFFFFFF: return "--:--.---"
    m = ms // 60000
    s = (ms % 60000) // 1000
    ms_rem = ms % 1000
    return f"{m}:{s:02d}.{ms_rem:03d}"

@app.route('/api/telemetry')
def get_telemetry():
    if engine and engine.running:
        if not hasattr(engine, 'client') or engine.client is None:
            return jsonify({'active': True, 'is_live': False, 'status': 'connecting'})

        if engine.current_data:
            d = engine.current_data
            packet_age = time.time() - engine.client.last_packet_time
            is_data_fresh = packet_age < 2.5

            red_start = d.car_max_rpm - 50
            is_at_limit = (d.car_max_rpm > 0 and d.engine_rpm >= red_start) or bool(d.rev_limiter_active)
            is_shift_point = (d.engine_rpm >= d.car_shift_rpm - 100 and d.engine_rpm < red_start - 100) and not is_at_limit

            trig_f, trig_r = tire_processor.get_traction_triggers(d)
            if not current_config['effects']['traction'].get('enabled', True):
                trig_f, trig_r = 0.0, 0.0

            debug = getattr(engine, 'live_debug', {'road_noise': 0.0, 'g_force': 0.0, 'sim_road': 0.0})

            return jsonify({
                'active': True, 'is_live': is_data_fresh, 'heartbeat': time.time(),
                'units': current_config.get('units', 'metric'),
                'rpm': round(d.engine_rpm), 'max_rpm': d.car_max_rpm or 8000,
                'speed': d.speed_kmh, 'gear': d.gear, 'throttle': d.throttle, 'brake': d.brake,
                'tires': process_tires(d), 'rev_limiter': is_at_limit, 'shift_indicator': is_shift_point,
                'position': getattr(d, 'position', 0),
                'best_lap': format_time(getattr(d, 'best_lap_ms', -1)),
                'last_lap': format_time(getattr(d, 'last_lap_ms', -1)),
                'analysis': {'road': debug['road_noise'], 'impact': debug['g_force'], 'sim_road': debug.get('sim_road', 0.0)},
                'traction_triggers': {'front': round(trig_f, 2), 'rear': round(trig_r, 2)}
            })
    return jsonify({'active': engine.running if engine else False, 'is_live': False})

@app.route('/api/update', methods=['POST'])
def update_settings():
    """ Sammensmeltet funktion: Gemmer både live og i den aktive profil """
    data = request.json
    p_id = current_config.get('active_profile_id', '1')
    try:
        # Globale indstillinger
        current_config['master_volume'] = float(data.get('master_volume', current_config['master_volume']))
        current_config['output_headroom'] = float(data.get('output_headroom', current_config.get('output_headroom', 0.45)))
        current_config['ps5_ip'] = data.get('ps5_ip', current_config['ps5_ip'])
        current_config['units'] = data.get('units', current_config.get('units', 'metric'))
        current_config['shaker_mode'] = int(data.get('shaker_mode', current_config.get('shaker_mode', 2)))

        if 'audio' in data:
            current_config['audio']['device_index'] = int(data['audio'].get('device_index', -1))
            current_config['audio']['sample_rate'] = int(data['audio'].get('sample_rate', 48000))


        for effect in ['rpm', 'suspension', 'gear_shift', 'traction', 'sim_road']:
            if effect in data:
                for key, val in data[effect].items():
                    # Numerisk tjek (vigtigt for sliders)
                    if isinstance(val, str) and (val.replace('.','',1).isdigit() or (val.startswith('-') and val[1:].replace('.','',1).isdigit())):
                        val = float(val)

                    # Gem i aktiv kørsel OG i profil-arkiv
                    current_config['effects'][effect][key] = val
                    current_config['profiles'][p_id]['effects'][effect][key] = val

        # Live opdatering af tire_processor
        if 'traction' in data:
            t_data = data['traction']
            if 'threshold' in t_data: tire_processor.threshold = float(t_data['threshold'])
            if 'sensitivity' in t_data: tire_processor.sensitivity = float(t_data['sensitivity'])

        save_config(current_config)
        if engine: engine.cfg = current_config
        return jsonify({'status': 'updated'})
    except Exception as e:
        print(f"Update error: {e}")
        return jsonify({'status': 'error', 'msg': str(e)})

@app.route('/api/toggle', methods=['POST'])
def toggle_engine():
    global engine
    data = request.json
    if data.get('action') == 'start':
        if engine and engine.thread_active: return jsonify({'status': 'busy'})
        current_config['ps5_ip'] = data.get('ip', current_config['ps5_ip'])
        save_config(current_config)
        engine = ShakerEngine(current_config)
        engine.tire_processor = tire_processor
        threading.Thread(target=engine.run, args=(current_config['ps5_ip'],), daemon=True).start()
        return jsonify({'status': 'ok'})
    elif data.get('action') == 'stop':
        if engine: engine.running = False
        return jsonify({'status': 'ok'})
    return jsonify({'status': 'error'})

@app.route('/api/profiles/select', methods=['POST'])
def select_profile():
    p_id = str(request.json.get('id'))
    if p_id in current_config['profiles']:
        current_config['active_profile_id'] = p_id
        # BRUG DEEPCOPY HER OGSÅ!
        current_config['effects'] = copy.deepcopy(current_config['profiles'][p_id]['effects'])
        save_config(current_config)
        if engine: engine.cfg = current_config
        return jsonify({'status': 'ok', 'config': current_config})
    return jsonify({'status': 'error'})

@app.route('/api/profiles/rename', methods=['POST'])
def rename_profile():
    data = request.json
    p_id, new_name = str(data.get('id')), data.get('name', '').strip()
    if p_id in current_config['profiles'] and new_name:
        current_config['profiles'][p_id]['name'] = new_name[:20]
        save_config(current_config)
        return jsonify({'status': 'ok'})
    return jsonify({'status': 'error'})

@app.route('/api/test', methods=['POST'])
def test_shaker():
    threading.Thread(target=play_test_tone, args=(current_config, request.json.get('side', 0)), daemon=True).start()
    return jsonify({'status': 'ok'})

@app.route('/manual')
def manual(): return render_template('manual.html')

def main(): app.run(host='0.0.0.0', port=5000)

if __name__ == '__main__': main()
