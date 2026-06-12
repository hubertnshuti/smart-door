"""
Lab Access Control — main entry point.

Two fully separated portals sharing one SQLite database:
  Admin portal  — /admin/login  (session key: logged_in)
  Student portal — /student/    (session key: student_reg)

Run:  python app.py
"""
import csv
import io
import os
import secrets
import time
import threading
from datetime import datetime, timedelta
from functools import wraps

import cv2
from flask import (Flask, render_template, request, redirect, url_for,
                   session, Response, jsonify, flash, send_from_directory,
                   make_response)
from flask_socketio import SocketIO
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.security import check_password_hash
from werkzeug.utils import secure_filename

import config
import database as db
from camera import get_camera
from face_engine import FaceEngine
from hardware import get_hardware
import notifier

# ── app init ──────────────────────────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = config.SECRET_KEY
app.config["MAX_CONTENT_LENGTH"] = config.MAX_UPLOAD_BYTES

socketio = SocketIO(app, async_mode="threading", cors_allowed_origins="*")

# ── db + dirs ─────────────────────────────────────────────────────────────────
db.init_db()

for d in (config.KNOWN_FACES_DIR, config.SNAPSHOTS_DIR,
          config.STUDENT_PHOTOS_DIR, config.STAFF_PHOTOS_DIR,
          config.UPLOADS_CARDS_DIR, config.UPLOADS_RECO_DIR):
    os.makedirs(d, exist_ok=True)

db.seed_demo_data()

# ── hardware + camera + engine ────────────────────────────────────────────────
print("[init] starting camera...")
camera = get_camera()
print("[init] loading face model (first run may take a minute)...")
engine = FaceEngine()
print("[init] initializing hardware...")
door = get_hardware()
print("[init] ready.\n")

# ── shared recognition state ──────────────────────────────────────────────────
state = {
    "last_person": "—",
    "last_type":   "—",
    "last_status": "—",
    "last_time":   "—",
}
_last_seen = {}


# ── upload helpers ─────────────────────────────────────────────────────────────
_ALLOWED_IMG = {"jpg", "jpeg", "png", "webp", "gif"}
_ALLOWED_DOC = {"jpg", "jpeg", "png", "webp", "gif", "pdf"}


def _ext(filename):
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def _save_upload(file_obj, directory, prefix, allowed_exts):
    """Validate and save an uploaded file; return filename or None on error."""
    if not file_obj or not file_obj.filename:
        return None
    ext = _ext(file_obj.filename)
    if ext not in allowed_exts:
        return None
    fname = f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(4)}.{ext}"
    file_obj.save(os.path.join(directory, fname))
    return fname


# ── recognition loop ──────────────────────────────────────────────────────────
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
            face  = engine.largest_face(faces)
            if face is None:
                continue
            known  = db.get_all_known_faces()
            match  = engine.match(face.normed_embedding, known)
            now    = time.time()
            now_dt = datetime.now()

            if match:
                key = f"{match['type']}_{match['id']}"
                if now - _last_seen.get(key, 0) < config.COOLDOWN_SECONDS:
                    continue
                _last_seen[key] = now
                if match["type"] == "staff":
                    door.open_door(auto_relock=True)
                    action = f"Door opened — Staff ({match['name']})"
                    _emit_event(match["name"], "staff", "Granted", action, True)
                    db.add_log(match["name"], "staff", "Granted", action)
                else:
                    student = db.get_student_by_id(match["id"])
                    reg     = student["reg_number"] if student else None
                    grant   = db.get_active_grant(match["id"], now_dt)
                    if grant:
                        door.open_door(auto_relock=True)
                        label  = grant["class_label"] or grant["reason"]
                        action = f"Door opened — {label}"
                        _emit_event(match["name"], "student", "Granted", action, True, reg)
                        db.add_log(match["name"], "student", "Granted", action, reg)
                    else:
                        door.alarm(seconds=1)
                        action = "Access denied — no active grant"
                        _emit_event(match["name"], "student", "Denied", action, False, reg)
                        db.add_log(match["name"], "student", "Denied", action, reg)
            else:
                if now - _last_seen.get("unknown", 0) < config.COOLDOWN_SECONDS:
                    continue
                _last_seen["unknown"] = now
                snap = _save_snapshot(frame)
                door.alarm(seconds=3)
                notifier.notify_unknown(snap)
                action = "Alarm + alert sent"
                _emit_event("Unknown", "unknown", "Denied", action, False)
                db.add_log("Unknown", "unknown", "Denied", action,
                           snapshot=os.path.basename(snap))
        except Exception as e:
            print(f"[loop] error: {e}")
        time.sleep(0.03)


