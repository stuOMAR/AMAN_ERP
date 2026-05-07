# Contract: Attendance ↔ Time Tracking Link

## Purpose
Single helper that consolidates per-employee per-day attendance with time-tracking entries to produce one authoritative work-hours record (used by payroll calculation).

## Helper

`services/hr/attendance_timetracking.py::link_attendance_to_timetracking(employee_id, work_date) -> LinkedDay`

`LinkedDay` fields: `attendance_in`, `attendance_out`, `timetracking_total_hours`, `discrepancy_minutes`, `effective_hours`, `source` (`attendance_only|timetracking_only|both|reconciled`).

## Behavior

- If both sources present: `effective_hours = min(attendance_window, timetracking_total)` with `discrepancy_minutes` recorded.
- If only attendance: `effective_hours = attendance_window`.
- If only timetracking: `effective_hours = timetracking_total`.
- If neither: returns `None` (no row).
- Payroll calculation reads `effective_hours` from this helper exclusively.

## Errors

| Code | When |
|------|------|
| 409 `attendance.discrepancy_threshold_exceeded` | `discrepancy_minutes > company_settings.hr.attendance_discrepancy_max_minutes`; routes to `manual_review`. |
