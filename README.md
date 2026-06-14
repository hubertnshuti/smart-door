# Lab Access Control System

A face-recognition door system for a university computer lab, built on a **Raspberry Pi Zero 2 W**. A camera at the lab door continuously watches for faces. When it recognises an authorised person it unlocks the door with a servo motor; when it sees an unknown person it sounds a buzzer and sends an alert (SMS, email, and Telegram). Everything is managed through a web dashboard.

This README assumes **no prior knowledge** of the technologies involved. Follow it top to bottom and you will have a working system.

---

## Table of contents

1. [What the system does](#1-what-the-system-does)
2. [How it works (plain explanation)](#2-how-it-works-plain-explanation)
3. [Who can open the door](#3-who-can-open-the-door)
4. [Hardware you need](#4-hardware-you-need)
5. [Wiring](#5-wiring)
6. [Software setup, step by step](#6-software-setup-step-by-step)
7. [Configuration](#7-configuration)
8. [Running the system](#8-running-the-system)
9. [Using the two portals](#9-using-the-two-portals)
10. [The alert system (SMS, email, Telegram)](#10-the-alert-system-sms-email-telegram)
11. [Project structure](#11-project-structure)
12. [How face recognition works](#12-how-face-recognition-works)
13. [Troubleshooting](#13-troubleshooting)
14. [Glossary](#14-glossary)

---

## 1. What the system does

- Watches the lab door through a Raspberry Pi camera.
- Recognises faces of people who have been enrolled in the system.
- **Opens the door** (via a servo motor that moves a latch) for authorised people, then automatically re-locks after a few seconds.
- **Sounds a buzzer and sends alerts** when an unknown person, or a known student without valid access, appears.
- Provides an **admin web dashboard** to manage people, grant time-limited access, watch a live camera feed, and review a full history of events.
- Provides a separate **student web portal** where students create an account and request access to the lab.

It is designed for a real lab scenario: permanent staff always have access, while students get access only for specific time windows (for example, a two-hour lab session or a lecturer bringing a whole class).

---

## 2. How it works (plain explanation)

The system is a single program (`app.py`) that runs three things at once:

1. **A camera loop** — constantly grabs pictures from the Pi camera.
2. **A recognition loop** — several times per second it takes the latest picture, looks for a face, and decides what to do (open the door, sound the alarm, or do nothing).
3. **A web server** — serves the admin dashboard and the student portal in a browser, on the local network.

When a face appears, the recognition loop turns it into a list of numbers called a *face embedding* (explained in [section 12](#12-how-face-recognition-works)), compares it to everyone enrolled, and makes a decision. Every decision is saved to a log and pushed live to any open dashboard so admins see events appear instantly.

---

## 3. Who can open the door

There are three kinds of people:

| Type | How they get access |
|------|---------------------|
| **Staff** (lab admins, lecturers, responsibles) | Permanent, unconditional access. Once their face is enrolled, the door always opens for them. |
| **Students with a grant** | Access only during a time window an admin has granted them. Outside that window, the door stays locked. |
| **Unknown people** | Never get access. The buzzer sounds and alerts are sent. |

**Access grants** are the core idea. A grant says "this student may enter between time A and time B." Grants are created two ways:

- **Admin-initiated** — an admin grants access directly (for example, a lecturer brings a class; the admin grants the whole list of students for two hours).
- **Student-initiated** — a student signs into the student portal and requests access, uploading their student card as proof of identity. An admin reviews the request and approves or denies it, optionally adjusting the time.

A student can also **check out early** from the student portal if they leave before their time is up, which ends their grant and records the real exit.

---

## 4. Hardware you need

- **Raspberry Pi Zero 2 W** with Raspberry Pi OS (Bookworm) on a 32 GB or larger SD card.
- **Raspberry Pi Camera** connected to the camera (CSI) port.
- **MG995 servo motor** (moves the door latch).
- **External 5V 2A power supply for the servo** — do **not** power the MG995 from the Pi; it draws too much current and will crash or damage the Pi.
- **Active buzzer** (the alarm).
- **Jumper wires and a breadboard.**

---

## 5. Wiring

Pin numbers below use **BCM numbering** (the GPIO numbers, not the physical pin positions).

```
MG995 servo:
  Orange (signal) -> GPIO 18   (physical pin 12)
  Red    (VCC)    -> External 5V (+)
  Brown  (GND)    -> External 5V (-)  AND  Pi GND   <-- COMMON GROUND REQUIRED

Buzzer:
  +  -> GPIO 17   (physical pin 11)
  -  -> Pi GND    (physical pin 6)

Camera -> CSI ribbon port
```

> **The single most common cause of a jittering or dead servo is a missing common ground.** The servo's external power supply and the Pi must share a ground connection. Connect the servo power supply's negative terminal to one of the Pi's GND pins.

---

## 6. Software setup, step by step

These steps are run **on the Raspberry Pi**, in a terminal. If you are connecting to the Pi from another computer, you do this over SSH.

### 6.1 Update the Pi and enable the camera

```bash
sudo apt update && sudo apt full-upgrade -y
sudo raspi-config      # Interface Options -> enable Camera, then reboot if asked
```

Confirm the camera is detected:

```bash
rpicam-hello --list-cameras
```

If this lists a camera, you are good. If it shows nothing, re-seat the camera ribbon cable and check it is enabled in `raspi-config`.

### 6.2 Install the system packages

These come from the Pi's package manager (`apt`), not from Python. They provide the camera and GPIO control:

```bash
sudo apt install -y python3-picamera2 python3-libcamera \
                    python3-venv libatlas-base-dev
```

### 6.3 Get the project onto the Pi

```bash
cd ~
git clone <your-repository-url> smartdoor
cd smartdoor
```

(If you already have the folder, skip the clone and just `cd ~/smartdoor`.)

### 6.4 Create a Python environment and install dependencies

A *virtual environment* (venv) is an isolated space for this project's Python packages. The `--system-site-packages` flag lets it also see the camera/GPIO packages installed above.

```bash
python3 -m venv venv --system-site-packages
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

> The first install of `insightface` and `onnxruntime` (the face-recognition libraries) is slow on a Pi Zero 2 W — **expect 15 to 30 minutes**. This is normal. If it runs out of memory, add swap (see [Troubleshooting](#13-troubleshooting)).

**You must `source venv/bin/activate` every time you open a new terminal to run the project.** When the environment is active, your prompt shows `(venv)` at the start of the line. If you don't see `(venv)`, the project will report missing modules like `cv2`.

---

## 7. Configuration

All settings live in `config.py`. You can edit that file directly, or (safer) set values as environment variables so secrets never get committed to git.

The most important settings:

| Setting | What it is | Default |
|---------|-----------|---------|
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | Admin dashboard login | `admin` / `admin1234` |
| `SECRET_KEY` | Secures login sessions — change it | a placeholder |
| `SERVO_OPEN_ANGLE` / `SERVO_LOCKED_ANGLE` | Servo positions for open vs locked | tune to your latch |
| `RELOCK_DELAY_SECONDS` | How long the door stays open before auto-relock | 5 |
| `MATCH_THRESHOLD` | How strict face matching is (higher = stricter) | 0.45 |
| `DASHBOARD_URL` | Link included in alert messages | `http://dodos:5000` |

### Alert settings (optional but recommended)

| Setting | For |
|---------|-----|
| `SMS_ENABLED`, `INFOBIP_BASE_URL`, `INFOBIP_API_KEY`, `SMS_SENDER`, `SMS_TO` | SMS alerts via Infobip |
| `EMAIL_ENABLED`, `EMAIL_FROM`, `EMAIL_PASSWORD`, `EMAIL_TO` | Email alerts (Gmail) |
| `TELEGRAM_ENABLED`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Telegram alerts |

See [section 10](#10-the-alert-system-sms-email-telegram) for how to obtain these.

> **Security note:** never commit real API keys or passwords to git. Prefer setting them as environment variables. To regenerate a leaked key, do so in the relevant provider's dashboard.

### The dashboard URL and changing IP addresses

Alert messages include a link to the dashboard. Because the Pi's IP address can change between networks, the cleanest approach is to let the system fill in the current IP automatically when you start it:

```bash
export DASHBOARD_URL="http://$(hostname -I | awk '{print $1}'):5000"
```

Run that line before starting the app (see next section). The fallback in `config.py` uses the Pi's hostname (`http://dodos:5000`), which also works on networks that resolve hostnames.

---

## 8. Running the system

```bash
cd ~/smartdoor
source venv/bin/activate
export DASHBOARD_URL="http://$(hostname -I | awk '{print $1}'):5000"   # optional but recommended
python3 app.py
```

On startup you should see lines confirming the real camera and hardware are active, ending with:

```
[init] ready.
```

Then, from any device on the **same network** as the Pi, open a browser to:

```
http://<pi-ip-address>:5000
```

Find the Pi's IP with `hostname -I`. You'll land on a page letting you choose the **Admin** or **Student** portal.

To stop the system, press `Ctrl+C` in the terminal.

---

## 9. Using the two portals

The system has two completely separate web portals that share one database.

### Admin portal

Log in at `/admin/login` with your admin credentials. From here you can:

- **Dashboard** — live camera feed, door status, manual Open/Lock buttons, and a real-time feed of every access event.
- **Students** — list, search, register, edit, and remove students. Registering captures a face from the camera and (importantly) automatically adds the student to the school roster so they can create a portal account.
- **Staff** — register staff whose faces always open the door.
- **Roster** — the official list of valid registration numbers. Only people on this roster can create a student account. You can add entries here directly.
- **Grants** — give students time-limited access, either individually or as a whole class with a label like "CS301 Lecture." You can revoke or end grants early.
- **Requests** — review access requests submitted by students. Each shows the uploaded student card so you can verify identity before approving. You can adjust the start time and duration on approval.
- **Logs** — a complete, filterable history (by date, person type, status, or search text) with a CSV export for reports.

### Student portal

Students use `/student/login` and `/student/signup`. The flow:

1. **Sign up** — the student enters their registration number. The system checks it exists on the official roster (and that no account already exists for it), then the student sets a password.
2. **Request access** — the student picks a desired start time and duration, writes a note, and **uploads their student card** (required) plus an optional recommendation letter. Only one pending request is allowed at a time.
3. **Wait for approval** — an admin reviews and approves or denies. On approval, an access grant is created for the chosen window.
4. **Check out early** — if the student leaves before their time is up, they can end their session from the portal.

> **Why the student card upload matters:** a registration number is an identifier, not a secret — someone could know yours. So lab access is never granted on the registration number alone. The card upload is the real identity check: an admin visually confirms the card matches the roster before approving. This mirrors how university systems verify students.

---

## 10. The alert system (SMS, email, Telegram)

When an **unknown person** or a **known student without valid access** appears, the system sends alerts in the background (it never blocks the door logic while sending).

- **SMS (Infobip):** instant text alert that works on any phone with no internet needed. Sign up at infobip.com (free trial), verify your phone number, and copy your API key and base URL into the config. During the trial, SMS can only be delivered to your own verified number.
- **Email (Gmail):** includes the **snapshot photo** of the unknown person as an attachment, plus a link to the dashboard. Requires a Gmail **App Password** (turn on 2-Step Verification in your Google account, then create an App Password — use that 16-character password, not your normal one).
- **Telegram:** delivers the **snapshot photo** to a Telegram chat. Create a bot via @BotFather to get a token, and get your chat ID from @userinfobot.

Each channel can be turned on or off independently with its `*_ENABLED` flag in `config.py`. The photo is delivered via email and Telegram; SMS is text-only (plain SMS cannot carry images).

---

## 11. Project structure

```
smartdoor/
├── app.py              Main program: camera loop, recognition loop, web server
├── config.py           All settings (with environment-variable overrides)
├── camera.py           Reads frames from the Pi camera
├── hardware.py         Controls the servo (door latch) and buzzer
├── face_engine.py      Face detection and matching (InsightFace)
├── database.py         All database logic (SQLite)
├── notifier.py         Sends SMS, email, and Telegram alerts
├── requirements.txt    Python dependencies
├── data.db             The database file (created automatically)
├── student_photos/     Enrolled student face photos
├── staff_photos/       Enrolled staff face photos
├── snapshots/          Photos of unknown people (for alerts)
├── uploads/            Student-card and recommendation uploads
├── static/
│   └── style.css       The dashboard's visual design
└── templates/          The web pages (admin + student portals)
```

The database (`data.db`) holds: the school roster, students (with face data), staff, access grants, access requests, admin accounts, student accounts, and the event log.

---

## 12. How face recognition works

The system uses a pre-trained neural network (the `buffalo_sc` model from the InsightFace library) that turns any face image into a list of 512 numbers called an **embedding**. The network was trained so that two photos of the *same* person produce embeddings that are very close together, while *different* people produce embeddings far apart.

Recognition is then simple:

1. Enrol a person by storing the embedding of their face.
2. When a face appears at the door, compute its embedding.
3. Compare it to every stored embedding using **cosine similarity** (a measure of how close two embeddings are).
4. If the closest match scores above the threshold (`MATCH_THRESHOLD`, default 0.45), it's that person; otherwise the face is treated as unknown.

Raising the threshold makes the system stricter (fewer strangers wrongly accepted, but more genuine people occasionally missed); lowering it does the reverse.

---

## 13. Troubleshooting

| Problem | Fix |
|---------|-----|
| `ModuleNotFoundError: No module named 'cv2'` (or flask, etc.) | The virtual environment isn't active. Run `source venv/bin/activate` — your prompt should show `(venv)`. |
| Servo jitters or doesn't move | Check the **common ground** between the servo's power supply and the Pi. Verify wiring to GPIO 18. |
| Servo moves too fast / too jerky | In `hardware.py`, the servo moves in small steps; reduce the step size or increase the delay for slower, smoother motion. |
| Door opens the wrong way | Swap `SERVO_OPEN_ANGLE` and `SERVO_LOCKED_ANGLE` in `config.py`. |
| Camera not detected | Run `rpicam-hello --list-cameras`; re-seat the ribbon cable; enable the camera in `raspi-config`. |
| Recognises strangers as known people | Raise `MATCH_THRESHOLD` (e.g. 0.5–0.55) and re-enrol faces in good lighting. |
| Doesn't recognise enrolled people | Lower `MATCH_THRESHOLD` (e.g. 0.4); re-enrol in better light. |
| Out of memory while installing | Add swap: `sudo dphys-swapfile swapoff`, edit `/etc/dphys-swapfile` to set `CONF_SWAPSIZE=1024`, then `sudo dphys-swapfile setup && sudo dphys-swapfile swapon`. |
| A student can't sign up ("not in the roster") | Add their registration number on the **Roster** page, or register them as a student (which adds them to the roster automatically). |
| SMS not arriving | On the Infobip free trial, the destination number must be **verified** in your Infobip account. |
| Email not sending | Use a Gmail **App Password**, not your normal password; ensure 2-Step Verification is on. |
| Dashboard link in alerts doesn't open on a phone | The dashboard is only reachable on the same local network as the Pi. The link won't load over mobile data. |

---

## 14. Glossary

- **Embedding** — a list of 512 numbers representing a face; the basis of recognition.
- **Cosine similarity** — how the system measures whether two embeddings (two faces) are the same person.
- **Grant** — a record giving a student access between a start and end time.
- **Roster** — the official list of valid registration numbers; required for a student to create an account.
- **Servo** — the motor that physically moves the door latch.
- **GPIO** — the Pi's general-purpose pins used to control the servo and buzzer.
- **venv (virtual environment)** — an isolated space for this project's Python packages; activate it with `source venv/bin/activate`.
- **SSH** — a way to control the Pi from another computer's terminal over the network.
- **SQLite** — the lightweight database stored in the single file `data.db`.

---

*Built for a Raspberry Pi Zero 2 W using InsightFace, Flask, and SQLite.*