def _save_snapshot(frame):
    fname = f"unknown_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
    path  = os.path.join(config.SNAPSHOTS_DIR, fname)
    cv2.imwrite(path, frame)
    return path


def _emit_event(person, ptype, status, action, door_opened, reg=None):
    state["last_person"] = person
    state["last_type"]   = ptype
    state["last_status"] = status
    state["last_time"]   = datetime.now().strftime("%H:%M:%S")
    event = {
        "person":      person,
        "type":        ptype,
        "reg_number":  reg or "",
        "status":      status,
        "action":      action,
        "time":        datetime.now().strftime("%H:%M:%S"),
        "door_opened": door_opened,
    }
    socketio.emit("access_event", event)
    socketio.emit("door_status", {"is_open": door.is_open})


# ── auth decorators ───────────────────────────────────────────────────────────
def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return wrapper


def student_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("student_reg"):
            return redirect(url_for("student_login"))
        return f(*args, **kwargs)
    return wrapper


# ── context processor (injects pending badge count into all admin templates) ──
@app.context_processor
def inject_admin_globals():
    ctx = {}
    if session.get("logged_in"):
        ctx["pending_requests_count"] = db.get_pending_requests_count()
    return ctx


# ── error handlers ────────────────────────────────────────────────────────────
@app.errorhandler(RequestEntityTooLarge)
def handle_too_large(e):
    flash("File too large. Maximum size is 5 MB per file.")
    return redirect(request.referrer or url_for("student_request_form")), 413


# ══════════════════════════════════════════════════════════════════════════════
#  ADMIN PORTAL
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        admin    = db.get_admin_by_username(username)
        if admin and check_password_hash(admin["password_hash"], password):
            session["logged_in"] = True
            session["username"]  = username
            return redirect(url_for("dashboard"))
        flash("Invalid username or password")
    return render_template("login.html")


@app.route("/login")
def login_redirect():
    return redirect(url_for("admin_login"))


@app.route("/logout")
def logout():
    session.pop("logged_in", None)
    session.pop("username",   None)
    return redirect(url_for("admin_login"))


# ── root landing ──────────────────────────────────────────────────────────────
@app.route("/")
def index():
    if session.get("logged_in"):
        return redirect(url_for("dashboard"))
    if session.get("student_reg"):
        return redirect(url_for("student_dashboard"))
    return render_template("landing.html")


# ── dashboard ─────────────────────────────────────────────────────────────────
@app.route("/dashboard")
@admin_required
def dashboard():
    return render_template("dashboard.html",
                           state=state, stats=db.get_dashboard_stats(),
                           initial_logs=db.get_logs(limit=25),
                           door_open=door.is_open)


def _mjpeg():
    while True:
        jpg = camera.get_jpeg()
        if jpg:
            yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpg + b"\r\n")
        time.sleep(0.05)


@app.route("/video")
@admin_required
def video():
    return Response(_mjpeg(), mimetype="multipart/x-mixed-replace; boundary=frame")


@app.route("/open", methods=["POST"])
@admin_required
def open_door():
    door.open_door(auto_relock=True)
    who = session.get("username", "admin")
    db.add_log(who, "admin", "Manual", "Opened remotely via dashboard")
    socketio.emit("door_status", {"is_open": True})
    socketio.emit("access_event", {
        "person": who, "type": "admin", "reg_number": "",
        "status": "Manual", "action": "Door opened manually",
        "time": datetime.now().strftime("%H:%M:%S"), "door_opened": True,
    })
    return jsonify(status="open", is_open=True)


