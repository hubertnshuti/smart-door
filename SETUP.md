# Lab Access Control — Setup Guide

## Running on Windows (development / testing)

The system auto-detects the platform and uses:
- **MockCamera** — reads from your laptop webcam (OpenCV `VideoCapture(0)`)
- **MockDoorHardware** — prints actions to console, no GPIO required

### 1. Install dependencies (cross-platform subset)

```bash
pip install flask flask-socketio eventlet insightface onnxruntime opencv-python numpy requests werkzeug
```

> `gpiozero`, `lgpio`, and `picamera2` are Pi-only. Do **not** install them on Windows —
> the app handles their absence through the abstraction layer.

### 2. Run

```bash
python app.py
```

Open [http://localhost:5000](http://localhost:5000) in your browser.

The root URL `/` shows a landing chooser with links to both portals.

### Default credentials

| Portal | URL | Username / Reg | Password |
|--------|-----|----------------|----------|
| Admin  | `/login` or `/admin/login` | `admin` | `admin1234` |
| Student (demo) | `/student/login` | `DEMO/2024/001` | `demo1234` |

Admin credentials are overridable via `ADMIN_USERNAME` / `ADMIN_PASSWORD` env vars.

**Demo flow:** Log in as the demo student to explore the student portal. To demo the live
signup flow, use any of the sample roster entries (`STU/2024/001` – `STU/2024/010`) —
they have no pre-created account so you can sign up with any password.

### Theme

The app defaults to **light theme**. Click the sun/moon toggle (top-right of every page)
to switch to dark. The choice is persisted in `localStorage`.

### 3. Environment variables (optional overrides)

```bash
set ADMIN_USERNAME=admin
set ADMIN_PASSWORD=yourpassword
set SECRET_KEY=change-me-in-production
set EMAIL_FROM=you@gmail.com
set EMAIL_PASSWORD=your-app-password
set EMAIL_TO=you@gmail.com
set TELEGRAM_BOT_TOKEN=your-token
set TELEGRAM_CHAT_ID=your-chat-id
set SMS_TO=250780000000
```

Force mock implementations explicitly:

```bash
set FORCE_MOCK_HARDWARE=1
set FORCE_MOCK_CAMERA=1
```

---

## Deploying on Raspberry Pi Zero 2 W

### 1. Enable camera interface

```bash
sudo raspi-config
# Interface Options → Camera → Enable
# Reboot
```

### 2. Install system packages

```bash
sudo apt update
sudo apt install -y python3-picamera2 python3-lgpio libatlas-base-dev
```

> **Note:** `picamera2` must be installed as a system package (not via pip) on Bookworm.
> Install it with `apt`, then use `--system-site-packages` when creating your venv.

### 3. Create virtual environment and install Python dependencies

```bash
python3 -m venv --system-site-packages venv
source venv/bin/activate
pip install flask flask-socketio eventlet insightface onnxruntime opencv-python numpy requests werkzeug gpiozero lgpio
```

### 4. Wire hardware

| Component | GPIO (BCM) | Physical Pin |
|-----------|-----------|--------------|
| MG995 servo signal | GPIO 18 | Pin 12 |
| Buzzer + | GPIO 17 | Pin 11 |
| Servo / buzzer GND | GND | Pin 6 |
| Servo VCC | 5V | Pin 2 |

### 5. Run

```bash
python app.py
```

The system will print `[camera] RealCamera (Picamera2)` and `[hardware] RealDoorHardware` at startup.

Access the dashboard from any device on the same network: `http://<pi-ip>:5000`

### 6. Run as a service (optional)

```bash
sudo nano /etc/systemd/system/labaccess.service
```

```ini
[Unit]
Description=Lab Access Control
After=network.target

[Service]
User=pi
WorkingDirectory=/home/pi/smart-door
ExecStart=/home/pi/smart-door/venv/bin/python app.py
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable labaccess
sudo systemctl start labaccess
```
