#!/usr/bin/env bash
set -euo pipefail

DB="$HOME/LAIA/index/sqlite/archive.db"

sqlite3 "$DB" <<'SQL'
.headers on
.mode column

SELECT COUNT(*) AS total_files FROM files;

SELECT extension, COUNT(*) AS count
FROM files
GROUP BY extension
ORDER BY count DESC;

SELECT camera_model, COUNT(*) AS count
FROM files
GROUP BY camera_model
ORDER BY count DESC;

SELECT film_mode, COUNT(*) AS count
FROM files
WHERE film_mode IS NOT NULL
GROUP BY film_mode
ORDER BY count DESC;
SQL
