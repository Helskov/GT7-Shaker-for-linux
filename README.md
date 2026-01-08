# GT7 Shaker for Linux 1.28
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


## 💻 Installation & Usage


### Recommended: Install via pipx
The easiest way to install and run GT7 Shaker as a standalone application:
    ```bash
    pipx install https://github.com/Helskov/GT7-Shaker-for-linux/releases/download/v1.27/gt7_shaker-1.27-py3-none-any.whl
    
After installation, simply run gt-shaker from anywhere in your terminal.

Option 2: Install from Source (For Developers)

Start by cloning the project to your local machine:
bash
    git clone https://github.com/Helskov/GT7-Shaker-for-linux.git
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
## 📱 Web Interface & Functionality

The web interface is designed for ease of use and is divided into two main pages. You can navigate between them by **swiping** on mobile devices or **clicking the navigation dots**.

---

### 📊 Page 1: Live Telemetry & Monitoring
*Focuses on real-time data visualization while driving.*

* **Real-time Gauges**: Visual display of **RPM**, **Speed**, **Gear**, and **Pedal** (Throttle/Brake) inputs.
* **Tire Status**: Monitoring of tire temperatures and wear percentages with color-coded alerts for optimal grip management.
* **Shaker Analysis**: A live graph showing the intensity of **Road Noise (Red)** vs. **Impact Forces (Blue)** being sent to your transducers.

---

### ⚙️ Page 2: Advanced Shaker Tuning
*This page allows you to customize the physical feel of the haptic feedback in real-time.*

#### 🛠️ General Settings
* **Master Volume**: Global gain control that scales all active haptic effects simultaneously.
* **Audio Device**: Select which soundcard or USB interface the engine should use for output.
* **Hardware Test**: Dedicated buttons to trigger 60Hz test tones for **Rear (Left)** or **Front (Right)** channels to verify wiring and shaker placement.

#### 🏎️ Engine RPM
* **Profiles**: Toggle between **Sine** (smooth), **V8** (simulated ignition pulses), and **Boxer** (rhythmic rumble).
* **Frequency Range**: Define the **Min Hz** and **Max Hz** to match your hardware's resonance capabilities and personal preference.

#### 🛣️ Suspension & Environment
* **Road vs. Impact**: Independent volume controls for subtle road textures and heavy bumps (curbs, grass, collisions).
* **Priority Mode**: Automatically dims engine vibrations during heavy suspension hits to prioritize road feel and impact clarity.

#### 🏁 Traction & Grip
* **Interface**: Dedicated sliders for **Sensitivity** and **Volume control**.
* **Auto-calibration**: Toggle functionality to ensure the traction loss effect remains accurate across different car classes.

#### 🕹️ Gear Shift Feedback
* **Mechanical Thump**: Generates a short, powerful vibration (tuned to 40Hz) every time the car changes gears to simulate mechanical shift linkage.
* **Volume & Balance**: Granular control over the "kick" intensity and the ability to shift the effect between front and rear transducers.
* **Interactive Toggle**: Includes a dedicated switch in the dashboard to quickly enable or disable the effect on the fly.


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

* More stability to the engine. See outstanding. 

* Cleanup and see if i can make the code more effective. 

* Maybe and just maybe support for motion. The integration should not be hard. But i have nothing to test with. 

* Landscape Mode Optimization: Specific CSS layouts for horizontal viewing on mounted devices.

* Multi-Channel Support: Expand from 2-channel stereo to 4.0 or 5.1 surround sound for 4-corner setups.

## 🛠️ In Progress / Outstanding

* Fix you sometimes have to restart engine when track changes or engine was already on when you started the game. 

## 🚀 Future Features (Planned)

* Support for Wind simulator

## Changes

### v1.28
* **Added Profiles**: Users can now save and name up to 4 different profiles.
* **Persistence**: All settings are now saved to `config.json`.
* **Haptic Improvement**: Road surface texture changed to a more haptic range (20-80Hz).
* **Traction Loss Priority**: Function added to prioritize traction loss over suspension and engine RPM.
* **Custom Headroom**: User-defined headroom for Safe-Gain (40-70%).
* **PWA Optimization**: Improved user manual for Android and iPhone.
* **Default Settings**: Updated defaults to provide a better "out of the box" experience.
* **Traction Calibration**: Faster auto-calibration that works during races; triggers when lifting gas while driving straight.

### v1.27
* **Audio Mixing**: Pit boost volume is now decoupled from Engine RPM volume.
* **Stability**: Fixed "stuck" engine effect after leaving track and prevented crashes when starting the engine without data.
* **Volume Adjustments**: Changed max volume for Gear Shift and Pit Boost.
* **Enhanced Status**: Implemented a more robust 3-stage status system.
* **Race Dashboard**: Added Position, Best Lap, and Last Lap; UI now defaults to Page 2.
* **Analysis**: Shaker analysis now includes traction and road simulation.
* **Removed**: Tire wear functionality (did not work properly).

### v1.26
* **Visuals**: Fixed graphs for throttle, brake, and suspension analysis.

### v1.25
* **Engine Effect**: More aggressive engine effect that follows RPM faster (previously felt like an old-school automatic).
* **Pit Boost UI**: New interface to control engine volume while stationary.
* **ALSA Support**: Prevented ALSA locks during engine start/stop on Linux.
* **Simulated Road Effect**: 
* New file: `Simulated_Road.py`.
* Roughness handle for bumps.
* Speed-based timing: Bumps hit front shakers then rear (reversed in reverse gear).
* **UI/UX**: 
* Start/Stop button stays in sync across multiple browsers.
* Added "Keep Screen On" functionality for mobile phones.
* New Race Dashboard focusing on race-critical data.
* **Traction Control**: Added frequency sliders for front and rear axles and replaced the traction readout.
* **Audio Settings**: Users can now toggle between 44.1kHz and 48kHz.
* **General**: Various bug fixes and stability optimizations.
  you lift the gas and drive straight if enabled. 

## 📂 Project Structure
To run the application correctly, the files must be organized as follows:
```
.
├── .gitignore # Files to be ignored by Git
├── LICENSE # Project license
├── pyproject.toml # Build configuration for the Python package
├── README.md # Documentation and instructions
├── requirements.txt # List of required libraries
└── src/ # Source code directory
    ├── config.json # User settings (auto-generated)
    └── gt_shaker/ # The main program package
        ├── __init__.py # Marks the directory as a package
        ├── audio_processor.py # Audio logic and effects
        ├── main.py # Main engine and audio stream
        ├── network_manager.py # PS5 network communication
        ├── Simulated_Road.py # Road simulation
        ├── tire_processor.py # Tire and traction logic
        ├── web_app.py # Flask web server and dashboard
        ├── assets/ # Images for UI and README
        └── templates/ # HTML files for the dashboard
            ├── index.html
            └── manual.html
