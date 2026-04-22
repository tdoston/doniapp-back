-- Swift Bookings: biznes jadvallari (Django API + SQLite). Django auth jadvallari alohida.
PRAGMA foreign_keys = ON;

DROP TABLE IF EXISTS bed_bookings;
DROP TABLE IF EXISTS guests;
DROP TABLE IF EXISTS room_cleaning;
DROP TABLE IF EXISTS rooms;
DROP TABLE IF EXISTS users;
DROP TABLE IF EXISTS hostels;

CREATE TABLE hostels (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE
);

CREATE TABLE rooms (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  hostel_id INTEGER NOT NULL REFERENCES hostels (id) ON DELETE CASCADE,
  code TEXT NOT NULL,
  name TEXT NOT NULL,
  bed_count INTEGER NOT NULL CHECK (bed_count >= 0 AND bed_count <= 32),
  room_kind TEXT NOT NULL DEFAULT 'dorm' CHECK (room_kind IN ('dorm', 'bathroom')),
  photos TEXT NOT NULL DEFAULT '[]',
  UNIQUE (hostel_id, code)
);

CREATE INDEX rooms_hostel_idx ON rooms (hostel_id);

CREATE TABLE guests (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  identity_key TEXT NOT NULL UNIQUE,
  phone_normalized TEXT NOT NULL DEFAULT '',
  passport_series TEXT NOT NULL DEFAULT '',
  guest_name TEXT NOT NULL DEFAULT '',
  doc_full_name TEXT NOT NULL DEFAULT '',
  doc_birth_date TEXT NOT NULL DEFAULT '',
  doc_expiry_date TEXT NOT NULL DEFAULT '',
  doc_citizenship TEXT NOT NULL DEFAULT '',
  doc_number TEXT NOT NULL DEFAULT '',
  doc_type TEXT NOT NULL DEFAULT '',
  doc_extracted_at TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
  updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

CREATE INDEX guests_identity_idx ON guests (identity_key);

CREATE TABLE bed_bookings (
  id TEXT PRIMARY KEY,
  room_id INTEGER NOT NULL REFERENCES rooms (id) ON DELETE CASCADE,
  bed_index INTEGER NOT NULL CHECK (bed_index >= 1),
  check_in_date TEXT NOT NULL,
  nights INTEGER NOT NULL DEFAULT 1 CHECK (nights >= 1 AND nights <= 365),
  guest_name TEXT NOT NULL DEFAULT '',
  guest_phone TEXT NOT NULL DEFAULT '',
  guest_id INTEGER REFERENCES guests (id),
  price REAL NOT NULL DEFAULT 0,
  paid REAL NOT NULL DEFAULT 0,
  notes TEXT NOT NULL DEFAULT '',
  photos TEXT NOT NULL DEFAULT '[]',
  checked_in_by TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'cancelled')),
  booking_kind TEXT NOT NULL DEFAULT 'check_in' CHECK (booking_kind IN ('bron', 'check_in')),
  expected_arrival TEXT NOT NULL DEFAULT '',
  cancel_reason_bron TEXT NOT NULL DEFAULT '',
  cancel_reason_checkin TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
  updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

CREATE INDEX bed_bookings_room_idx ON bed_bookings (room_id);
CREATE INDEX bed_bookings_active_idx ON bed_bookings (room_id, status, check_in_date);

CREATE TABLE room_cleaning (
  room_id INTEGER PRIMARY KEY REFERENCES rooms (id) ON DELETE CASCADE,
  status TEXT NOT NULL DEFAULT 'dirty' CHECK (status IN ('dirty', 'cleaned')),
  full_taken INTEGER NOT NULL DEFAULT 0 CHECK (full_taken IN (0, 1)),
  full_taken_mode TEXT NOT NULL DEFAULT '' CHECK (full_taken_mode IN ('', 'check_in', 'bron')),
  photos_before TEXT NOT NULL DEFAULT '[]',
  photos_after TEXT NOT NULL DEFAULT '[]',
  updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

CREATE TABLE users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  login TEXT NOT NULL UNIQUE,
  display_name TEXT NOT NULL,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'staff' CHECK (role IN ('admin', 'staff')),
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

CREATE INDEX users_active_idx ON users (active);