@app.route("/lock", methods=["POST"])
@admin_required
def lock_door():
    door.lock_door()
    who = session.get("username", "admin")
    db.add_log(who, "admin", "Manual", "Locked remotely via dashboard")
    socketio.emit("door_status", {"is_open": False})
    socketio.emit("access_event", {
        "person": who, "type": "admin", "reg_number": "",
        "status": "Manual", "action": "Door locked manually",
        "time": datetime.now().strftime("%H:%M:%S"), "door_opened": False,
    })
    return jsonify(status="locked", is_open=False)


@app.route("/status")
@admin_required
def status():
    return jsonify({**state, "door_open": door.is_open})


# ── students ──────────────────────────────────────────────────────────────────
@app.route("/students")
@admin_required
def students():
    search = request.args.get("q", "").strip()
    all_s  = db.get_all_students()
    if search:
        sl = search.lower()
        all_s = [s for s in all_s
                 if sl in s["name"].lower() or sl in s["reg_number"].lower()]
    return render_template("students.html", students=all_s, search=search)


@app.route("/students/register", methods=["GET", "POST"])
@admin_required
def students_register():
    if request.method == "POST":
        reg          = request.form.get("reg_number", "").strip()
        name         = request.form.get("name", "").strip()
        program      = request.form.get("program", "").strip()
        capture_face = request.form.get("capture_face") == "1"

        if not reg or not name:
            flash("Registration number and name are required.")
            return redirect(url_for("students_register"))

        existing = db.get_student_by_reg(reg)

        if capture_face:
            frame = camera.get_frame()
            if frame is None:
                flash("Camera not ready — try again.")
                return redirect(url_for("students_register"))
            faces = engine.get_faces(frame)
            face  = engine.largest_face(faces)
            if face is None:
                flash("No face detected — look at the camera and try again.")
                return redirect(url_for("students_register"))
            fname = f"{reg.replace('/', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
            cv2.imwrite(os.path.join(config.STUDENT_PHOTOS_DIR, fname), frame)
            if existing:
                db.update_student_face(existing["id"], fname, face.normed_embedding)
                flash(f"Face updated for {existing['name']}.")
            else:
                db.add_student(reg, name, program, fname, face.normed_embedding)
                flash(f"Student {name} registered with face capture.")
            db.upsert_roster_entry(reg, name, program)
        else:
            if existing:
                flash(f"Reg number {reg} already exists. Open the student's edit page to update info.")
            else:
                db.add_student(reg, name, program)
                db.upsert_roster_entry(reg, name, program)
                flash(f"Student {name} added — enrol their face from the edit page.")

        return redirect(url_for("students_register"))

    return render_template("students_register.html", students=db.get_all_students())


@app.route("/students/<int:sid>/edit", methods=["GET", "POST"])
@admin_required
def edit_student(sid):
    student = db.get_student_by_id(sid)
    if not student:
        flash("Student not found.")
        return redirect(url_for("students"))

    if request.method == "POST":
        action = request.form.get("action", "info")

        if action == "face":
            frame = camera.get_frame()
            if frame is None:
                flash("Camera not ready — try again.")
                return redirect(url_for("edit_student", sid=sid))
            faces = engine.get_faces(frame)
            face  = engine.largest_face(faces)
            if face is None:
                flash("No face detected — make sure the student is facing the camera.")
                return redirect(url_for("edit_student", sid=sid))
            reg   = student["reg_number"]
            fname = f"{reg.replace('/', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
            cv2.imwrite(os.path.join(config.STUDENT_PHOTOS_DIR, fname), frame)
            db.update_student_face(sid, fname, face.normed_embedding)
            flash("Face photo and embedding updated successfully.")

        else:  # action == "info"
            name    = request.form.get("name", "").strip()
            program = request.form.get("program", "").strip()
            reg     = request.form.get("reg_number", "").strip()
            if not name or not reg:
                flash("Name and registration number are required.")
                return redirect(url_for("edit_student", sid=sid))
            # Check reg uniqueness if changed
            clash = db.get_student_by_reg(reg)
            if clash and clash["id"] != sid:
                flash(f"Reg number {reg} is already used by another student.")
                return redirect(url_for("edit_student", sid=sid))
            db.update_student_info(sid, name, program, reg)
            db.upsert_roster_entry(reg, name, program)
            flash("Student information updated.")

        return redirect(url_for("edit_student", sid=sid))

    grants = db.get_grants_by_student_id(sid)
    return render_template("students_edit.html",
                           student=student, grants=grants)


