"""SQLite is the source of truth; the model cannot invent capacity or verification."""
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4
from .config import settings

CUSTOMERS = [
    ("c1", "Ayşe Kaya", "0532 000 00 01", "1988-03-14", "Kadıköy", "Ev"),
    ("c2", "Mehmet Demir", "0532 000 00 02", "1975-11-02", "Kadıköy", "İş yeri"),
    ("c3", "Zeynep Arslan", "0532 000 00 03", "1993-06-27", "Kadıköy", "Ev"),
    ("c4", "Can Yıldız", "0532 000 00 04", "1981-01-09", "Ataşehir", "Ev"),
    ("c5", "Elif Şahin", "0532 000 00 05", "1990-08-30", "Ataşehir", "İş yeri"),
    ("c6", "Burak Çelik", "0532 000 00 06", "1969-12-18", "Şişli", "Ev"),
    ("c7", "Selin Aydın", "0532 000 00 07", "1999-04-05", "Şişli", "Ev"),
    ("c8", "Ali Öztürk", "0532 000 00 08", "1984-07-21", "Beşiktaş", "İş yeri"),
]

class RuleError(Exception):
    pass

@contextmanager
def connection():
    db = sqlite3.connect(settings.database_path, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

def initialize():
    monday = date.fromisoformat(settings.demo_week_start)
    if monday.weekday() != 0:
        raise ValueError("DEMO_WEEK_START must be a Monday")
    with connection() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS customers (
          id TEXT PRIMARY KEY, name TEXT, phone TEXT, birth_date TEXT,
          district TEXT, address_type TEXT);
        CREATE TABLE IF NOT EXISTS slots (
          id TEXT PRIMARY KEY, district TEXT, delivery_date TEXT, start TEXT, end TEXT,
          capacity INTEGER CHECK(capacity > 0));
        CREATE TABLE IF NOT EXISTS calls (
          id TEXT PRIMARY KEY, customer_id TEXT REFERENCES customers(id),
          verified INTEGER DEFAULT 0, attempts INTEGER DEFAULT 0,
          status TEXT DEFAULT 'started', created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS bookings (
          id TEXT PRIMARY KEY, customer_id TEXT UNIQUE REFERENCES customers(id),
          slot_id TEXT REFERENCES slots(id), call_id TEXT REFERENCES calls(id),
          created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS callback_requests (
          id TEXT PRIMARY KEY,
          customer_id TEXT NOT NULL REFERENCES customers(id),
          call_id TEXT NOT NULL UNIQUE REFERENCES calls(id),
          requested_at TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'pending'
            CHECK(status IN ('pending', 'completed', 'cancelled')),
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE UNIQUE INDEX IF NOT EXISTS one_pending_callback_per_customer
          ON callback_requests(customer_id) WHERE status='pending';
        """)
        # Serialize additive migration checks across API and spawned worker processes.
        db.execute("BEGIN IMMEDIATE")
        # Additive migration for databases created before recipient confirmation.
        columns = {r["name"] for r in db.execute("PRAGMA table_info(calls)")}
        if "recipient_status" not in columns:
            db.execute("ALTER TABLE calls ADD COLUMN recipient_status TEXT NOT NULL DEFAULT 'unknown'")
        customer_columns = {r["name"] for r in db.execute("PRAGMA table_info(customers)")}
        if "verification_failures" not in customer_columns:
            db.execute("ALTER TABLE customers ADD COLUMN verification_failures INTEGER NOT NULL DEFAULT 0")
            db.execute("""UPDATE customers SET verification_failures=MIN(2,COALESCE((
                SELECT SUM(MAX(0,attempts-verified)) FROM calls WHERE customer_id=customers.id
            ),0))""")
        if "do_not_call" not in customer_columns:
            db.execute("ALTER TABLE customers ADD COLUMN do_not_call INTEGER NOT NULL DEFAULT 0")
            db.execute("ALTER TABLE customers ADD COLUMN do_not_call_at TEXT")
        if "contact_review_status" not in customer_columns:
            db.execute("ALTER TABLE customers ADD COLUMN contact_review_status TEXT NOT NULL DEFAULT 'clear'")
            db.execute("ALTER TABLE customers ADD COLUMN contact_issue_at TEXT")
            db.execute("ALTER TABLE customers ADD COLUMN contact_issue_call_id TEXT REFERENCES calls(id)")
            db.execute("""UPDATE customers SET contact_review_status='pending',
                contact_issue_call_id=(SELECT id FROM calls WHERE customer_id=customers.id
                    AND status='incorrect_details' ORDER BY created_at DESC,rowid DESC LIMIT 1),
                contact_issue_at=(SELECT created_at FROM calls WHERE customer_id=customers.id
                    AND status='incorrect_details' ORDER BY created_at DESC,rowid DESC LIMIT 1)
                WHERE EXISTS(SELECT 1 FROM calls WHERE customer_id=customers.id AND status='incorrect_details')""")
            db.execute("""UPDATE callback_requests SET status='cancelled' WHERE status='pending'
                AND customer_id IN (SELECT id FROM customers WHERE contact_review_status='pending')""")
        db.executemany("INSERT OR IGNORE INTO customers(id,name,phone,birth_date,district,address_type) VALUES (?,?,?,?,?,?)", CUSTOMERS)
        for sid, district, offset, start, end, capacity in [
            ("s1", "Kadıköy", 3, "09:00", "13:00", 1),
            ("s2", "Kadıköy", 4, "14:00", "18:00", 1),
            ("s3", "Ataşehir", 3, "14:00", "18:00", 2),
            ("s4", "Şişli", 4, "09:00", "13:00", 2),
            ("s5", "Beşiktaş", 3, "09:00", "13:00", 1),
        ]:
            db.execute("INSERT OR IGNORE INTO slots VALUES (?,?,?,?,?,?)", (
                sid, district, str(monday + timedelta(days=offset)), start, end, capacity))

def dashboard():
    with connection() as db:
        customers = [dict(r) for r in db.execute("""
            SELECT c.id,c.name,c.phone,c.district,c.address_type,c.do_not_call,c.verification_failures,
                c.contact_review_status,c.contact_issue_at,b.slot_id
            FROM customers c LEFT JOIN bookings b ON b.customer_id=c.id ORDER BY c.id
        """)]
        slots = [dict(r) for r in db.execute("""
            SELECT s.*, s.capacity-count(b.id) AS remaining FROM slots s
            LEFT JOIN bookings b ON b.slot_id=s.id GROUP BY s.id ORDER BY s.id
        """)]
        calls = [dict(r) for r in db.execute("""
            SELECT id,customer_id,verified,status,created_at,recipient_status FROM calls
            ORDER BY created_at DESC, rowid DESC LIMIT 20
        """)]
        callbacks = [dict(r) for r in db.execute("""
            SELECT r.*,c.name,c.phone FROM callback_requests r
            JOIN customers c ON c.id=r.customer_id
            ORDER BY r.requested_at,r.id
        """)]
    return {"customers": customers, "slots": slots, "calls": calls,
            "callbacks": callbacks,
            "demo_week_start": settings.demo_week_start}

def create_call(customer_id):
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        customer = db.execute("SELECT * FROM customers WHERE id=?", (customer_id,)).fetchone()
        if not customer:
            raise RuleError("Müşteri bulunamadı.")
        _contact_allowed(customer)
        call_id = str(uuid4())
        db.execute("INSERT INTO calls(id,customer_id) VALUES (?,?)", (call_id, customer_id))
    return call_id

def call_customer(call_id):
    with connection() as db:
        row = db.execute("""SELECT c.id,c.name FROM customers c JOIN calls k
            ON c.id=k.customer_id WHERE k.id=?""", (call_id,)).fetchone()
        if not row:
            raise RuleError("Görüşme bulunamadı.")
        return dict(row)

def verify(call_id, birth_date):
    # ISO format is validated, expected date is never returned to the model.
    try:
        birth_date = date.fromisoformat(birth_date).isoformat()
    except (ValueError, TypeError):
        raise RuleError("Tarihi YYYY-MM-DD biçiminde iletin.") from None
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("""SELECT k.*,c.birth_date,c.verification_failures,c.do_not_call,c.contact_review_status FROM calls k JOIN customers c
            ON c.id=k.customer_id WHERE k.id=?""", (call_id,)).fetchone()
        if not row or row["status"] != "started":
            raise RuleError("Doğrulama yapılamıyor; görüşmeyi sonlandırın.")
        _contact_allowed(row)
        if row["recipient_status"] != "self":
            raise RuleError("Önce aranan müşteriyle görüşüldüğünü teyit edin.")
        if row["verified"]:
            return {"verified": True, "booking": _existing_booking(db, row["customer_id"])}
        ok = birth_date == row["birth_date"]
        db.execute("UPDATE calls SET verified=?, attempts=attempts+1 WHERE id=?", (ok, call_id))
        failures = row["verification_failures"] + (not ok)
        if not ok:
            db.execute("UPDATE customers SET verification_failures=? WHERE id=?", (failures, row["customer_id"]))
        if failures >= 2:
            db.execute("UPDATE calls SET status='verification_failed' WHERE customer_id=? AND status='started'",
                       (row["customer_id"],))
        result = {"verified": ok, "remaining_attempts": 2-failures}
        if ok:
            result["booking"] = _existing_booking(db, row["customer_id"])
        return result


def confirm_recipient(call_id, recipient_status):
    """Self declaration permits verification, never access to delivery information."""
    if recipient_status not in ("self", "other_person", "incorrect_details"):
        raise RuleError("Geçersiz muhatap sonucu.")
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        call = db.execute("SELECT * FROM calls WHERE id=?", (call_id,)).fetchone()
        if not call or call["status"] != "started":
            raise RuleError("Görüşme aktif değil.")
        status = "started" if recipient_status == "self" else recipient_status
        db.execute("UPDATE calls SET recipient_status=?,status=?,verified=CASE WHEN ?='self' THEN verified ELSE 0 END WHERE id=?",
                   (recipient_status, status, recipient_status, call_id))
        if recipient_status == "incorrect_details":
            db.execute("""UPDATE customers SET contact_review_status='pending',
                contact_issue_at=CURRENT_TIMESTAMP,contact_issue_call_id=? WHERE id=?""",
                (call_id, call["customer_id"]))
            db.execute("UPDATE callback_requests SET status='cancelled' WHERE customer_id=? AND status='pending'",
                       (call["customer_id"],))
        return {"recipient_status": recipient_status, "status": status}


def _existing_booking(db, customer_id):
    row = db.execute("""SELECT b.id AS booking_id,s.id AS slot_id,s.delivery_date,
        s.start,s.end,s.district,c.address_type FROM bookings b
        JOIN slots s ON s.id=b.slot_id JOIN customers c ON c.id=b.customer_id
        WHERE b.customer_id=?""", (customer_id,)).fetchone()
    return dict(row) if row else None


def existing_booking(call_id):
    with connection() as db:
        call = authorized(db, call_id)
        return {"booking": _existing_booking(db, call["customer_id"])}

def authorized(db, call_id):
    row = db.execute("""SELECT k.*,c.do_not_call,c.verification_failures,c.contact_review_status FROM calls k
        JOIN customers c ON c.id=k.customer_id WHERE k.id=?""", (call_id,)).fetchone()
    if not row or row["recipient_status"] != "self" or not row["verified"] or row["status"] not in ("started", "booked"):
        raise RuleError("Önce kimlik doğrulaması gerekli.")
    _contact_allowed(row)
    return row

def available_slots(call_id):
    with connection() as db:
        call = authorized(db, call_id)
        return [dict(r) for r in db.execute("""
          SELECT s.id,s.delivery_date,s.start,s.end,s.capacity-count(b.id) AS remaining
          FROM slots s JOIN customers c ON c.district=s.district
          LEFT JOIN bookings b ON b.slot_id=s.id WHERE c.id=? GROUP BY s.id
          HAVING remaining>0 ORDER BY s.delivery_date,s.start
        """, (call["customer_id"],))]

def book(call_id, slot_id, confirmed):
    if not confirmed:
        raise RuleError("Müşterinin açık onayı gerekli.")
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        call = authorized(db, call_id)
        existing = db.execute("SELECT * FROM bookings WHERE customer_id=?", (
            call["customer_id"],)).fetchone()
        if existing:
            if existing["slot_id"] == slot_id:
                return {"booking_id": existing["id"], "slot_id": slot_id, "already_booked": True}
            raise RuleError("Mevcut rezervasyon var; değişiklik için banka desteği gerekli.")
        slot = db.execute("""SELECT s.*,c.district AS customer_district FROM slots s
            JOIN customers c ON c.id=? WHERE s.id=?""", (call["customer_id"], slot_id)).fetchone()
        if not slot or slot["district"] != slot["customer_district"]:
            raise RuleError("Bu ilçede teslimat yapılamaz.")
        used = db.execute("SELECT count(*) FROM bookings WHERE slot_id=?", (slot_id,)).fetchone()[0]
        if used >= slot["capacity"]:
            raise RuleError("Bu saat doldu. Müsaitlikleri tekrar sorgulayın.")
        booking_id = str(uuid4())
        db.execute("INSERT INTO bookings(id,customer_id,slot_id,call_id) VALUES (?,?,?,?)", (
            booking_id, call["customer_id"], slot_id, call_id))
        db.execute("UPDATE calls SET status='booked' WHERE id=?", (call_id,))
        return {"booking_id": booking_id, "slot_id": slot_id,
                "delivery_date": slot["delivery_date"], "start": slot["start"], "end": slot["end"]}

def close_call(call_id, outcome):
    if outcome not in ("declined", "no_availability", "needs_support", "existing_booking_confirmed"):
        raise RuleError("Geçersiz görüşme sonucu.")
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT status FROM calls WHERE id=?", (call_id,)).fetchone()
        if not row:
            raise RuleError("Görüşme bulunamadı.")
        if row["status"] != "started":
            return {"status": row["status"]}
        if outcome == "existing_booking_confirmed":
            call = authorized(db, call_id)
            if not _existing_booking(db, call["customer_id"]):
                raise RuleError("Mevcut rezervasyon bulunamadı.")
        db.execute("UPDATE calls SET status=? WHERE id=?", (outcome, call_id))
    return {"status": outcome}


def request_callback(call_id, requested_at, confirmed):
    """Record an explicitly confirmed callback, without exposing delivery details."""
    if confirmed is not True:
        raise RuleError("Geri aranma zamanı için müşterinin açık onayı gerekli.")
    try:
        instant = datetime.fromisoformat(requested_at)
        if instant.tzinfo is None or instant.utcoffset() is None:
            raise ValueError
        instant = instant.astimezone(timezone.utc)
    except (ValueError, TypeError):
        raise RuleError("Saat dilimi içeren ISO tarih/saat iletin; örnek: 2026-11-18T15:00:00+03:00.") from None
    normalized = instant.isoformat()
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        call = db.execute("SELECT * FROM calls WHERE id=?", (call_id,)).fetchone()
        if not call:
            raise RuleError("Görüşme bulunamadı.")
        customer = db.execute("SELECT * FROM customers WHERE id=?", (call["customer_id"],)).fetchone()
        _contact_allowed(customer)
        existing = db.execute("SELECT * FROM callback_requests WHERE call_id=?", (call_id,)).fetchone()
        if existing:
            if existing["requested_at"] == normalized and existing["status"] == "pending":
                return {"callback_id": existing["id"], "requested_at": normalized,
                        "status": "pending", "already_requested": True}
            raise RuleError("Bu görüşmenin geri aranma talebi zaten kaydedildi.")
        if call["status"] != "started":
            raise RuleError("Kapanmış görüşmede geri aranma talebi oluşturulamaz.")
        if call["recipient_status"] != "self":
            raise RuleError("Geri aranma talebi yalnız aranan müşteriden alınabilir; önce muhatabı teyit edin.")
        if instant <= datetime.now(timezone.utc):
            raise RuleError("Geri aranma zamanı gelecekte olmalı.")
        pending = db.execute("SELECT id FROM callback_requests WHERE customer_id=? AND status='pending'",
                             (call["customer_id"],)).fetchone()
        if pending:
            raise RuleError("Müşterinin bekleyen geri aranma talebi var; operasyon panelinden takip edin.")
        callback_id = str(uuid4())
        db.execute("INSERT INTO callback_requests(id,customer_id,call_id,requested_at) VALUES (?,?,?,?)",
                   (callback_id, call["customer_id"], call_id, normalized))
        db.execute("UPDATE calls SET status='callback_requested' WHERE id=?", (call_id,))
    return {"callback_id": callback_id, "requested_at": normalized, "status": "pending"}


def resolve_callback(callback_id, status):
    if status not in ("completed", "cancelled"):
        raise RuleError("Geri aranma sonucu completed veya cancelled olmalı.")
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT status FROM callback_requests WHERE id=?", (callback_id,)).fetchone()
        if not row:
            raise RuleError("Geri aranma talebi bulunamadı.")
        if row["status"] not in ("pending", status):
            raise RuleError("Kapanmış talebin sonucu değiştirilemez.")
        db.execute("UPDATE callback_requests SET status=? WHERE id=?", (status, callback_id))
    return {"callback_id": callback_id, "status": status}


def _contact_allowed(customer):
    if customer["contact_review_status"] == "pending":
        raise RuleError("Yanlış numara veya hatalı müşteri kaydı bildirildi; kayıt incelenip düzeltilene kadar aramaya kapalı.")
    if customer["do_not_call"]:
        raise RuleError("Müşteri tekrar aranmak istemiyor; yeni görüşme veya geri aranma oluşturulamaz.")
    if customer["verification_failures"] >= 2:
        raise RuleError("Müşterinin iki doğrulama denemesi doldu; banka desteğine başvurulmalı.")


def opt_out_calls(call_id, confirmed):
    """Persist an explicit request from the intended recipient; never cancel a booking."""
    if confirmed is not True:
        raise RuleError("Tekrar aranmama için müşterinin açık talebi gerekli.")
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        call = db.execute("SELECT * FROM calls WHERE id=?", (call_id,)).fetchone()
        if not call or call["recipient_status"] != "self":
            raise RuleError("Aranmama tercihi yalnız aranan müşteriden alınabilir.")
        if call["status"] in ("other_person", "incorrect_details"):
            raise RuleError("Yanlış muhatap adına tercih kaydedilemez.")
        db.execute("UPDATE customers SET do_not_call=1,do_not_call_at=COALESCE(do_not_call_at,CURRENT_TIMESTAMP) WHERE id=?",
                   (call["customer_id"],))
        db.execute("UPDATE callback_requests SET status='cancelled' WHERE customer_id=? AND status='pending'",
                   (call["customer_id"],))
        db.execute("UPDATE calls SET status='do_not_call' WHERE customer_id=? AND status IN ('started','callback_requested')",
                   (call["customer_id"],))
    return {"status": "do_not_call", "do_not_call": True}
