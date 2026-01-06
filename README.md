# GT7 Shaker for Linux 1.27
GT7 Shaker for Linux is a Python-based telemetry-to-audio converter specifically designed for Gran Turismo 7. It captures real-time physics data from your PS5 or PS4 over the network and translates it into haptic feedback for Bass Shakers using a standard soundcard or hardware like NobSound amplifiers with builtin soundcar functionality

Project is still under development and bugs is to be expected. 

Project started as personal project as i wanted a solution where is didn't need to boot a windows machine and start software like SimHub and etc. 
I wanted a solution that could run on linux and on lightweight hardware as my Raspberry Pi 3 build right on to my Rig. 

## 🚀 Core Features
Real-time Telemetry Decryption: Uses Salsa20 decryption to read the proprietary GT7 UDP stream from the PS5.

Advanced Audio Engine:

RPM Profiles: Supports Sine wave, V8 (with firing pulses), and Boxer engine profiles for realistic vibration.
    Pit Boost (New): Automatically detects when the car is stationary ($< 1.0$ km/h) and applies a 25% volume boost to the engine effects, providing a powerful, visceral "idle" feel in the seat while waiting in the pits.

Suspension Haptics: Separate logic for high-frequency road texture and low-frequency impacts/bumps.
    Road vs. Impact: Separate processing for Road Rumble (Red - 32Hz) and Impacts/Curbs (Blue - 55Hz).
    Priority Effect (Ducking): When a hard impact (Curb/Sausage) is detected, the constant road vibration is automatically attenuated. This prevents "signal mud" and ensures every curb strike feels sharp and defined.

Dual-Frequency Traction Loss:Haptic Differentiation: Uses distinct frequencies to help the driver identify which end of the car is losing grip
Autocalibration function to eliminate unnecessary noise during normal run. Can be enabled or disabled from interface.Work only above 40km/t 
and when have zero throttle and and zero brake applied
Frequency settings for rear and front axle so you better can feel the Differentiation

Gear Shifts: Sharp, physical "thumps" triggered during gear changes.

Simulated road effects calculated on speed. 

Web-Based Dashboard: A mobile-friendly Flask interface for real-time monitoring and tuning.

Hardware Protection: Includes a soft peak limiter and a stagnation detector to prevent damage and unnecessary noise.

Flexible Hardware Support for 1 or 2 shaker setup. 
Stereo Mode (2 Shakers): Full front-to-rear separation. Experience the curb transition from the front axle to the rear axle in real-time.

Mono Mode (1 Shaker): Intelligent "Downmix" that sums all telemetry channels into a single mono signal, ensuring no data is lost for users with a single-transducer setup.

![Dashboard Interface](src/gt_shaker/assets/Connectionpage.png)

![Dashboard Interface](src/gt_shaker/assets/RaceDash.png)

## 🛠 Prerequisites
Hardware
PS4/PS5 running Gran Turismo 7.

Linux PC (or any system running Python) on the same local network as the PS5.

Soundcard connected to an amplifier and haptic transducers (e.g., Buttkicker, Dayton Audio pucks).

Software Dependencies
You need Python 3.8+ and the following libraries installed:

Bash

pip install flask pyaudio numpy pycryptodome
Note: pycryptodome is essential for handling the encrypted telemetry packets sent by the PS5.

