"""
Performance Reviews Router - US12
تقييم الأداء: دورات المراجعة، الأهداف، التقييم الذاتي، تقييم المدير، الدرجة المركبة
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import text
from typing import Any, Dict, List, Optional
from decimal import Decimal, ROUND_HALF_UP
import json
import logging

from database import get_db_connection
from routers.auth import get_current_user, UserResponse, get_current_user_company
from utils.permissions import branch_scope_filter, require_permission, require_module, validate_branch_access
from utils.audit import log_activity
from schemas.performance import (
    ReviewCycleCreate, GoalCreate, SelfAssessmentSubmit, ManagerAssessmentSubmit,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/hr/performance",
    tags=["Performance Reviews - تقييم الأداء"],
    dependencies=[Depends(require_module("hr"))],
)


def _branch_condition(current_user, branch_id, column: str, params: Dict[str, Any], branch_param: str = "bid") -> str:
    clause = branch_scope_filter(current_user, branch_id, column, params, branch_param=branch_param)
    return clause[4:].strip() if clause.startswith("AND ") else clause.strip()


# =============================================
# دورات المراجعة - Review Cycles
# =============================================

@router.post("/cycles", dependencies=[Depends(require_permission("hr.performance_manage"))], response_model=Dict[str, Any])
def create_cycle(
    data: ReviewCycleCreate,
    request: Request,
    current_user: UserResponse = Depends(get_current_user),
    company_id: str = Depends(get_current_user_company),
):
    """Create Cycle."""
    conn = get_db_connection(company_id)
    try:
        if data.period_end <= data.period_start:
            raise HTTPException(**http_error(400, "period_end_must_be_after_period_start", request))

        row = conn.execute(text("""
            INSERT INTO review_cycles (name, period_start, period_end,
                self_assessment_deadline, manager_review_deadline, status, created_by)
            VALUES (:name, :ps, :pe, :sad, :mrd, 'draft', :uid)
            RETURNING id
        """), {
            "name": data.name, "ps": data.period_start, "pe": data.period_end,
            "sad": data.self_assessment_deadline, "mrd": data.manager_review_deadline,
            "uid": current_user.id,
        }).fetchone()
        conn.commit()
        log_activity(
            conn, user_id=current_user.id, username=getattr(current_user, "username", "unknown"),
            action="hr.performance.cycle_create", resource_type="review_cycle",
            resource_id=str(row[0]), details={"name": data.name}, request=request
        )
        return {"id": row[0], "message": i18n_message("review_cycle_created", request)}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"Create cycle error: {e}")
        raise HTTPException(**http_error(500, "failed_to_create_review_cycle", request))
    finally:
        conn.close()


@router.get("/cycles", dependencies=[Depends(require_permission("hr.performance_view"))], response_model=List[Dict[str, Any]])
def list_cycles(
    status: Optional[str] = None,
    branch_id: Optional[int] = None,
    current_user: UserResponse = Depends(get_current_user),
    company_id: str = Depends(get_current_user_company),
):
    """List Cycles."""
    conn = get_db_connection(company_id)
    try:
        conditions = ["1=1"]
        params = {}
        if status:
            conditions.append("rc.status = :status")
            params["status"] = status

        branch_filter = ""
        branch_condition = _branch_condition(current_user, branch_id, "branch_id", params)
        if branch_condition:
            branch_filter = f"AND pr_inner.employee_id IN (SELECT id FROM employees WHERE {branch_condition})"

        try:
            rows = conn.execute(text(f"""
                SELECT rc.*,
                    COALESCE(cnt.total, 0) as total_reviews,
                    COALESCE(cnt.completed, 0) as completed_reviews
                FROM review_cycles rc
                LEFT JOIN (
                    SELECT cycle_id,
                        COUNT(*) as total,
                        COUNT(*) FILTER (WHERE status = 'completed') as completed
                    FROM performance_reviews pr_inner
                    WHERE cycle_id IS NOT NULL {branch_filter}
                    GROUP BY cycle_id
                ) cnt ON cnt.cycle_id = rc.id
                WHERE {' AND '.join(conditions)}
                ORDER BY rc.created_at DESC
            """), params).fetchall()
        except Exception as e:
            conn.rollback()
            if "does not exist" in str(e):
                return []
            raise
        return [dict(r._mapping) for r in rows]
    finally:
        conn.close()


@router.post("/cycles/{cycle_id}/launch", dependencies=[Depends(require_permission("hr.performance_manage"))], response_model=Dict[str, Any])
def launch_cycle(
    cycle_id: int,
    request: Request,
    branch_id: Optional[int] = None,
    current_user: UserResponse = Depends(get_current_user),
    company_id: str = Depends(get_current_user_company),
):
    """Launch cycle: create a PerformanceReview for every active employee, status = pending_self."""
    conn = get_db_connection(company_id)
    try:
        cycle = conn.execute(text(
            "SELECT id, name, status, period_start, period_end FROM review_cycles WHERE id = :id"
        ), {"id": cycle_id}).fetchone()

        if not cycle:
            raise HTTPException(**http_error(404, "cycle_not_found", request))

        c = dict(cycle._mapping)
        if c["status"] != "draft":
            raise HTTPException(**http_error(400, "only_draft_cycles_can_be_launched", request))

        # Check idempotency
        existing = conn.execute(text(
            "SELECT COUNT(*) FROM performance_reviews WHERE cycle_id = :cid"
        ), {"cid": cycle_id}).scalar()
        if existing > 0:
            raise HTTPException(**http_error(400, "reviews_already_exist_for_this_cycle", request))

        # Fetch active employees with their managers
        emp_query = """
            SELECT e.id as employee_id,
                   COALESCE(e.manager_id, (
                       SELECT d.manager_id FROM departments d
                       WHERE d.id = e.department_id
                       LIMIT 1
                   )) as manager_id
            FROM employees e
            WHERE e.status = 'active'
        """
        emp_params = {}
        branch_condition = _branch_condition(current_user, branch_id, "e.branch_id", emp_params)
        if branch_condition:
            emp_query += " AND " + branch_condition
        employees = conn.execute(text(emp_query), emp_params).fetchall()

        if not employees:
            raise HTTPException(**http_error(400, "no_active_employees_found", request))

        review_period = f"{c['period_start']} - {c['period_end']}"
        total_created = 0

        for emp in employees:
            e = dict(emp._mapping)
            conn.execute(text("""
                INSERT INTO performance_reviews
                    (cycle_id, employee_id, reviewer_id, review_period, review_date, review_type, status)
                VALUES (:cid, :eid, :rid, :period, CURRENT_DATE, 'cycle', 'pending_self')
            """), {
                "cid": cycle_id,
                "eid": e["employee_id"],
                "rid": e.get("manager_id"),
                "period": review_period,
            })
            total_created += 1

        # Update cycle status
        conn.execute(text(
            "UPDATE review_cycles SET status = 'active', updated_at = NOW() WHERE id = :id"
        ), {"id": cycle_id})

        conn.commit()
        log_activity(
            conn, user_id=current_user.id, username=getattr(current_user, "username", "unknown"),
            action="hr.performance.cycle_launch", resource_type="review_cycle",
            resource_id=str(cycle_id), details={"total_reviews": total_created}, request=request
        )
        return {"message": i18n_message("performance_cycle_launched", request), "total_reviews": total_created}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"Launch cycle error: {e}")
        raise HTTPException(**http_error(500, "failed_to_launch_cycle", request))
    finally:
        conn.close()


# =============================================
# مراجعاتي - My Reviews (Employee)
# =============================================

@router.get("/reviews", dependencies=[Depends(require_permission("hr.performance_self"))], response_model=Dict[str, Any])
def list_my_reviews(
    cycle_id: Optional[int] = None,
    branch_id: Optional[int] = None,
    current_user: UserResponse = Depends(get_current_user),
    company_id: str = Depends(get_current_user_company),
):
    """List reviews for the current employee."""
    conn = get_db_connection(company_id)
    try:
        # Find employee linked to current user
        emp = conn.execute(text(
            "SELECT id FROM employees WHERE user_id = :uid LIMIT 1"
        ), {"uid": current_user.id}).fetchone()

        if not emp:
            return []

        conditions = ["pr.employee_id = :eid"]
        params = {"eid": emp[0]}
        if cycle_id:
            conditions.append("pr.cycle_id = :cid")
            params["cid"] = cycle_id
        branch_condition = _branch_condition(current_user, branch_id, "e.branch_id", params)
        if branch_condition:
            conditions.append(branch_condition)

        rows = conn.execute(text(f"""
            SELECT pr.*,
                rc.name as cycle_name,
                e.first_name || ' ' || e.last_name as employee_name,
                r.first_name || ' ' || r.last_name as reviewer_name
            FROM performance_reviews pr
            LEFT JOIN review_cycles rc ON pr.cycle_id = rc.id
            LEFT JOIN employees e ON pr.employee_id = e.id
            LEFT JOIN employees r ON pr.reviewer_id = r.id
            WHERE {' AND '.join(conditions)}
            ORDER BY pr.created_at DESC
        """), params).fetchall()

        results = []
        for row in rows:
            d = dict(row._mapping)
            # Fetch goals
            goals = conn.execute(text(
                "SELECT * FROM performance_goals WHERE review_id = :rid ORDER BY id"
            ), {"rid": d["id"]}).fetchall()
            d["goals"] = [dict(g._mapping) for g in goals]
            results.append(d)

        return results
    finally:
        conn.close()


@router.put("/reviews/{review_id}/self-assessment", dependencies=[Depends(require_permission("hr.performance_self"))], response_model=Dict[str, Any])
def submit_self_assessment(
    review_id: int,
    data: SelfAssessmentSubmit,
    request: Request,
    current_user: UserResponse = Depends(get_current_user),
    company_id: str = Depends(get_current_user_company),
):
    """Submit Self Assessment."""
    conn = get_db_connection(company_id)
    try:
        # Verify ownership
        review = conn.execute(text("""
            SELECT pr.id, pr.status, pr.employee_id, e.user_id
            FROM performance_reviews pr
            JOIN employees e ON pr.employee_id = e.id
            WHERE pr.id = :rid
        """), {"rid": review_id}).fetchone()

        if not review:
            raise HTTPException(**http_error(404, "review_not_found", request))

        rv = dict(review._mapping)
        if rv["user_id"] != current_user.id:
            raise HTTPException(**http_error(403, "you_can_only_submit_your_own_self_assessment", request))

        if rv["status"] != "pending_self":
            raise HTTPException(**http_error(400, "self_assessment_already_submitted_or_review_is_not", request))

        assessment_data = [s.model_dump() for s in data.scores]

        conn.execute(text("""
            UPDATE performance_reviews
            SET self_assessment = :sa::jsonb,
                self_comments = :comments,
                status = 'pending_manager',
                updated_at = NOW()
            WHERE id = :rid
        """), {
            "sa": json.dumps(assessment_data),
            "comments": data.overall_comments,
            "rid": review_id,
        })
        conn.commit()
        log_activity(
            conn, user_id=current_user.id, username=getattr(current_user, "username", "unknown"),
            action="hr.performance.self_assessment", resource_type="performance_review",
            resource_id=str(review_id), details={}, request=request
        )
        return {"message": i18n_message("self_assessment_submitted", request)}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"Self-assessment error: {e}")
        raise HTTPException(**http_error(500, "failed_to_submit_self_assessment", request))
    finally:
        conn.close()


# =============================================
# مراجعات الفريق - Team Reviews (Manager)
# =============================================

@router.get("/team-reviews", dependencies=[Depends(require_permission("hr.performance_review"))], response_model=Dict[str, Any])
def list_team_reviews(
    cycle_id: Optional[int] = None,
    branch_id: Optional[int] = None,
    current_user: UserResponse = Depends(get_current_user),
    company_id: str = Depends(get_current_user_company),
):
    """List reviews where current user is the reviewer (manager)."""
    conn = get_db_connection(company_id)
    try:
        # Find employee id of current user (they are the reviewer/manager)
        mgr = conn.execute(text(
            "SELECT id FROM employees WHERE user_id = :uid LIMIT 1"
        ), {"uid": current_user.id}).fetchone()

        if not mgr:
            # Admins can see all if no employee record
            if current_user.role in ("admin", "system_admin"):
                conditions = ["1=1"]
                params = {}
            else:
                return []
        else:
            conditions = ["pr.reviewer_id = :mgr_id"]
            params = {"mgr_id": mgr[0]}

        if cycle_id:
            conditions.append("pr.cycle_id = :cid")
            params["cid"] = cycle_id
        branch_condition = _branch_condition(current_user, branch_id, "e.branch_id", params)
        if branch_condition:
            conditions.append(branch_condition)

        rows = conn.execute(text(f"""
            SELECT pr.*,
                rc.name as cycle_name,
                e.first_name || ' ' || e.last_name as employee_name,
                r.first_name || ' ' || r.last_name as reviewer_name
            FROM performance_reviews pr
            LEFT JOIN review_cycles rc ON pr.cycle_id = rc.id
            LEFT JOIN employees e ON pr.employee_id = e.id
            LEFT JOIN employees r ON pr.reviewer_id = r.id
            WHERE {' AND '.join(conditions)}
            ORDER BY pr.created_at DESC
        """), params).fetchall()

        results = []
        for row in rows:
            d = dict(row._mapping)
            goals = conn.execute(text(
                "SELECT * FROM performance_goals WHERE review_id = :rid ORDER BY id"
            ), {"rid": d["id"]}).fetchall()
            d["goals"] = [dict(g._mapping) for g in goals]
            results.append(d)

        return results
    finally:
        conn.close()


@router.put("/reviews/{review_id}/manager-assessment", dependencies=[Depends(require_permission("hr.performance_review"))], response_model=Dict[str, Any])
def submit_manager_assessment(
    review_id: int,
    data: ManagerAssessmentSubmit,
    request: Request,
    current_user: UserResponse = Depends(get_current_user),
    company_id: str = Depends(get_current_user_company),
):
    """Submit Manager Assessment."""
    conn = get_db_connection(company_id)
    try:
        review = conn.execute(text("""
            SELECT pr.id, pr.status, pr.reviewer_id, e.user_id as reviewer_user_id
            FROM performance_reviews pr
            LEFT JOIN employees e ON pr.reviewer_id = e.id
            WHERE pr.id = :rid
        """), {"rid": review_id}).fetchone()

        if not review:
            raise HTTPException(**http_error(404, "review_not_found", request))

        rv = dict(review._mapping)

        # Allow admin or the assigned reviewer
        is_admin = current_user.role in ("admin", "system_admin")
        is_reviewer = rv.get("reviewer_user_id") == current_user.id
        if not is_admin and not is_reviewer:
            raise HTTPException(**http_error(403, "only_the_assigned_reviewer_can_submit_manager_asse", request))

        if rv["status"] != "pending_manager":
            raise HTTPException(**http_error(400, "review_must_be_pending_manager_assessment", request))

        assessment_data = [s.model_dump() for s in data.scores]

        conn.execute(text("""
            UPDATE performance_reviews
            SET manager_assessment = :ma::jsonb,
                manager_comments = :comments,
                updated_at = NOW()
            WHERE id = :rid
        """), {
            "ma": json.dumps(assessment_data),
            "comments": data.overall_comments,
            "rid": review_id,
        })
        conn.commit()
        log_activity(
            conn, user_id=current_user.id, username=getattr(current_user, "username", "unknown"),
            action="hr.performance.manager_assessment", resource_type="performance_review",
            resource_id=str(review_id), details={}, request=request
        )
        return {"message": i18n_message("manager_assessment_submitted", request)}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"Manager assessment error: {e}")
        raise HTTPException(**http_error(500, "failed_to_submit_manager_assessment", request))
    finally:
        conn.close()


# =============================================
# إتمام المراجعة - Finalize Review
# =============================================

@router.post("/reviews/{review_id}/finalize", dependencies=[Depends(require_permission("hr.performance_manage"))], response_model=Dict[str, Any])
def finalize_review(
    review_id: int,
    request: Request,
    current_user: UserResponse = Depends(get_current_user),
    company_id: str = Depends(get_current_user_company),
):
    """Finalize a review: compute composite score from weighted manager scores."""
    conn = get_db_connection(company_id)
    try:
        review = conn.execute(text("""
            SELECT id, status, manager_assessment, cycle_id
            FROM performance_reviews WHERE id = :rid
        """), {"rid": review_id}).fetchone()

        if not review:
            raise HTTPException(**http_error(404, "review_not_found", request))

        rv = dict(review._mapping)

        if rv["status"] == "completed":
            raise HTTPException(**http_error(400, "review_already_finalized", request))

        manager_scores = rv.get("manager_assessment")
        if not manager_scores:
            raise HTTPException(**http_error(400, "manager_assessment_not_submitted_yet", request))

        # Fetch goals with weights for this review
        goals = conn.execute(text(
            "SELECT id, weight FROM performance_goals WHERE review_id = :rid"
        ), {"rid": review_id}).fetchall()

        goal_weights = {g[0]: float(g[1]) for g in goals}
        total_weight = sum(goal_weights.values())

        if total_weight == 0:
            # If no goals defined, simple average of manager scores
            scores = [s["score"] for s in manager_scores if "score" in s]
            composite = sum(scores) / len(scores) if scores else 0
        else:
            # Weighted average using goal weights
            composite = Decimal("0")
            for score_entry in manager_scores:
                gid = score_entry.get("goal_id")
                sc = Decimal(str(score_entry.get("score", 0)))
                w = Decimal(str(goal_weights.get(gid, 0)))
                if total_weight > 0:
                    composite += sc * w / Decimal(str(total_weight))
            composite = float(composite.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

        conn.execute(text("""
            UPDATE performance_reviews
            SET composite_score = :score, status = 'completed',
                overall_rating = :score, updated_at = NOW()
            WHERE id = :rid
        """), {"score": composite, "rid": review_id})

        # Check if all reviews in the cycle are completed → complete the cycle
        if rv.get("cycle_id"):
            pending = conn.execute(text("""
                SELECT COUNT(*) FROM performance_reviews
                WHERE cycle_id = :cid AND status != 'completed'
            """), {"cid": rv["cycle_id"]}).scalar()

            if pending == 0:
                conn.execute(text(
                    "UPDATE review_cycles SET status = 'completed', updated_at = NOW() WHERE id = :cid"
                ), {"cid": rv["cycle_id"]})

        conn.commit()
        log_activity(
            conn, user_id=current_user.id, username=getattr(current_user, "username", "unknown"),
            action="hr.performance.finalize", resource_type="performance_review",
            resource_id=str(review_id), details={"composite_score": composite}, request=request
        )
        return {"message": i18n_message("review_finalized", request), "composite_score": composite}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"Finalize review error: {e}")
        raise HTTPException(**http_error(500, "failed_to_finalize_review", request))
    finally:
        conn.close()


# =============================================
# أهداف الأداء - Performance Goals
# =============================================

@router.post("/reviews/{review_id}/goals", dependencies=[Depends(require_permission("hr.performance_manage"))], response_model=Dict[str, Any])
def add_goal(
    review_id: int,
    data: GoalCreate,
    request: Request,
    current_user: UserResponse = Depends(get_current_user),
    company_id: str = Depends(get_current_user_company),
):
    """Add Goal."""
    conn = get_db_connection(company_id)
    try:
        # Verify review exists
        review = conn.execute(text(
            "SELECT id FROM performance_reviews WHERE id = :rid"
        ), {"rid": review_id}).fetchone()
        if not review:
            raise HTTPException(**http_error(404, "review_not_found", request))

        row = conn.execute(text("""
            INSERT INTO performance_goals (review_id, title, description, weight, target)
            VALUES (:rid, :title, :desc, :weight, :target)
            RETURNING id
        """), {
            "rid": review_id, "title": data.title,
            "desc": data.description, "weight": data.weight,
            "target": data.target,
        }).fetchone()
        conn.commit()
        log_activity(
            conn, user_id=current_user.id, username=getattr(current_user, "username", "unknown"),
            action="hr.performance.goal_add", resource_type="performance_goal",
            resource_id=str(row[0]), details={"review_id": review_id, "title": data.title}, request=request
        )
        return {"id": row[0], "message": i18n_message("goal_added", request)}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"Add goal error: {e}")
        raise HTTPException(**http_error(500, "failed_to_add_goal", request))
    finally:
        conn.close()


@router.get("/reviews/{review_id}/goals", dependencies=[Depends(require_permission("hr.performance_view"))], response_model=List[Dict[str, Any]])
def list_goals(
    review_id: int,
    company_id: str = Depends(get_current_user_company),
):
    """List Goals."""
    conn = get_db_connection(company_id)
    try:
        rows = conn.execute(text(
            "SELECT * FROM performance_goals WHERE review_id = :rid ORDER BY id"
        ), {"rid": review_id}).fetchall()
        return [dict(r._mapping) for r in rows]
    finally:
        conn.close()


@router.delete("/goals/{goal_id}", dependencies=[Depends(require_permission("hr.performance_manage"))], response_model=Dict[str, Any])
def delete_goal(
    goal_id: int,
    request: Request,
    current_user: UserResponse = Depends(get_current_user),
    company_id: str = Depends(get_current_user_company),
):
    """Delete Goal."""
    conn = get_db_connection(company_id)
    try:
        result = conn.execute(text(
            "DELETE FROM performance_goals WHERE id = :gid"
        ), {"gid": goal_id})
        conn.commit()
        if result.rowcount == 0:
            raise HTTPException(**http_error(404, "goal_not_found", request))
        log_activity(
            conn, user_id=current_user.id, username=getattr(current_user, "username", "unknown"),
            action="hr.performance.goal_delete", resource_type="performance_goal",
            resource_id=str(goal_id), details={}, request=request
        )
        return {"message": i18n_message("goal_deleted", request)}
    except HTTPException:
        raise
    except Exception:
        conn.rollback()
        raise HTTPException(**http_error(500, "failed_to_delete_goal", request))
    finally:
        conn.close()


# =============================================
# تفاصيل المراجعة - Review Detail
# =============================================

@router.get("/reviews/{review_id}", dependencies=[Depends(require_permission("hr.performance_view"))], response_model=Dict[str, Any])
def get_review_detail(request: Request, 
    review_id: int,
    current_user: UserResponse = Depends(get_current_user),
    company_id: str = Depends(get_current_user_company),
):
    """Get Review Detail."""
    conn = get_db_connection(company_id)
    try:
        row = conn.execute(text("""
            SELECT pr.*,
                rc.name as cycle_name,
                e.first_name || ' ' || e.last_name as employee_name,
                r.first_name || ' ' || r.last_name as reviewer_name
            FROM performance_reviews pr
            LEFT JOIN review_cycles rc ON pr.cycle_id = rc.id
            LEFT JOIN employees e ON pr.employee_id = e.id
            LEFT JOIN employees r ON pr.reviewer_id = r.id
            WHERE pr.id = :rid
        """), {"rid": review_id}).fetchone()

        if not row:
            raise HTTPException(**http_error(404, "review_not_found", request))

        d = dict(row._mapping)
        # Validate branch access if employee has a branch
        emp_branch = conn.execute(text(
            "SELECT branch_id FROM employees WHERE id = :eid"
        ), {"eid": d.get("employee_id")}).fetchone()
        if emp_branch and emp_branch[0]:
            validate_branch_access(current_user, emp_branch[0])

        goals = conn.execute(text(
            "SELECT * FROM performance_goals WHERE review_id = :rid ORDER BY id"
        ), {"rid": review_id}).fetchall()
        d["goals"] = [dict(g._mapping) for g in goals]
        return d
    finally:
        conn.close()
