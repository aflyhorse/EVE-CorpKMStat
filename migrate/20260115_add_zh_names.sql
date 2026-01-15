-- Migration: add Chinese name fields for SDE entities
-- Date: 2026-01-15
--
-- This project uses SQLite by default.
-- These ALTER TABLE statements are compatible with SQLite.
--
-- If you use another DB (e.g. MySQL/PostgreSQL), adjust types accordingly.

ALTER TABLE solar_system ADD COLUMN name_zh VARCHAR;
ALTER TABLE item_type ADD COLUMN name_zh VARCHAR;

-- Optional: indexes if you plan to search by Chinese name frequently.
-- CREATE INDEX IF NOT EXISTS idx_solar_system_name_zh ON solar_system(name_zh);
-- CREATE INDEX IF NOT EXISTS idx_item_type_name_zh ON item_type(name_zh);