@app.route("/students/<int:sid>/delete", methods=["POST"])
@admin_required
def delete_student(sid):
    db.delete_student(sid)
    flash("Student removed.")
    return redirect(url_for("students"))


# ── roster management ─────────────────────────────────────────────────────────
@app.route("/roster")
@admin_required
def roster_list():
    return render_template("roster.html", roster=db.get_roster_with_status())


@app.route("/roster/add", methods=["POST"])
@admin_required
def roster_add():
    reg     = request.form.get("reg_number", "").strip().upper()
    name    = request.form.get("name", "").strip()
    program = request.form.get("program", "").strip()
    if not reg or not name:
        flash("Registration number and name are required.")
        return redirect(url_for("roster_list"))
    db.upsert_roster_entry(reg, name, program)
    flash(f"{reg} — {name} added to roster.")
    return redirect(url_for("roster_list"))


@app.route("/roster/<path:reg>/delete", methods=["POST"])
@admin_required
def roster_delete_entry(reg):
    db.delete_roster_entry(reg)
    flash(f"Removed {reg} from roster.")
    return redirect(url_for("roster_list"))


# ── staff ─────────────────────────────────────────────────────────────────────
@app.route("/staff")
@admin_required
def staff():
    return render_template("staff.html", staff=db.get_all_staff())


@app.route("/staff/register", methods=["GET", "POST"])
@admin_required
def staff_register():
    if request.method == "POST":
        name         = request.form.get("name", "").strip()
        role         = request.form.get("role", "").strip()
        capture_face = request.form.get("capture_face") == "1"
        if not name or not role:
            flash("Name and role are required.")
            return redirect(url_for("staff_register"))
        if capture_face:
            frame = camera.get_frame()
            if frame is None:
                flash("Camera not ready.")
                return redirect(url_for("staff_register"))
            faces = engine.get_faces(frame)
            face  = engine.largest_face(faces)
            if face is None:
                flash("No face detected — try again.")
                return redirect(url_for("staff_register"))
            fname = f"staff_{name.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
            cv2.imwrite(os.path.join(config.STAFF_PHOTOS_DIR, fname), frame)
            db.add_staff(name, role, fname, face.normed_embedding)
            flash(f"{name} registered with face capture.")
        else:
            db.add_staff(name, role)
            flash(f"{name} added (no face yet).")
        return redirect(url_for("staff_register"))
    return render_template("staff_register.html", staff=db.get_all_staff())


@app.route("/staff/<int:sid>/delete", methods=["POST"])
@admin_required
def delete_staff(sid):
    db.delete_staff(sid)
    flash("Staff member removed.")
    return redirect(url_for("staff"))


# ── grants ────────────────────────────────────────────────────────────────────
@app.route("/grants")
@admin_required
def grants():
    now_str    = datetime.now().isoformat(timespec="seconds")
    all_grants = db.get_all_grants(include_expired=False)
    active     = [g for g in all_grants if g["start_time"] <= now_str]
    upcoming   = [g for g in all_grants if g["start_time"] > now_str]
    return render_template("grants.html", active=active, upcoming=upcoming,
                           presets=config.GRANT_DURATION_PRESETS)


@app.route("/grants/individual", methods=["POST"])
@admin_required
def grant_individual():
    reg_raw  = request.form.get("reg_numbers", "")
    duration = request.form.get("duration", "60")
    who      = session.get("username", "admin")
    try:
        mins = int(duration)
    except ValueError:
        flash("Invalid duration.")
        return redirect(url_for("grants"))
    regs = [r.strip() for r in reg_raw.replace(",", "\n").splitlines() if r.strip()]
    if not regs:
        flash("No registration numbers provided.")
        return redirect(url_for("grants"))
    start = datetime.now()
    end   = start + timedelta(minutes=mins)
    ok, missing = [], []
    for reg in regs:
        s = db.get_student_by_reg(reg)
        if not s:
            missing.append(reg)
        else:
            db.create_grant(s["id"], who, "individual", None, start, end)
            ok.append(reg)
    if ok:
        flash(f"Access granted to {len(ok)} student(s) for {mins} min.")
    if missing:
        flash(f"Not found in students: {', '.join(missing)}")
    return redirect(url_for("grants"))


