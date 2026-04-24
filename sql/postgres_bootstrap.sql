-- Lokal / yangi Postgres: biznes jadvallari (Django api.* managed=False bo‘lgani uchun migrate ularni yaratmaydi).
-- Tartib: bu faylni `psql` dan import qiling, keyin `manage.py migrate`.

BEGIN;

CREATE TABLE IF NOT EXISTS hostels (
  id SERIAL PRIMARY KEY,
  name VARCHAR(200) NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS rooms (
  id SERIAL PRIMARY KEY,
  hostel_id INTEGER NOT NULL REFERENCES hostels (id) ON DELETE CASCADE,
  code VARCHAR(64) NOT NULL,
  name VARCHAR(255) NOT NULL,
  bed_count SMALLINT NOT NULL CHECK (bed_count >= 0 AND bed_count <= 32),
  room_kind VARCHAR(20) NOT NULL DEFAULT 'dorm' CHECK (room_kind IN ('dorm', 'bathroom')),
  photos TEXT NOT NULL DEFAULT '[]',
  UNIQUE (hostel_id, code)
);
CREATE INDEX IF NOT EXISTS rooms_hostel_idx ON rooms (hostel_id);

CREATE TABLE IF NOT EXISTS bed_bookings (
  id VARCHAR(36) PRIMARY KEY,
  room_id INTEGER NOT NULL REFERENCES rooms (id) ON DELETE CASCADE,
  bed_index SMALLINT NOT NULL CHECK (bed_index >= 1),
  check_in_date VARCHAR(10) NOT NULL,
  nights SMALLINT NOT NULL DEFAULT 1 CHECK (nights >= 1 AND nights <= 365),
  guest_name VARCHAR(200) NOT NULL DEFAULT '',
  guest_phone VARCHAR(32) NOT NULL DEFAULT '',
  price DOUBLE PRECISION NOT NULL DEFAULT 0,
  paid DOUBLE PRECISION NOT NULL DEFAULT 0,
  notes TEXT NOT NULL DEFAULT '',
  photos TEXT NOT NULL DEFAULT '[]',
  checked_in_by VARCHAR(200) NOT NULL DEFAULT '',
  status VARCHAR(20) NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'cancelled')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS bed_bookings_room_idx ON bed_bookings (room_id);
CREATE INDEX IF NOT EXISTS bed_bookings_active_idx ON bed_bookings (room_id, status, check_in_date);

CREATE TABLE IF NOT EXISTS room_cleaning (
  room_id INTEGER PRIMARY KEY REFERENCES rooms (id) ON DELETE CASCADE,
  status VARCHAR(20) NOT NULL DEFAULT 'dirty' CHECK (status IN ('dirty', 'cleaned')),
  photos_before TEXT NOT NULL DEFAULT '[]',
  photos_after TEXT NOT NULL DEFAULT '[]',
  updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS users (
  id SERIAL PRIMARY KEY,
  login VARCHAR(64) NOT NULL UNIQUE,
  display_name VARCHAR(200) NOT NULL,
  password_hash VARCHAR(255) NOT NULL,
  role VARCHAR(20) NOT NULL DEFAULT 'staff' CHECK (role IN ('admin', 'staff')),
  active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS users_active_idx ON users (active);

COMMIT;
