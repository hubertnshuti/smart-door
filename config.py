"""
Central configuration for the Smart Door system.
Edit the values here, or (better) set them as environment variables.
"""
import os

# ---------- GPIO PINS (BCM numbering) ----------
SERVO_PIN = 18          # MG995 signal wire -> GPIO 18 (physical pin 12)
BUZZER_PIN = 17         # Buzzer +          -> GPIO 17 (physical pin 11)

# ---------- SERVO ANGLES ----------
# Tune these to match how your latch is mounted.
SERVO_LOCKED_ANGLE = 125      # position when door is locked
SERVO_OPEN_ANGLE =0       # position that pulls the bolt open
RELOCK_DELAY_SECONDS = 5    # auto re-lock after this many seconds

# ---------- FACE RECOGNITION ----------
# buffalo_sc is the lightest InsightFace bundle (good for Pi Zero 2 W).
FACE_MODEL = "buffalo_sc"
# Cosine-similarity threshold. Higher = stricter. 0.4-0.5 is typical.
MATCH_THRESHOLD = 0.45
# Run recognition only every Nth frame to save CPU.
RECOGNIZE_EVERY_N_FRAMES = 10
# Seconds to wait before reacting to the same person again (avoid spam).
COOLDOWN_SECONDS = 15

# ---------- CAMERA ----------
CAMERA_WIDTH = 640
CAMERA_HEIGHT = 480

# ---------- WEB SERVER ----------
WEB_HOST = "0.0.0.0"
WEB_PORT = 5000
# Login credentials for the dashboard. CHANGE THESE.
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "1234")
SECRET_KEY = os.environ.get("SECRET_KEY", "please-change-this-secret-key")

# ---------- EMAIL (Gmail example) ----------
# Create an "App Password" in your Google account (NOT your normal password).
EMAIL_ENABLED = True
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
EMAIL_FROM = os.environ.get("EMAIL_FROM", "youremail@gmail.com")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "your-app-password")
EMAIL_TO = os.environ.get("EMAIL_TO", "youremail@gmail.com")

# ---------- TELEGRAM ----------
# Create a bot via @BotFather, then get your chat id from @userinfobot.
TELEGRAM_ENABLED = True
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "your-bot-token")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "your-chat-id")

# ---------- SMS (Infobip) ----------
SMS_ENABLED = True
INFOBIP_BASE_URL = os.environ.get("INFOBIP_BASE_URL", "qwelwq.api.infobip.com")
INFOBIP_API_KEY  = os.environ.get("INFOBIP_API_KEY", "53fd6397ff8ca9a8b449a4d1c61a5498-84c7684c-6472-4ade-aa06-5a9ce90affb4")
SMS_SENDER = "ServiceSMS"        # required test sender during free trial
SMS_TO = os.environ.get("SMS_TO", "250780354633")   # your verified number

# ---------- PATHS ----------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data.db")
KNOWN_FACES_DIR = os.path.join(BASE_DIR, "known_faces")
SNAPSHOTS_DIR = os.path.join(BASE_DIR, "snapshots")