@app.route("/grants/class", methods=["POST"])
@admin_required
def grant_class():
    class_label = request.form.get("class_label", "").strip()
    reg_raw     = request.form.get("reg_numbers", "")
    duration    = request.form.get("duration", "60")
    who         = session.get("username", "admin")
    if not class_label:
        flash("Class label is required.")
        return redirect(url_for("grants"))
    try:
        mins = int(duration)
    except ValueError:
        flash("Invalid duration.")
        return redirect(url_for("grants"))
    regs  = [r.strip() for r in reg_raw.replace(",", "\n").splitlines() if r.strip()]
    start = datetime.now()
    end   = start + timedelta(minutes=mins)
    ok, missing = [], []
    for reg in regs:
        s = db.get_student_by_reg(reg)
        if not s:
            missing.append(reg)
        else:
            db.create_grant(s["id"], who, "class", class_label, start, end)
            ok.append(reg)
    if ok:
        flash(f"Class grant '{class_label}' created for {len(ok)} student(s) ({mins} min).")
    if missing:
        flash(f"Not found: {', '.join(missing)}")
    return redirect(url_for("grants"))


@app.route("/grants/<int:gid>/revoke", methods=["POST"])
@admin_required
def revoke_grant(gid):
    db.revoke_grant(gid)
    flash("Grant revoked.")
    return redirect(url_for("grants"))


@app.route("/grants/<int:gid>/checkout", methods=["POST"])
@admin_required
def admin_checkout(gid):
    """Admin-side early checkout — ends a grant immediately."""
    db.revoke_grant(gid)
    who = session.get("username", "admin")
    db.add_log(who, "admin", "Manual", f"Admin ended grant #{gid} early")
    socketio.emit("access_event", {
        "person": who, "type": "admin", "reg_number": "",
        "status": "Manual", "action": f"Grant #{gid} ended early by admin",
        "time": datetime.now().strftime("%H:%M:%S"), "door_opened": False,
    })
    flash("Grant ended early.")
    return redirect(url_for("grants"))


# ── access requests (admin review queue) ─────────────────────────────────────
@app.route("/requests")
@admin_required
def requests_queue():
    pending  = db.get_all_access_requests(status="pending")
    reviewed = db.get_all_access_requests()   # all (for history section)
    reviewed = [r for r in reviewed if r["status"] != "pending"][:20]
    return render_template("requests.html",
                           pending=pending, reviewed=reviewed,
                           presets=config.GRANT_DURATION_PRESETS)


@app.route("/requests/<int:rid>/approve", methods=["POST"])
@admin_required
def approve_request(rid):
    req = db.get_access_request_by_id(rid)
    if not req:
        flash("Request not found.")
        return redirect(url_for("requests_queue"))

    start_str = request.form.get("start_time", "").strip()
    duration  = request.form.get("duration", str(req["desired_duration_min"]))
    who       = session.get("username", "admin")

    try:
        mins = int(duration)
    except ValueError:
        flash("Invalid duration.")
        return redirect(url_for("requests_queue"))

    try:
        # datetime-local input gives "YYYY-MM-DDTHH:MM"
        start_dt = datetime.fromisoformat(start_str.replace("T", " ") if "T" in start_str else start_str)
    except (ValueError, TypeError):
        start_dt = datetime.fromisoformat(req["desired_start"])

    grant_id = db.approve_request(rid, who, start_dt, mins)
    end_dt   = start_dt + timedelta(minutes=mins)

    student_name = req["student_name"]
    reg          = req["student_reg"]
    db.add_log(student_name, "student", "Granted",
               f"Access request approved by {who} — grant starts {start_dt.strftime('%H:%M')}",
               reg_number=reg)
    socketio.emit("access_event", {
        "person": student_name, "type": "student", "reg_number": reg,
        "status": "Granted",
        "action": f"Request approved — access {start_dt.strftime('%d/%m %H:%M')} to {end_dt.strftime('%H:%M')}",
        "time": datetime.now().strftime("%H:%M:%S"), "door_opened": False,
    })
    flash(f"Request approved. Access granted to {student_name} from {start_dt.strftime('%d/%m %H:%M')}.")
    return redirect(url_for("requests_queue"))


