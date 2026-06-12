"""
SQLite storage for the Lab Access Control system.

Tables: students, staff, access_grants, logs, admins,
        school_roster, student_accounts, access_requests.
All init operations are idempotent (CREATE TABLE IF NOT EXISTS).
"""
import os
import sqlite3
import numpy as np
from datetime import datetime, timedelta

from werkzeug.security import generate_password_hash

import config


def _connect():
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# ── schema ────────────────────────────────────────────────────────────────────

def init_db():
    conn = _connect()

    # Migrate old logs table if it uses the legacy single-column "person" schema.
    try:
        conn.execute("SELECT person_name FROM logs LIMIT 1")
    except sqlite3.OperationalError:
        conn.execute("DROP TABLE IF EXISTS logs")
        conn.commit()

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS students (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            reg_number TEXT    NOT NULL UNIQUE,
            name       TEXT    NOT NULL,
            program    TEXT,
            photo      TEXT,
            embedding  BLOB,
            created    TEXT
        );

        CREATE TABLE IF NOT EXISTS staff (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            name      TEXT NOT NULL,
            role      TEXT,
            photo     TEXT,
            embedding BLOB,
            created   TEXT
        );

        CREATE TABLE IF NOT EXISTS access_grants (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id  INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
            granted_by  TEXT    NOT NULL,
            reason      TEXT    NOT NULL DEFAULT 'individual',
            class_label TEXT,
            start_time  TEXT    NOT NULL,
            end_time    TEXT    NOT NULL,
            active      INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS logs (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp   TEXT,
            person_name TEXT,
            person_type TEXT,
            reg_number  TEXT,
            status      TEXT,
            action      TEXT,
            snapshot    TEXT
        );

        CREATE TABLE IF NOT EXISTS admins (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            username      TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL
        );

        -- Official school roster: pre-populated by admins; the authoritative
        -- list of who is allowed to create a student portal account.
        CREATE TABLE IF NOT EXISTS school_roster (
            reg_number TEXT PRIMARY KEY,
            name       TEXT NOT NULL,
            program    TEXT,
            phone      TEXT,   -- reserved for future OTP verification
            email      TEXT    -- reserved for future OTP verification
        );

        -- Student portal credentials. A student can create an account only if
        -- their reg_number exists in school_roster AND no account already exists.
        -- verified=0 means the account is active but email/SMS OTP has not been
        -- confirmed yet (OTP flow is a future extension — not built now).
        -- Identity is verified at access-request time by uploading a student card
        -- that an admin visually checks against the roster name/program.
        CREATE TABLE IF NOT EXISTS student_accounts (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            reg_number    TEXT NOT NULL UNIQUE REFERENCES school_roster(reg_number),
            password_hash TEXT NOT NULL,
            verified      INTEGER NOT NULL DEFAULT 0,
            created       TEXT
        );

        -- Access requests submitted by students from the self-service portal.
        -- card_image is mandatory; reco_file is optional (image or PDF).
        -- On approval the admin can adjust start/duration; a grant is created
        -- and grant_id is recorded here for auditability.
        CREATE TABLE IF NOT EXISTS access_requests (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            student_reg          TEXT NOT NULL REFERENCES school_roster(reg_number),
            desired_start        TEXT NOT NULL,
            desired_duration_min INTEGER NOT NULL,
            note                 TEXT,
            card_image           TEXT,
            reco_file            TEXT,
            status               TEXT NOT NULL DEFAULT 'pending',
            admin_note           TEXT,
            decided_by           TEXT,
            grant_id             INTEGER,
            created              TEXT NOT NULL,
            decided_at           TEXT
        );
    """)
    conn.commit()

    # ── safe, additive backfill: any existing students → school_roster ──────────
    conn.execute("""
        INSERT OR IGNORE INTO school_roster (reg_number, name, program)
        SELECT reg_number, name, COALESCE(program,'') FROM students
    """)

    # ── one-time cleanup: remove passwordless student_accounts (broken seeds) ───
    # Only removes rows where password_hash is NULL or empty — never real accounts.
    conn.execute("""
        DELETE FROM student_accounts WHERE password_hash IS NULL OR password_hash = ''
    """)

    conn.commit()
    conn.close()


def seed_demo_data():
    """Idempotent: create default admin, roster, demo student account, and a
    sample pending request so the full workflow is demoable immediately."""
    conn = _connect()

    # ── admin ──────────────────────────────────────────────────────────────────
    if not conn.execute(
        "SELECT id FROM admins WHERE username=?", (config.DEFAULT_ADMIN_USERNAME,)
    ).fetchone():
        conn.execute(
            "INSERT INTO admins (username, password_hash) VALUES (?,?)",
            (config.DEFAULT_ADMIN_USERNAME,
             generate_password_hash(config.DEFAULT_ADMIN_PASSWORD)),
        )

    # ── school roster (sample students, signup-eligible but no pre-seeded accounts)
    roster = [
        ("STU/2024/001", "Alice Uwimana",      "Computer Science",       None, None),
        ("STU/2024/002", "Bob Nkurunziza",     "Information Technology", None, None),
        ("STU/2024/003", "Clara Ingabire",     "Software Engineering",   None, None),
        ("STU/2024/004", "David Habimana",     "Computer Science",       None, None),
        ("STU/2024/005", "Eve Mukamana",       "Information Technology", None, None),
        ("STU/2024/006", "Frank Ndayishimiye", "Computer Science",       None, None),
        ("STU/2024/007", "Grace Uwineza",      "Software Engineering",   None, None),
        ("STU/2024/008", "Henry Tuyishime",    "Information Technology", None, None),
        ("STU/2024/009", "Irene Nyiraneza",    "Computer Science",       None, None),
        ("STU/2024/010", "James Bigirimana",   "Software Engineering",   None, None),
        # Demo account entry — has a pre-set password documented in SETUP.md
        ("DEMO/2024/001", "Demo Student",      "Demo Account",           None, None),
    ]
    for reg, name, prog, phone, email in roster:
        conn.execute(
            "INSERT OR IGNORE INTO school_roster (reg_number, name, program, phone, email) VALUES (?,?,?,?,?)",
            (reg, name, prog, phone, email),
        )

    # ── students table (face-enrollment records for the first 5 sample students)
    for reg, name, prog, _, _ in roster[:5]:
        if not conn.execute(
            "SELECT id FROM students WHERE reg_number=?", (reg,)
        ).fetchone():
            conn.execute(
                "INSERT INTO students (reg_number, name, program, created) VALUES (?,?,?,?)",
                (reg, name, prog, datetime.now().isoformat(timespec="seconds")),
            )

    # ── demo student account (one pre-set account for live demo of the portal) ─
    # reg=DEMO/2024/001, password=demo1234 (documented in SETUP.md)
    # All other sample roster entries have NO pre-seeded account — use them to
    # demo the live signup flow.
    if not conn.execute(
        "SELECT id FROM student_accounts WHERE reg_number=?", (config.DEMO_STUDENT_REG,)
    ).fetchone():
        conn.execute(
            "INSERT INTO student_accounts (reg_number, password_hash, verified, created) VALUES (?,?,0,?)",
            (config.DEMO_STUDENT_REG,
             generate_password_hash(config.DEMO_STUDENT_PASSWORD),
             datetime.now().isoformat(timespec="seconds")),
        )

    conn.commit()

    # ── placeholder card image ─────────────────────────────────────────────────
    card_fname = "demo_card_DEMO2024001.jpg"
    card_path  = os.path.join(config.UPLOADS_CARDS_DIR, card_fname)
    os.makedirs(config.UPLOADS_CARDS_DIR, exist_ok=True)
    if not os.path.exists(card_path):
        _generate_placeholder_card(card_path, "Demo Student", "DEMO/2024/001")

    # ── demo pending access request ────────────────────────────────────────────
    if not conn.execute(
        "SELECT id FROM access_requests WHERE student_reg=? AND status='pending'",
        (config.DEMO_STUDENT_REG,),
    ).fetchone():
        tomorrow = (datetime.now() + timedelta(days=1)).replace(
            hour=9, minute=0, second=0, microsecond=0
        )
        conn.execute(
            """INSERT INTO access_requests
               (student_reg, desired_start, desired_duration_min, note,
                card_image, status, created)
               VALUES (?,?,?,?,?,?,?)""",
            (config.DEMO_STUDENT_REG,
             tomorrow.isoformat(timespec="seconds"),
             120,
             "Need lab access for database systems assignment (Chapter 5 project).",
             card_fname,
             "pending",
             datetime.now().isoformat(timespec="seconds")),
        )

    conn.commit()
    conn.close()


def _generate_placeholder_card(path, name, reg_number):
    """Generate a synthetic student ID card image for demo purposes."""
    try:
        import cv2
        import numpy as np
        img = np.zeros((170, 280, 3), dtype=np.uint8)
        img[:] = (35, 65, 145)                               # university blue
        cv2.rectangle(img, (0, 0), (279, 169), (255, 255, 255), 2)
        cv2.rectangle(img, (0, 0), (279, 38), (20, 40, 100), -1)
        cv2.putText(img, "UNIVERSITY OF RWANDA",
                    (12, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)
        cv2.putText(img, "STUDENT IDENTITY CARD",
                    (12, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (220, 220, 255), 1)
        cv2.putText(img, name,
                    (12, 95), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)
        cv2.putText(img, reg_number,
                    (12, 125), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 220, 255), 1)
        cv2.putText(img, "[DEMO PLACEHOLDER]",
                    (12, 158), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (100, 130, 200), 1)
        cv2.imwrite(path, img)
    except Exception:
        pass   # silently skip if cv2 unavailable at seed time


# ── admins ────────────────────────────────────────────────────────────────────

def get_admin_by_username(username):
    conn = _connect()
    row = conn.execute("SELECT * FROM admins WHERE username=?", (username,)).fetchone()
    conn.close()
    return dict(row) if row else None


# ── school roster ─────────────────────────────────────────────────────────────

def get_roster_by_reg(reg_number):
    conn = _connect()
    row = conn.execute(
        "SELECT * FROM school_roster WHERE reg_number=?", (reg_number,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_roster():
    conn = _connect()
    rows = conn.execute(
        "SELECT * FROM school_roster ORDER BY name"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def upsert_roster_entry(reg_number, name, program):
    """Insert if missing, update name/program if already present."""
    conn = _connect()
    conn.execute(
        "INSERT OR IGNORE INTO school_roster (reg_number, name, program) VALUES (?,?,?)",
        (reg_number, name, program or ""),
    )
    conn.execute(
        "UPDATE school_roster SET name=?, program=? WHERE reg_number=?",
        (name, program or "", reg_number),
    )
    conn.commit()
    conn.close()


def delete_roster_entry(reg_number):
    """Remove a roster entry. Safe: leaves student_accounts/students rows intact."""
    conn = _connect()
    conn.execute("DELETE FROM school_roster WHERE reg_number=?", (reg_number,))
    conn.commit()
    conn.close()


def get_roster_with_status():
    """Roster rows enriched with has_account and has_face booleans."""
    conn = _connect()
    rows = conn.execute("""
        SELECT sr.*,
               CASE WHEN sa.id IS NOT NULL THEN 1 ELSE 0 END AS has_account,
               CASE WHEN s.id  IS NOT NULL THEN 1 ELSE 0 END AS has_face
        FROM school_roster sr
        LEFT JOIN student_accounts sa ON sa.reg_number = sr.reg_number
        LEFT JOIN students          s  ON s.reg_number  = sr.reg_number
        ORDER BY sr.name
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── student accounts ──────────────────────────────────────────────────────────

def get_student_account_by_reg(reg_number):
    conn = _connect()
    row = conn.execute(
        "SELECT * FROM student_accounts WHERE reg_number=?", (reg_number,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def create_student_account(reg_number, password):
    conn = _connect()
    conn.execute(
        "INSERT INTO student_accounts (reg_number, password_hash, verified, created) VALUES (?,?,0,?)",
        (reg_number, generate_password_hash(password),
         datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()
    conn.close()


# ── students ──────────────────────────────────────────────────────────────────

def add_student(reg_number, name, program, photo=None, embedding=None):
    conn = _connect()
    emb_bytes = embedding.astype(np.float32).tobytes() if embedding is not None else None
    conn.execute(
        "INSERT INTO students (reg_number, name, program, photo, embedding, created) VALUES (?,?,?,?,?,?)",
        (reg_number, name, program, photo, emb_bytes,
         datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()
    conn.close()


def update_student_info(student_id, name, program, reg_number):
    conn = _connect()
    conn.execute(
        "UPDATE students SET name=?, program=?, reg_number=? WHERE id=?",
        (name, program, reg_number, student_id),
    )
    conn.commit()
    conn.close()


def update_student_face(student_id, photo, embedding):
    conn = _connect()
    conn.execute(
        "UPDATE students SET photo=?, embedding=? WHERE id=?",
        (photo, embedding.astype(np.float32).tobytes(), student_id),
    )
    conn.commit()
    conn.close()


def get_all_students():
    conn = _connect()
    rows = conn.execute(
        "SELECT id, reg_number, name, program, photo, created FROM students ORDER BY name"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_student_by_id(student_id):
    conn = _connect()
    row = conn.execute("SELECT * FROM students WHERE id=?", (student_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_student_by_reg(reg_number):
    conn = _connect()
    row = conn.execute(
        "SELECT * FROM students WHERE reg_number=?", (reg_number,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def delete_student(student_id):
    conn = _connect()
    conn.execute("DELETE FROM students WHERE id=?", (student_id,))
    conn.commit()
    conn.close()


# ── staff ─────────────────────────────────────────────────────────────────────

def add_staff(name, role, photo=None, embedding=None):
    conn = _connect()
    emb_bytes = embedding.astype(np.float32).tobytes() if embedding is not None else None
    conn.execute(
        "INSERT INTO staff (name, role, photo, embedding, created) VALUES (?,?,?,?,?)",
        (name, role, photo, emb_bytes, datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()
    conn.close()


def update_staff_face(staff_id, photo, embedding):
    conn = _connect()
    conn.execute(
        "UPDATE staff SET photo=?, embedding=? WHERE id=?",
        (photo, embedding.astype(np.float32).tobytes(), staff_id),
    )
    conn.commit()
    conn.close()


def get_all_staff():
    conn = _connect()
    rows = conn.execute(
        "SELECT id, name, role, photo, created FROM staff ORDER BY name"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_staff_by_id(staff_id):
    conn = _connect()
    row = conn.execute("SELECT * FROM staff WHERE id=?", (staff_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def delete_staff(staff_id):
    conn = _connect()
    conn.execute("DELETE FROM staff WHERE id=?", (staff_id,))
    conn.commit()
    conn.close()


# ── recognition face pool ─────────────────────────────────────────────────────

def get_all_known_faces():
    conn = _connect()
    results = []
    for row in conn.execute(
        "SELECT id, name, embedding FROM students WHERE embedding IS NOT NULL"
    ):
        emb = np.frombuffer(row["embedding"], dtype=np.float32)
        results.append((row["id"], row["name"], "student", emb))
    for row in conn.execute(
        "SELECT id, name, embedding FROM staff WHERE embedding IS NOT NULL"
    ):
        emb = np.frombuffer(row["embedding"], dtype=np.float32)
        results.append((row["id"], row["name"], "staff", emb))
    conn.close()
    return results


# ── access grants ─────────────────────────────────────────────────────────────

def create_grant(student_id, granted_by, reason, class_label, start_time, end_time):
    conn = _connect()
    cur = conn.execute(
        """INSERT INTO access_grants
           (student_id, granted_by, reason, class_label, start_time, end_time, active)
           VALUES (?,?,?,?,?,?,1)""",
        (student_id, granted_by, reason, class_label,
         start_time.isoformat(timespec="seconds"),
         end_time.isoformat(timespec="seconds")),
    )
    gid = cur.lastrowid
    conn.commit()
    conn.close()
    return gid


def get_active_grant(student_id, now=None):
    if now is None:
        now = datetime.now()
    now_str = now.isoformat(timespec="seconds")
    conn = _connect()
    row = conn.execute(
        """SELECT * FROM access_grants
           WHERE student_id=? AND active=1
             AND start_time<=? AND end_time>=?
           ORDER BY end_time ASC LIMIT 1""",
        (student_id, now_str, now_str),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_upcoming_grant(student_id, now=None):
    """First grant not yet started (future start_time)."""
    if now is None:
        now = datetime.now()
    now_str = now.isoformat(timespec="seconds")
    conn = _connect()
    row = conn.execute(
        """SELECT * FROM access_grants
           WHERE student_id=? AND active=1 AND start_time>?
           ORDER BY start_time ASC LIMIT 1""",
        (student_id, now_str),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_grants(include_expired=False):
    conn = _connect()
    where = "" if include_expired else "WHERE ag.active=1"
    rows = conn.execute(f"""
        SELECT ag.*, s.name AS student_name, s.reg_number
        FROM access_grants ag
        JOIN students s ON s.id=ag.student_id
        {where}
        ORDER BY ag.end_time ASC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_grants_by_student_id(student_id, limit=20):
    conn = _connect()
    rows = conn.execute(
        """SELECT * FROM access_grants WHERE student_id=?
           ORDER BY start_time DESC LIMIT ?""",
        (student_id, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def revoke_grant(grant_id):
    conn = _connect()
    conn.execute(
        "UPDATE access_grants SET active=0, end_time=? WHERE id=?",
        (datetime.now().isoformat(timespec="seconds"), grant_id),
    )
    conn.commit()
    conn.close()


# ── access requests ───────────────────────────────────────────────────────────

def create_access_request(student_reg, desired_start, desired_duration_min,
                          note, card_image, reco_file=None):
    conn = _connect()
    cur = conn.execute(
        """INSERT INTO access_requests
           (student_reg, desired_start, desired_duration_min, note,
            card_image, reco_file, status, created)
           VALUES (?,?,?,?,?,?,'pending',?)""",
        (student_reg, desired_start, desired_duration_min, note,
         card_image, reco_file,
         datetime.now().isoformat(timespec="seconds")),
    )
    rid = cur.lastrowid
    conn.commit()
    conn.close()
    return rid


def get_all_access_requests(status=None):
    conn = _connect()
    where = "WHERE ar.status=?" if status else ""
    params = (status,) if status else ()
    rows = conn.execute(
        f"""SELECT ar.*, sr.name AS student_name, sr.program AS student_program
            FROM access_requests ar
            JOIN school_roster sr ON sr.reg_number=ar.student_reg
            {where}
            ORDER BY ar.created DESC""",
        params,
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_pending_requests_count():
    conn = _connect()
    n = conn.execute(
        "SELECT COUNT(*) FROM access_requests WHERE status='pending'"
    ).fetchone()[0]
    conn.close()
    return n


def get_access_request_by_id(request_id):
    conn = _connect()
    row = conn.execute(
        """SELECT ar.*, sr.name AS student_name, sr.program AS student_program
           FROM access_requests ar
           JOIN school_roster sr ON sr.reg_number=ar.student_reg
           WHERE ar.id=?""",
        (request_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_pending_request_for_student(reg_number):
    conn = _connect()
    row = conn.execute(
        "SELECT * FROM access_requests WHERE student_reg=? AND status='pending' LIMIT 1",
        (reg_number,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_most_recent_request(reg_number):
    conn = _connect()
    row = conn.execute(
        "SELECT * FROM access_requests WHERE student_reg=? ORDER BY created DESC LIMIT 1",
        (reg_number,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_requests_by_student(reg_number, limit=20):
    conn = _connect()
    rows = conn.execute(
        "SELECT * FROM access_requests WHERE student_reg=? ORDER BY created DESC LIMIT ?",
        (reg_number, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def approve_request(request_id, decided_by, start_dt, duration_min):
    """Approve a request: ensure student record exists, create grant, update request."""
    req = get_access_request_by_id(request_id)
    if not req:
        return None

    # Ensure the student has a record in the face-enrollment table.
    # They may have a portal account but admin may not have enrolled them yet.
    student = get_student_by_reg(req["student_reg"])
    if not student:
        roster = get_roster_by_reg(req["student_reg"])
        add_student(req["student_reg"],
                    roster["name"] if roster else req["student_reg"],
                    roster["program"] if roster else "")
        student = get_student_by_reg(req["student_reg"])

    end_dt   = start_dt + timedelta(minutes=duration_min)
    grant_id = create_grant(
        student["id"], decided_by, "individual", None, start_dt, end_dt
    )

    conn = _connect()
    conn.execute(
        """UPDATE access_requests SET status='approved', decided_by=?,
           grant_id=?, decided_at=? WHERE id=?""",
        (decided_by, grant_id,
         datetime.now().isoformat(timespec="seconds"), request_id),
    )
    conn.commit()
    conn.close()
    return grant_id


def deny_request(request_id, decided_by, admin_note=""):
    conn = _connect()
    conn.execute(
        """UPDATE access_requests SET status='denied', decided_by=?,
           admin_note=?, decided_at=? WHERE id=?""",
        (decided_by, admin_note,
         datetime.now().isoformat(timespec="seconds"), request_id),
    )
    conn.commit()
    conn.close()


# ── logs ──────────────────────────────────────────────────────────────────────

def add_log(person_name, person_type, status, action,
            reg_number=None, snapshot=None):
    conn = _connect()
    conn.execute(
        """INSERT INTO logs
           (timestamp, person_name, person_type, reg_number, status, action, snapshot)
           VALUES (?,?,?,?,?,?,?)""",
        (datetime.now().isoformat(sep=" ", timespec="seconds"),
         person_name, person_type, reg_number, status, action, snapshot),
    )
    conn.commit()
    conn.close()


def get_logs(limit=100, date_from=None, date_to=None,
             person_type=None, status=None, search=None):
    conn = _connect()
    clauses, params = [], []
    if date_from:
        clauses.append("timestamp >= ?")
        params.append(date_from + " 00:00:00")
    if date_to:
        clauses.append("timestamp <= ?")
        params.append(date_to + " 23:59:59")
    if person_type:
        clauses.append("person_type = ?")
        params.append(person_type)
    if status:
        clauses.append("status = ?")
        params.append(status)
    if search:
        clauses.append("(person_name LIKE ? OR reg_number LIKE ?)")
        params += [f"%{search}%", f"%{search}%"]
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    rows = conn.execute(
        f"SELECT * FROM logs {where} ORDER BY id DESC LIMIT ?",
        params + [limit],
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_logs_by_reg(reg_number, limit=50):
    conn = _connect()
    rows = conn.execute(
        "SELECT * FROM logs WHERE reg_number=? ORDER BY id DESC LIMIT ?",
        (reg_number, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_log_summary(date_from=None, date_to=None, search=None):
    conn = _connect()
    clauses, params = [], []
    if date_from:
        clauses.append("timestamp >= ?")
        params.append(date_from + " 00:00:00")
    if date_to:
        clauses.append("timestamp <= ?")
        params.append(date_to + " 23:59:59")
    if search:
        clauses.append("(person_name LIKE ? OR reg_number LIKE ?)")
        params += [f"%{search}%", f"%{search}%"]
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    row = conn.execute(
        f"""SELECT
              COUNT(*) as total,
              SUM(CASE WHEN status='Granted' THEN 1 ELSE 0 END) as granted,
              SUM(CASE WHEN status='Denied'  THEN 1 ELSE 0 END) as denied,
              COUNT(DISTINCT CASE WHEN person_type='student' THEN reg_number END) as unique_students
            FROM logs {where}""",
        params,
    ).fetchone()
    conn.close()
    return dict(row) if row else {"total": 0, "granted": 0, "denied": 0, "unique_students": 0}


# ── dashboard stats ───────────────────────────────────────────────────────────

def get_dashboard_stats():
    conn = _connect()
    today = datetime.now().strftime("%Y-%m-%d")
    now   = datetime.now().isoformat(timespec="seconds")
    stats = {
        "students_total":  conn.execute("SELECT COUNT(*) FROM students").fetchone()[0],
        "staff_total":     conn.execute("SELECT COUNT(*) FROM staff").fetchone()[0],
        "grants_active":   conn.execute(
            "SELECT COUNT(*) FROM access_grants WHERE active=1 AND start_time<=? AND end_time>=?",
            (now, now)
        ).fetchone()[0],
        "today_entries":   conn.execute(
            "SELECT COUNT(*) FROM logs WHERE timestamp>=? AND status='Granted'",
            (today + " 00:00:00",)
        ).fetchone()[0],
    }
    conn.close()
    return stats
