# Lab Access Control — Technical Specification

## Database Schema

### `admins`
| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | |
| username | TEXT UNIQUE | |
| password_hash | TEXT | werkzeug `generate_password_hash` |

### `students`
| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | |
| reg_number | TEXT UNIQUE | e.g. `STU/2024/001` |
| name | TEXT | |
| program | TEXT | e.g. Computer Science |
| photo | TEXT | filename in `student_photos/` |
| embedding | BLOB | numpy float32 bytes, nullable |
| created | TEXT | ISO 8601 |

### `staff`
| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | |
| name | TEXT | |
| role | TEXT | e.g. Lab Administrator |
| photo | TEXT | filename in `staff_photos/` |
| embedding | BLOB | numpy float32 bytes |
| created | TEXT | ISO 8601 |

### `access_grants`
| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | |
| student_id | INTEGER FK | → students.id |
| granted_by | TEXT | admin username |
| reason | TEXT | `individual` or `class` |
| class_label | TEXT | nullable, e.g. `CS301 Lecture` |
| start_time | TEXT | ISO 8601 |
| end_time | TEXT | ISO 8601 |
| active | INTEGER | 1 = active, 0 = revoked |

A student has access at time T if a grant exists with `active=1 AND start_time ≤ T ≤ end_time`.

### `logs`
| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | |
| timestamp | TEXT | `YYYY-MM-DD HH:MM:SS` |
| person_name | TEXT | |
| person_type | TEXT | `staff` / `student` / `unknown` / `admin` |
| reg_number | TEXT | nullable |
| status | TEXT | `Granted` / `Denied` / `Manual` |
| action | TEXT | human-readable description |
| snapshot | TEXT | filename in `snapshots/`, nullable |

---

## HTTP Endpoints

### Root + Auth
| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Landing chooser — redirects to dashboard/student-portal if already logged in |
| GET/POST | `/login` | Admin login (alias: `/admin/login`) |
| GET | `/logout` | Clear admin session |

### Admin Portal (all require admin session)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/dashboard` | Live camera, door status, activity feed |
| GET | `/video` | MJPEG stream |
| POST | `/open` | Manually open door |
| POST | `/lock` | Manually lock door |
| GET | `/status` | Door + last-event JSON |
| GET | `/students` | Student list (searchable) |
| GET/POST | `/students/register` | Add student / capture face (auto-adds to roster) |
| GET/POST | `/students/<id>/edit` | Edit student info or re-capture face |
| POST | `/students/<id>/delete` | Remove student |
| GET | `/roster` | School roster management |
| POST | `/roster/add` | Add a reg number to the roster |
| POST | `/roster/<reg>/delete` | Remove a roster entry |
| GET | `/staff` | Staff list |
| GET/POST | `/staff/register` | Add staff / capture face |
| POST | `/staff/<id>/delete` | Remove staff |
| GET | `/grants` | Active + upcoming grants with countdowns |
| POST | `/grants/individual` | Create individual grant |
| POST | `/grants/class` | Create class grant (bulk) |
| POST | `/grants/<id>/revoke` | Revoke a grant immediately |
| POST | `/grants/<id>/checkout` | Admin-side early checkout |
| GET | `/requests` | Pending student access requests queue |
| POST | `/requests/<id>/approve` | Approve request, create grant |
| POST | `/requests/<id>/deny` | Deny request with optional note |
| GET | `/logs` | Filtered log table |
| GET | `/logs/export.csv` | CSV download (utf-8-sig BOM, Excel-safe) |
| GET | `/photos/student/<filename>` | Serve student photo |
| GET | `/photos/staff/<filename>` | Serve staff photo |
| GET | `/snapshots/<filename>` | Serve unknown-person snapshot |
| GET | `/uploads/cards/<filename>` | Serve student card upload (admin only) |
| GET | `/uploads/reco/<filename>` | Serve recommendation file (admin only) |

### Student Portal
| Method | Path | Description |
|--------|------|-------------|
| GET/POST | `/student/signup` | Create account (validates against roster) |
| GET/POST | `/student/login` | Student login |
| GET | `/student/logout` | Clear student session |
| GET | `/student` | Student dashboard (status card) |
| GET/POST | `/student/request` | Submit access request with card image |
| POST | `/student/checkout` | Student-side early checkout |
| GET | `/student/history` | Requests, grants, and door events |

### Security model
- Admin session key: `session['logged_in']` + `session['username']`
- Student session key: `session['student_reg']` + `session['student_name']`
- A student can never reach an admin route, and vice versa
- Student signup requires reg_number to exist in `school_roster`; identity verified at request time via card image reviewed by admin

---

## SocketIO Events (server → client)

### `access_event`
Emitted on every door decision and manual action.

```json
{
  "person":      "Alice Uwimana",
  "type":        "student",
  "reg_number":  "STU/2024/001",
  "status":      "Granted",
  "action":      "Door opened — CS301 Lecture",
  "time":        "14:35:02",
  "door_opened": true
}
```

### `door_status`
Emitted whenever the door state changes.

```json
{ "is_open": true }
```

---

## Platform Abstraction

| Interface | Real (Pi) | Mock (Windows) | Detection |
|-----------|-----------|----------------|-----------|
| `CameraBase` | `RealCamera` (Picamera2) | `MockCamera` (OpenCV webcam) | `import picamera2` / `FORCE_MOCK_CAMERA=1` |
| `DoorHardwareBase` | `RealDoorHardware` (gpiozero) | `MockDoorHardware` (prints) | `platform.system() == 'Linux'` + `import gpiozero` / `FORCE_MOCK_HARDWARE=1` |

---

## Access Decision Logic

```
face detected → match against all known faces (students + staff with embeddings)

  MATCH found:
    type == staff    → open door → log Granted/staff
    type == student  → check access_grants for active grant covering now
                         grant found  → open door → log Granted/student (with class_label)
                         no grant     → short buzz  → log Denied/student
  NO MATCH (unknown):
    → 3s alarm
    → snapshot saved
    → SMS + email + Telegram notifications sent
    → log Denied/unknown
```

Cooldown: `COOLDOWN_SECONDS` (default 15) prevents repeated triggers for the same person.

---

## Configuration (`config.py`)

Key env-var overrides: `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `SECRET_KEY`, `EMAIL_FROM`, `EMAIL_PASSWORD`, `EMAIL_TO`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `INFOBIP_BASE_URL`, `INFOBIP_API_KEY`, `SMS_TO`, `FORCE_MOCK_CAMERA`, `FORCE_MOCK_HARDWARE`.