@app.route("/requests/<int:rid>/deny", methods=["POST"])
@admin_required
def deny_request(rid):
    req        = db.get_access_request_by_id(rid)
    admin_note = request.form.get("admin_note", "").strip()
    who        = session.get("username", "admin")
    db.deny_request(rid, who, admin_note)
    if req:
        db.add_log(req["student_name"], "student", "Denied",
                   f"Access request denied by {who}",
                   reg_number=req["student_reg"])
    flash("Request denied.")
    return redirect(url_for("requests_queue"))


# ── uploads serving (admin only) ─────────────────────────────────────────────
@app.route("/uploads/cards/<path:filename>")
@admin_required
def serve_card(filename):
    return send_from_directory(config.UPLOADS_CARDS_DIR, filename)


@app.route("/uploads/reco/<path:filename>")
@admin_required
def serve_reco(filename):
    return send_from_directory(config.UPLOADS_RECO_DIR, filename)


# ── logs ──────────────────────────────────────────────────────────────────────
@app.route("/logs")
@admin_required
def logs():
    today    = datetime.now().strftime("%Y-%m-%d")
    week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    preset   = request.args.get("preset", "today")
    date_from = request.args.get("date_from", today if preset == "today" else week_ago)
    date_to   = request.args.get("date_to",   today)
    ptype     = request.args.get("person_type", "")
    lstatus   = request.args.get("status", "")
    search    = request.args.get("search", "")
    log_list  = db.get_logs(limit=500, date_from=date_from, date_to=date_to,
                            person_type=ptype or None, status=lstatus or None,
                            search=search or None)
    summary   = db.get_log_summary(date_from=date_from, date_to=date_to,
                                   search=search or None)
    week_start = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    return render_template("logs.html", logs=log_list, summary=summary,
                           date_from=date_from, date_to=date_to,
                           person_type=ptype, status=lstatus, search=search,
                           preset=preset, today=today, week_start=week_start)


@app.route("/logs/export.csv")
@admin_required
def logs_export():
    today    = datetime.now().strftime("%Y-%m-%d")
    week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    date_from = request.args.get("date_from", week_ago)
    date_to   = request.args.get("date_to",   today)
    ptype     = request.args.get("person_type", "") or None
    lstatus   = request.args.get("status", "")      or None
    search    = request.args.get("search", "")       or None

    rows = db.get_logs(limit=10000, date_from=date_from, date_to=date_to,
                       person_type=ptype, status=lstatus, search=search)

    # Write UTF-8 with BOM so Excel auto-detects encoding and renders timestamps
    # and special characters (dashes, accented names) correctly.
    output  = io.BytesIO()
    wrapper = io.TextIOWrapper(output, encoding="utf-8-sig", newline="")
    writer  = csv.DictWriter(
        wrapper,
        fieldnames=["id", "timestamp", "person_name", "person_type",
                    "reg_number", "status", "action", "snapshot"],
        extrasaction="ignore",
        quoting=csv.QUOTE_ALL,
    )
    writer.writeheader()
    for row in rows:
        clean = {k: (row.get(k) or "") for k in writer.fieldnames}
        writer.writerow(clean)
    wrapper.flush()

    resp = make_response(output.getvalue())
    resp.headers["Content-Type"] = "text/csv; charset=utf-8-sig"
    resp.headers["Content-Disposition"] = (
        f'attachment; filename="access_log_{date_from}_{date_to}.csv"'
    )
    return resp


# ── admin photo/file serving ──────────────────────────────────────────────────
@app.route("/photos/student/<path:filename>")
@admin_required
def serve_student_photo(filename):
    return send_from_directory(config.STUDENT_PHOTOS_DIR, filename)


@app.route("/photos/staff/<path:filename>")
@admin_required
def serve_staff_photo(filename):
    return send_from_directory(config.STAFF_PHOTOS_DIR, filename)


