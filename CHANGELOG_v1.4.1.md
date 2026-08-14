# Kazhwan Bot v1.4.1

## Fixes

- Fixed `/settrip` flow in Telegram groups by using ForceReply for text steps.
- Added trip type selection: domestic / international.
- Split trip history into domestic and international sections.
- Added domestic and international trip-history columns to member Excel exports.
- Hardened quiet-hours reopening at 11:00 Iran time.
- Added a 5-minute quiet-hours watchdog for self-healing after Railway restarts or missed jobs.
- Added admin commands `/quieton` and `/quietoff` for manual lock/unlock.
- Added safe database migration for the new `trips.trip_type` column.

Existing PostgreSQL records are preserved.
