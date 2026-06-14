"""
Central configuration for the Lab Access Control system.
Edit the values here, or set them as environment variables.
"""
import os

# ---------- GPIO PINS (BCM numbering) ----------
SERVO_PIN = 18
BUZZER_PIN = 17

# ---------- SERVO ANGLES ----------
SERVO_LOCKED_ANGLE = 125
SERVO_OPEN_ANGLE = 0
RELOCK_DELAY_SECONDS = 5

# ---------- FACE RECOGNITION ----------
FACE_MODEL = "buffalo_sc"
MATCH_THRESHOLD = 0.45
RECOGNIZE_EVERY_N_FRAMES = 10
COOLDOWN_SECONDS = 15

# ---------- CAMERA ----------
CAMERA_WIDTH = 640
CAMERA_HEIGHT = 480

# ---------- WEB SERVER ----------
WEB_HOST = "0.0.0.0"
WEB_PORT = 5000
SECRET_KEY = os.environ.get("SECRET_KEY", "please-change-this-secret-key-lab")

# ---------- ADMIN SEED ----------
DEFAULT_ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
DEFAULT_ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin1234")

# ---------- DEMO STUDENT CREDENTIALS (documented in SETUP.md) ----------
DEMO_STUDENT_REG      = "DEMO/2024/001"
DEMO_STUDENT_PASSWORD = "demo1234"

# ---------- EMAIL ----------
EMAIL_ENABLED = True
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
EMAIL_FROM     = os.environ.get("EMAIL_FROM",     "furahadieudonnee1@gmail.com")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "mdia vohx ycbn mcad")
EMAIL_TO       = os.environ.get("EMAIL_TO",       "furahadieudonnee1@gmail.com")

# ---------- TELEGRAM ----------
TELEGRAM_ENABLED = True
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "your-bot-token")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID",   "your-chat-id")

# ---------- SMS (Infobip) ----------
SMS_ENABLED = True
INFOBIP_BASE_URL = os.environ.get("INFOBIP_BASE_URL", "d8ypyl.api.infobip.com")
INFOBIP_API_KEY  = os.environ.get("INFOBIP_API_KEY", "ff5f62d200256e74a517dd7f25dd5ae3-4b1e6990-9c3b-43a5-a857-ba67c6250d42")
SMS_SENDER = "ServiceSMS"        # required test sender during free trial
SMS_TO = os.environ.get("SMS_TO", "250781497409")   # your verified number

# ---------- GRANT DURATION PRESETS (minutes) ----------
GRANT_DURATION_PRESETS = [30, 60, 90, 120, 180, 240]

# ---------- FILE UPLOADS ----------
MAX_UPLOAD_BYTES = 5 * 1024 * 1024   # 5 MB per file

# ---------- PATHS ----------
BASE_DIR            = os.path.dirname(os.path.abspath(__file__))
DB_PATH             = os.path.join(BASE_DIR, "data.db")
KNOWN_FACES_DIR     = os.path.join(BASE_DIR, "known_faces")
SNAPSHOTS_DIR       = os.path.join(BASE_DIR, "snapshots")
STUDENT_PHOTOS_DIR  = os.path.join(BASE_DIR, "student_photos")
STAFF_PHOTOS_DIR    = os.path.join(BASE_DIR, "staff_photos")
UPLOADS_DIR         = os.path.join(BASE_DIR, "uploads")
UPLOADS_CARDS_DIR   = os.path.join(BASE_DIR, "uploads", "cards")
UPLOADS_RECO_DIR    = os.path.join(BASE_DIR, "uploads", "reco")