@app.route("/snapshots/<path:filename>")
@admin_required
def serve_snapshot(filename):
    return send_from_directory(config.SNAPSHOTS_DIR, filename)


# ══════════════════════════════════════════════════════════════════════════════
#  STUDENT PORTAL
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/student/signup", methods=["GET", "POST"])
def student_signup():
    if request.method == "POST":
        reg  = request.form.get("reg_number", "").strip().upper()
        pw   = request.form.get("password", "")
        pw2  = request.form.get("password2", "")

        if not reg or not pw:
            flash("All fields are required.")
            return render_template("student_signup.html")

        if pw != pw2:
            flash("Passwords do not match.")
            return render_template("student_signup.html")

        if len(pw) < 6:
            flash("Password must be at least 6 characters.")
            return render_template("student_signup.html")

        roster = db.get_roster_by_reg(reg)
        if not roster:
            flash("That registration number is not in the school roster. "
                  "Contact the lab administrator.")
            return render_template("student_signup.html")

        if db.get_student_account_by_reg(reg):
            flash("An account already exists for that registration number.")
            return render_template("student_signup.html")

        db.create_student_account(reg, pw)
        flash(f"Account created for {roster['name']}. You can now sign in.")
        return redirect(url_for("student_login"))

    return render_template("student_signup.html")


@app.route("/student/login", methods=["GET", "POST"])
def student_login():
    if request.method == "POST":
        reg  = request.form.get("reg_number", "").strip().upper()
        pw   = request.form.get("password", "")
        acct = db.get_student_account_by_reg(reg)
        if acct and check_password_hash(acct["password_hash"], pw):
            roster = db.get_roster_by_reg(reg)
            session["student_reg"]  = reg
            session["student_name"] = roster["name"] if roster else reg
            return redirect(url_for("student_dashboard"))
        flash("Invalid registration number or password.")
    return render_template("student_login.html")


@app.route("/student/logout")
def student_logout():
    session.pop("student_reg",  None)
    session.pop("student_name", None)
    return redirect(url_for("student_login"))


@app.route("/student")
@student_required
def student_dashboard():
    reg      = session["student_reg"]
    roster   = db.get_roster_by_reg(reg)
    student  = db.get_student_by_reg(reg)
    now_dt   = datetime.now()

    active_grant   = db.get_active_grant(student["id"],  now_dt) if student else None
    upcoming_grant = db.get_upcoming_grant(student["id"], now_dt) if student and not active_grant else None
    pending_req    = db.get_pending_request_for_student(reg)
    recent_req     = db.get_most_recent_request(reg)

    # Determine portal status
    if active_grant:
        portal_status = "active"
    elif upcoming_grant:
        portal_status = "upcoming"
    elif pending_req:
        portal_status = "pending"
    elif recent_req and recent_req["status"] == "denied":
        portal_status = "denied"
    else:
        portal_status = "none"

    recent_logs = db.get_logs_by_reg(reg, limit=5) if student else []
    # Convenience aliases used directly in the template
    grant = active_grant or upcoming_grant
    current_req = pending_req or recent_req
    grant_duration_min = 0
    if grant and grant.get("start_time") and grant.get("end_time"):
        try:
            s = datetime.fromisoformat(grant["start_time"])
            e = datetime.fromisoformat(grant["end_time"])
            grant_duration_min = int((e - s).total_seconds() / 60)
        except Exception:
            pass

    return render_template("student_dashboard.html",
                           student_name=session.get("student_name") or (roster["name"] if roster else reg),
                           now=now_dt.isoformat(timespec="seconds"),
                           portal_status=portal_status,
                           grant=grant,
                           grant_duration_min=grant_duration_min,
                           request=current_req,
                           recent_logs=recent_logs)