## 💻 Installation & Usage
Start by cloning the project to your local machine:
bash
git clone [https://github.com/Helskov/GT7-Shaker-for-linux.git](https://github.com/Helskov/GT7-Shaker-for-linux.git)
cd GT7-Shaker-for-linux

Modern Linux distributions (like Ubuntu 23.04+ or Debian 12+) require Python packages 
to be installed in a virtual environment to protect system stability:
    
python3 -m venv shaker-venv
source shaker-venv/bin/activate

You should now see (shaker-venv) in your terminal prompt.
Install the required libraries (Flask, PyAudio, NumPy, etc.) inside your environment:
pip install -r requirements.txt

Since the project uses relative imports to manage audio and telemetry modules, it must be run as a Python module:

cd src
python3 -m gt_shaker.web_app

Access the Dashboard: Open your browser (on PC or Smartphone) and go to http://[YOUR_PC_IP]:5000.

Inbound: Port 33740 (UDP) - Receives telemetry packets from GT7
Outbound: Port 33739 (UDP) - Sends heartbeats to PS5/PS4
Open Port 5000 as well for the browser. 

Connect to GT7: Enter your PS5 IP Address in the connection card and click START ENGINE.

## ⚙️ Interface & Configuration
The web interface is divided into two main pages that you can navigate by swiping or clicking the navigation dots.

Page 1: Live Telemetry & Monitoring

Real-time Gauges: Visual display of RPM, Speed, Gear, and Pedal (Throttle/Brake) inputs.

Tire Status: Monitoring of tire temperatures and wear percentages with color-coded alerts.

Shaker Analysis: Live graph showing the intensity of Road Noise vs. Impact Forces being sent to your shakers.

Page 2: Advanced Shaker Tuning
This page allows you to customize the physical feel of the haptic feedback.

General Settings:

Master Volume: Global gain control that scales all active haptic effects.

Audio Device: Select which soundcard or USB interface the engine should use for output.

Hardware Test: Buttons to trigger 60Hz test tones for Rear (Left) or Front (Right) channels to verify wiring.

Engine RPM:

Profiles: Toggle between Sine, V8 (simulated ignition pulses), and Boxer (rhythmic rumble).

Frequency Range: Define the Min Hz and Max Hz to match your hardware's resonance capabilities.

Suspension & Environment:

Road vs. Impact: Independent volume controls for subtle road textures and heavy bumps.

Priority Mode: Automatically dims engine vibrations during heavy suspension hits to prioritize road feel.

Traction & Grip Interface: Sliders for Sensitivity, volume control and autocalibration functionality

Gear Shift Feedback:
Mechanical Thump: Generates a short, vibration (tuned to 40Hz) every time the car changes gears to simulate mechanical shift linkage.

Volume & Balance: Allows for granular control over the "kick" intensity and the ability to shift the effect between front and rear transducers.

Interactive Toggle: Includes a dedicated switch in the web dashboard to quickly enable or disable the effect.

<table>
<tr>
<td><b>Page 1: Telemetry</b></td>
<td><b>Page 2: Shaker Tuning</b></td>
</tr>
<tr>
<td><img src="src/gt_shaker/assets/SettingsPage1_2.png" width="400"></td>
<td><img src="src/gt_shaker/assets/SettingsPage2_2.png" width="400"></td>
</tr>
</table>

## 🗺️ Roadmap & Future Plans
The project is under active development. Below are the planned features and current "to-do" items:

## 🛠️ In Progress / Outstanding

## 🚀 Future Features (Planned)

Landscape Mode Optimization: Specific CSS layouts for horizontal viewing on mounted devices.

Multi-Channel Support: Expand from 2-channel stereo to 4.0 or 5.1 surround sound for 4-corner setups.

## Changes
1.25 New:   More aggrasive Engine effec following the RPM faster. Before it was like a old school Automatic gearbox. 
            User interface for the Pit Boost effect so user can control the volume of the engine while stationary
            Prevent ALSA lock when starting and stopping Engine
            Simulated Road Effect with handle for roughness of simulated bumps. when driving forward bumps will hit frontshaker 
            and then rear shaker. Time in between is calculated on speed. Effect is reverse when car is in reverse. New file Simulated_Road.py
            Start/Stop engine button is now in sync across browsers. 
            Keep Screen on functionality on Phones. 
            New Race Dashboard with focus on race
            Sliders for frequencies on traction for front and rear axle. Replaced the readout for traction effect. 
            User can now set the soundcard settings to 44.1 or 48khz on the interface. 
            Various bug fixes and stability Optimization

1.26        Fixed graph for throttle, brake and suspension Analysis

1.27        Pit boost volume decoupled from Engine RPM volume
            Fix of Engine effect stuck after leaving track.
            changed max volume for gear shift and Pit Boost. 
            Made status more robost with 3 status, and software dont crash when activating engine while not data yet. 
            Removed Tire wear. did not work properly
            Added Pos, Bestlap and last lap to race dash. 
            Web always starts default page 2. 
            Shaker analysis now with traction and road simulation. 

## 📂 Project Structure
To run the application correctly, the files must be organized as follows:

```
.
├── pyproject.toml          # Build konfiguration
├── requirements.txt        # Afhængigheder (Flask, PyAudio, osv.)
├── .gitignore              # Fortæller Git hvilke filer der skal springes over
├── README.md               # Denne fil
└── src/                    # Kildekode-mappe
├── config.json         # Dine gemte indstillinger
└── gt_shaker/          # Selve program-pakken
├── __init__.py     # Markerer mappen som en pakke
├── web_app.py      # Flask server og interface
├── main.py         # Shaker motor og lyd-stream
├── audio_processor.py # Lyd-logik og effekter
├── network_manager.py # PS5 netværks-logik
├── tire_processor.py  # Dæk-data og traction-loss
├── Simulated_Road.py  # Simulering af vejoverflade
├── assets/         # Billeder til dashboard og README
└── templates/      # HTML filer til web-interfacet
├── index.html
└── manual.html            # Your saved settings (auto-generated in root or package)
```
