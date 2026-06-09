"""
Main entry point for the Smart Door system.

Starts:
  1. The camera thread.
  2. A background recognition loop that decides open / alarm.
  3. A Flask web server: login, dashboard, live stream, register, logs, manual control.

Run with:  python3 app.py
"""
import os
import time
import threading
from datetime import datetime
from functools import wraps

import cv2
from flask import (Flask, render_template, request, redirect, url_for,
                   session, Response, jsonify, flash)

import config
import database as db
from camera import Camera
from face_engine import FaceEngine
from hardware import DoorHardware
import notifier

# ---------- init ----------
app = Flask(__name__)
app.secret_key = config.SECRET_KEY

db.init_db()
os.makedirs(config.KNOWN_FACES_DIR, exist_ok=True)
os.makedirs(config.SNAPSHOTS_DIR, exist_ok=True)

print("[init] starting camera...")
camera = Camera()
print("[init] loading face model (this can take a minute on first run)...")
engine = FaceEngine()
print("[init] initializing hardware...")
door = DoorHardware()
print("[init] ready.")

# shared state for the dashboard
state = {
    "last_person": "—",
    "last_status": "—",
    "last_time": "—",
    "door": "Locked",
}
_last_seen = {}  # person/"unknown" -> timestamp, for cooldown


# ---------- recognition loop ----------
def recognition_loop():
    frame_count = 0
    while True:
        frame = camera.get_frame()
        if frame is None:
            time.sleep(0.1)
            continue

        frame_count += 1
        if frame_count % config.RECOGNIZE_EVERY_N_FRAMES != 0:
            time.sleep(0.03)
            continue

        try:
            faces = engine.get_faces(frame)
            face = engine.largest_face(faces)
            if face is None:
                continue

            known = db.get_all_users()
            name, score = engine.match(face.normed_embedding, known)
            now = time.time()

            if name:  # recognized
                if now - _last_seen.get(name, 0) < config.COOLDOWN_SECONDS:
                    continue
                _last_seen[name] = now
                door.open_door(auto_relock=True)
                _update_state(name, "Authorized", "Door opened")
                db.add_log(name, "Authorized", "Door opened")
            else:      # unknown
                if now - _last_seen.get("unknown", 0) < config.COOLDOWN_SECONDS:
                    continue
                _last_seen["unknown"] = now
                snap = _save_snapshot(frame)
                door.alarm(seconds=3)
                notifier.notify_unknown(snap)
                _update_state("Unknown", "Unauthorized", "Alarm + alert sent")
                db.add_log("Unknown", "Unauthorized",
                           "Alarm + alert sent", os.path.basename(snap))
        except Exception as e:
            print(f"[loop] error: {e}")
        time.sleep(0.03)


def _save_snapshot(frame):
    fname = f"unknown_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
    path = os.path.join(config.SNAPSHOTS_DIR, fname)
    cv2.imwrite(path, frame)
    return path


def _update_state(person, status, action):
    state["last_person"] = person
    state["last_status"] = status
    state["last_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    state["door"] = "Open" if door.is_open else "Locked"


# ---------- auth ----------
def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if (request.form.get("username") == config.ADMIN_USERNAME and
                request.form.get("password") == config.ADMIN_PASSWORD):
            session["logged_in"] = True
            return redirect(url_for("dashboard"))
        flash("Invalid credentials")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------- dashboard ----------
@app.route("/")
@login_required
def dashboard():
    return render_template("dashboard.html",
                           state=state, logs=db.get_logs(20))


def _mjpeg():
    while True:
        jpg = camera.get_jpeg()
        if jpg:
            yield (b"--frame\r\n"
                   b"Content-Type: image/jpeg\r\n\r\n" + jpg + b"\r\n")
        time.sleep(0.05)


@app.route("/video")
@login_required
def video():
    return Response(_mjpeg(),
                    mimetype="multipart/x-mixed-replace; boundary=frame")


@app.route("/open", methods=["POST"])
@login_required
def open_door():
    door.open_door(auto_relock=True)
    state["door"] = "Open"
    db.add_log("Owner", "Manual", "Opened remotely")
    return jsonify(status="open")


@app.route("/lock", methods=["POST"])
@login_required
def lock_door():
    door.lock_door()
    state["door"] = "Locked"
    db.add_log("Owner", "Manual", "Locked remotely")
    return jsonify(status="locked")


@app.route("/status")
@login_required
def status():
    state["door"] = "Open" if door.is_open else "Locked"
    return jsonify(state)


# ---------- registration ----------
@app.route("/register", methods=["GET", "POST"])
@login_required
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            flash("Name required")
            return redirect(url_for("register"))

        frame = camera.get_frame()
        if frame is None:
            flash("Camera not ready")
            return redirect(url_for("register"))

        faces = engine.get_faces(frame)
        face = engine.largest_face(faces)
        if face is None:
            flash("No face detected — look at the camera and try again")
            return redirect(url_for("register"))

        img_name = f"{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
        img_path = os.path.join(config.KNOWN_FACES_DIR, img_name)
        cv2.imwrite(img_path, frame)

        db.add_user(name, face.normed_embedding, img_name)
        flash(f"Registered {name} successfully!")
        return redirect(url_for("register"))

    return render_template("register.html", users=db.get_all_users())


@app.route("/delete_user/<int:user_id>", methods=["POST"])
@login_required
def delete_user(user_id):
    db.delete_user(user_id)
    return redirect(url_for("register"))


# ---------- run ----------
if __name__ == "__main__":
    t = threading.Thread(target=recognition_loop, daemon=True)
    t.start()
    try:
        app.run(host=config.WEB_HOST, port=config.WEB_PORT,
                threaded=True, use_reloader=False)
    finally:
        camera.stop()
        door.cleanup()