@app.route("/student/request", methods=["GET", "POST"])
@student_required
def student_request_form():
    reg = session["student_reg"]

    # Block a second submission while one is already pending
    existing = db.get_pending_request_for_student(reg)
    if existing and request.method == "GET":
        flash("You already have a pending request. "
              "Wait for the admin to review it before submitting another.")
        return redirect(url_for("student_dashboard"))

    if request.method == "POST":
        if existing:
            flash("You already have a pending request.")
            return redirect(url_for("student_dashboard"))

        desired_start    = request.form.get("desired_start", "").strip()
        duration_str     = request.form.get("duration", "60")
        note             = request.form.get("note", "").strip()
        card_file        = request.files.get("card_image")
        reco_file_obj    = request.files.get("reco_file")

        if not desired_start:
            flash("Please select a start date and time.")
            return render_template("student_request.html",
                                   presets=config.GRANT_DURATION_PRESETS,
                                   default_start=desired_start or "")

        try:
            duration_min = int(duration_str)
        except ValueError:
            flash("Invalid duration.")
            return render_template("student_request.html",
                                   presets=config.GRANT_DURATION_PRESETS,
                                   default_start=desired_start or "")

        # Card image is mandatory — this is the primary identity-proof document.
        if not card_file or not card_file.filename:
            flash("Student card image is required.")
            return render_template("student_request.html",
                                   presets=config.GRANT_DURATION_PRESETS,
                                   default_start=desired_start or "")

        safe_prefix = reg.replace("/", "_")
        card_fname  = _save_upload(card_file, config.UPLOADS_CARDS_DIR,
                                   safe_prefix, _ALLOWED_IMG)
        if not card_fname:
            flash("Invalid card image. Upload JPG, PNG, or WebP (max 5 MB).")
            return render_template("student_request.html",
                                   presets=config.GRANT_DURATION_PRESETS,
                                   default_start=desired_start or "")

        reco_fname = _save_upload(reco_file_obj, config.UPLOADS_RECO_DIR,
                                  safe_prefix + "_reco", _ALLOWED_DOC)
        # reco_fname may be None — it's optional

        try:
            start_dt = datetime.fromisoformat(desired_start.replace("T", " "))
        except ValueError:
            flash("Invalid date/time format.")
            return render_template("student_request.html",
                                   presets=config.GRANT_DURATION_PRESETS,
                                   default_start="")

        db.create_access_request(reg, start_dt.isoformat(timespec="seconds"),
                                 duration_min, note, card_fname, reco_fname)
        flash("Access request submitted. You'll be notified when the admin reviews it.")
        return redirect(url_for("student_dashboard"))

    default_start = (datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")
    return render_template("student_request.html",
                           presets=config.GRANT_DURATION_PRESETS,
                           default_start=default_start)


@app.route("/student/checkout", methods=["POST"])
@student_required
def student_checkout():
    reg     = session["student_reg"]
    student = db.get_student_by_reg(reg)
    if not student:
        flash("No student record found for your account.")
        return redirect(url_for("student_dashboard"))

    grant = db.get_active_grant(student["id"])
    if not grant:
        flash("No active access grant to check out from.")
        return redirect(url_for("student_dashboard"))

    db.revoke_grant(grant["id"])
    name = session.get("student_name", reg)
    db.add_log(name, "student", "Manual", "Student checked out early", reg_number=reg)
    socketio.emit("access_event", {
        "person": name, "type": "student", "reg_number": reg,
        "status": "Manual", "action": "Student checked out early",
        "time": datetime.now().strftime("%H:%M:%S"), "door_opened": False,
    })
    socketio.emit("door_status", {"is_open": door.is_open})
    flash("You have checked out. Access grant ended.")
    return redirect(url_for("student_dashboard"))


@app.route("/student/history")
@student_required
def student_history():
    reg      = session["student_reg"]
    roster   = db.get_roster_by_reg(reg)
    student  = db.get_student_by_reg(reg)
    requests = db.get_requests_by_student(reg)
    grants   = db.get_grants_by_student_id(student["id"]) if student else []
    log_list = db.get_logs_by_reg(reg) if student else []
    return render_template("student_history.html",
                           roster=roster, requests=requests,
                           grants=grants, log_list=log_list)


# ── run ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    t = threading.Thread(target=recognition_loop, daemon=True)
    t.start()
    try:
        socketio.run(app, host=config.WEB_HOST, port=config.WEB_PORT,
                     use_reloader=False, allow_unsafe_werkzeug=True)
    finally:
        camera.stop()
        door.cleanup()
