# Contract: Technician Profile + Assignment Matcher

## Helpers

`services/fsm/technicians.py::technician_assignment_matcher(service_order) -> [Match]`

`Match` fields: `technician_id`, `score: Decimal (0..1)`, `breakdown: {skills, zones, availability, workload}`, `reason: str`.

## Scoring

```
skills_match    = |required_skills ∩ technician.skills| / max(|required_skills|, 1)
zone_match      = 1.0 if service_order.zone in technician.zones else 0.0
availability    = 1.0 if technician.availability covers service_order.scheduled_window else 0.0
workload_invs   = max(0, 1 - active_orders / company_settings.fsm.workload_target)

score = 0.5 * skills_match + 0.2 * zone_match + 0.2 * availability + 0.1 * workload_invs
```

Inactive technicians and those with expired required certifications are excluded.

## Auto-Assign

- If `top.score >= company_settings.fsm.auto_assign_threshold` (default `0.75`):
  - `service_orders.assigned_technician_id = top.technician_id`.
  - Audit `service_order.auto_assigned`.
- Else: returned ranked list to dispatcher UI, no assignment.

## Errors

| Code | When |
|------|------|
| 422 `technician.no_candidates` | Zero matches (zero technicians, or all excluded). |
| 422 `technician.required_skill_unknown` | Order references undefined skill code. |
