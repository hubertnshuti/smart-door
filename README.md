# Smart Bell & Lock Door System — Setup Guide

Face recognition door system for **Raspberry Pi Zero 2 W** running **Raspberry Pi OS Bookworm**,
using **InsightFace**, an **MG995 servo** (auto re-locking latch), a **buzzer**, and
**Email + Telegram** alerts.

---

## 0. What you need

- Raspberry Pi Zero 2 W with Raspberry Pi OS Bookworm flashed to a 32GB+ SD card
- Pi Camera connected to the CSI port
- MG995 servo
- **External 5V 2A power supply for the servo** (do NOT power MG995 from the Pi)
- Active buzzer
- Jumper wires + breadboard

---

## 1. Wiring (BCM pin numbers)

```
MG995 servo:
  Orange (signal) -> GPIO 18  (physical pin 12)
  Red    (VCC)    -> External 5V (+)
  Brown  (GND)    -> External 5V (-)  AND  Pi GND   <-- COMMON GROUND IS REQUIRED

Buzzer:
  +  -> GPIO 17 (physical pin 11)
  -  -> Pi GND  (physical pin 6)

Camera -> CSI ribbon port
```

The #1 cause of a jittering or dead servo is a missing common ground between
the servo's power supply and the Pi. Connect them.

---

## 2. One-time Pi setup

Enable the camera and update the system:

```bash
sudo apt update && sudo apt full-upgrade -y
sudo raspi-config        # Interface Options -> enable Camera (if needed), then reboot
```

Install the system packages we rely on:

```bash
sudo apt install -y python3-picamera2 python3-opencv pigpio \
                    python3-venv libatlas-base-dev
```

Enable the pigpio daemon (needed for smooth servo PWM):

```bash
sudo systemctl enable --now pigpiod
```

---

## 3. Copy the project & create the environment

Put the `smart_door` folder in `/home/pi/smart_door`, then:

```bash
cd /home/pi/smart_door

# --system-site-packages lets the venv see Picamera2 & OpenCV from apt
python3 -m venv venv --system-site-packages
source venv/bin/activate

pip install --upgrade pip
pip install flask insightface onnxruntime numpy gpiozero pigpio requests
```

Note: `insightface` + `onnxruntime` take a while to install on a Pi Zero 2 W.
Be patient — it can take 15–30 minutes the first time.

---

## 4. Configure your settings

Open `config.py` and change:

- `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `SECRET_KEY`  (dashboard login)
- Email section: `EMAIL_FROM`, `EMAIL_PASSWORD`, `EMAIL_TO`
  - For Gmail, turn on 2-Step Verification, then create an **App Password**
    (Google Account -> Security -> App passwords). Use that 16-char password,
    NOT your normal Gmail password.
- Telegram section: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
  - Message **@BotFather** -> `/newbot` -> copy the token.
  - Message your new bot once, then visit
    `https://api.telegram.org/bot<TOKEN>/getUpdates` to find your chat id,
    or message **@userinfobot**.

You can instead set these as environment variables (safer than editing the file).

---

## 5. First run

```bash
cd /home/pi/smart_door
source venv/bin/activate
python3 app.py
```

The first run downloads the InsightFace model (one-time, needs internet).
When you see `[init] ready.`, open a browser on any device on the same network:

```
http://<your-pi-ip>:5000
```

Find the Pi's IP with `hostname -I`.

---

## 6. Using it

1. **Log in** with the admin credentials from `config.py`.
2. Go to **Members** -> have someone look at the camera -> type their name ->
   **Capture & register**. Repeat for each household member.
   (Register each person 2–3 times in different lighting for better accuracy.)
3. Go back to **Dashboard**. The system now:
   - Opens the door automatically for registered faces (auto re-locks after 5s).
   - Beeps the buzzer + emails + Telegrams a snapshot for unknown faces.
   - Lets you **Open / Lock** the door manually and watch the **live feed** and **logs**.

---

## 7. Auto-start on boot (optional)

```bash
sudo cp /home/pi/smart_door/smartdoor.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now smartdoor.service

# check it / view logs:
sudo systemctl status smartdoor.service
journalctl -u smartdoor.service -f
```

---

## 8. Tuning & troubleshooting

| Problem | Fix |
|---|---|
| Servo jitters or doesn't move | Check common ground; make sure `pigpiod` is running. |
| Door opens the wrong way | Swap `SERVO_LOCKED_ANGLE` / `SERVO_OPEN_ANGLE` in `config.py`. |
| Recognizes strangers as known | Raise `MATCH_THRESHOLD` (e.g. 0.5–0.55). |
| Doesn't recognize known people | Lower `MATCH_THRESHOLD` (e.g. 0.4); re-register in better light. |
| Too slow / CPU pegged | Increase `RECOGNIZE_EVERY_N_FRAMES`; keep `det_size` at (320,320). |
| Camera errors | Confirm `python3-picamera2` is installed and camera is enabled. |
| Out of memory during install | Add swap: `sudo dphys-swapfile` (raise CONF_SWAPSIZE to 1024). |

---

## How the recognition works (short version)

InsightFace turns each detected face into a 512-number vector (an "embedding").
Faces of the same person produce vectors pointing in almost the same direction.
We measure that with **cosine similarity** (1.0 = identical direction). If the best
match against your registered members scores above `MATCH_THRESHOLD`, it's that
person; otherwise it's treated as unknown.
