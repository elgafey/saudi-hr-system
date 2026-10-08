from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import LeaveInsufficientBalanceError
from app.shared.models import (
    Employee,
    LeaveAllocation,
    LeaveConsumption,
    LeaveRequest,
    LeaveType,
)

_QUANT = Decimal("0.01")


def _q(value: Decimal) -> Decimal:
    return value.quantize(_QUANT, rounding=ROUND_HALF_UP)


@dataclass
class BalanceLine:
    leave_type_id: int
    code: str
    name_ar: str
    name_en: str
    is_paid: bool
    negative_balance_allowed: bool
    allocated_days: Decimal
    used_days: Decimal
    pending_days: Decimal
    remaining_days: Decimal


def _allocations_in_scope(
    db: Session,
    employee: Employee,
    leave_type_id: int,
    *,
    as_of: date | None,
    period: tuple[date, date] | None,
    lock: bool = False,
) -> list[LeaveAllocation]:
    """Approved allocations in scope.

    - ``period=(start, end)``: allocations overlapping that range (the
      submit/approve gate, so a request may draw from every pool covering
      any of its dates, FIFO by period_start).
    - ``as_of=<date>``: allocations covering that date (display balance);
      the scope then widens to the union of their periods.

    Always ordered (period_start, id) - the canonical lock order used by
    every locking caller (deadlock-free across transactions).
    """
    stmt = select(LeaveAllocation).where(
        LeaveAllocation.employee_id == employee.id,
        LeaveAllocation.company_id == employee.company_id,
        LeaveAllocation.leave_type_id == leave_type_id,
        LeaveAllocation.status == "approved",
    )
    if period is not None:
        stmt = stmt.where(
            LeaveAllocation.period_start <= period[1],
            LeaveAllocation.period_end >= period[0],
        )
    elif as_of is not None:
        stmt = stmt.where(
            LeaveAllocation.period_start <= as_of,
            LeaveAllocation.period_end >= as_of,
        )
    stmt = stmt.order_by(LeaveAllocation.period_start, LeaveAllocation.id)
    if lock:
        stmt = stmt.with_for_update()
    return list(db.execute(stmt).scalars())


def _scope_from_allocations(
    allocs: list[LeaveAllocation], fallback: date
) -> tuple[date, date]:
    if not allocs:
        return (fallback, fallback)
    return (
        min(a.period_start for a in allocs),
        max(a.period_end for a in allocs),
    )


def compute_balance(
    db: Session,
    employee: Employee,
    leave_type: LeaveType,
    *,
    as_of: date | None = None,
    period: tuple[date, date] | None = None,
    exclude_request_id: int | None = None,
) -> BalanceLine:
    """Derived balance: allocated / used / pending / remaining.

    - allocated = SUM of approved allocations in scope.
    - used      = SUM of leave_consumptions attached to THOSE allocations
                  (consumptions exist only for APPROVED requests; cancelling
                  deletes them). Tying usage to the counted allocations keeps
                  prior-period usage out of the current pool.
    - pending   = SUM of days of SUBMITTED requests whose dates intersect
                  the scope (minus ``exclude_request_id`` while that request
                  itself is being evaluated).
    - remaining = allocated - used - pending.
    """
    as_of = as_of or date.today()
    allocs = _allocations_in_scope(
        db, employee, leave_type.id, as_of=as_of, period=period
    )
    scope_start, scope_end = (
        period if period is not None else _scope_from_allocations(allocs, as_of)
    )

    allocated = _q(sum((a.allocated_days for a in allocs), Decimal("0.00")))
    used = Decimal("0.00")
    if allocs:
        raw = db.execute(
            select(func.coalesce(func.sum(LeaveConsumption.days), 0)).where(
                LeaveConsumption.company_id == employee.company_id,
                LeaveConsumption.leave_allocation_id.in_([a.id for a in allocs]),
            )
        ).scalar_one()
        used = _q(Decimal(str(raw)))
    pending_stmt = select(func.coalesce(func.sum(LeaveRequest.days), 0)).where(
        LeaveRequest.company_id == employee.company_id,
        LeaveRequest.employee_id == employee.id,
        LeaveRequest.leave_type_id == leave_type.id,
        LeaveRequest.status == "submitted",
        LeaveRequest.start_date <= scope_end,
        LeaveRequest.end_date >= scope_start,
    )
    if exclude_request_id is not None:
        pending_stmt = pending_stmt.where(LeaveRequest.id != exclude_request_id)
    pending = _q(Decimal(str(db.execute(pending_stmt).scalar_one())))
    remaining = _q(allocated - used - pending)
    return BalanceLine(
        leave_type_id=leave_type.id,
        code=leave_type.code,
        name_ar=leave_type.name_ar,
        name_en=leave_type.name_en,
        is_paid=leave_type.is_paid,
        negative_balance_allowed=leave_type.negative_balance_allowed,
        allocated_days=allocated,
        used_days=used,
        pending_days=pending,
        remaining_days=remaining,
    )


def ensure_balance(
    db: Session,
    employee: Employee,
    leave_type: LeaveType,
    *,
    period: tuple[date, date],
    days_needed: Decimal,
    exclude_request_id: int | None = None,
) -> BalanceLine:
    """Balance gate for submit/approve (approve runs it again under the
    allocation row locks)."""
    line = compute_balance(
        db,
        employee,
        leave_type,
        period=period,
        exclude_request_id=exclude_request_id,
    )
    if line.remaining_days - days_needed >= 0:
        return line
    # Negative draw-down requires the explicit flag AND a real allocation
    # pool (without a pool there is nothing that could record the usage).
    if leave_type.negative_balance_allowed and line.allocated_days > 0:
        return line
    raise LeaveInsufficientBalanceError(
        "Insufficient leave balance "
        f"(remaining {line.remaining_days}, requested {days_needed})"
    )


def lock_allocations_for_request(
    db: Session,
    employee: Employee,
    leave_type_id: int,
    period: tuple[date, date],
) -> list[LeaveAllocation]:
    """Row-lock every allocation that could fund the request, canonical
    order. Call BEFORE consuming/releasing balance (approve / cancel)."""
    return _allocations_in_scope(
        db, employee, leave_type_id, as_of=None, period=period, lock=True
    )


def consume_fifo(
    db: Session,
    request: LeaveRequest,
    leave_type: LeaveType,
    allocations: list[LeaveAllocation],
) -> list[LeaveConsumption]:
    """FIFO draw-down across allocation periods (oldest period first).

    Raises LEAVE_INSUFFICIENT_BALANCE when the pools cannot fund the
    request and the type does not allow a negative balance; with the flag
    the overage is drawn against the earliest allocation (used_days may
    exceed allocated_days - the CHECK only guards against negatives).
    Allocations arrive already locked in canonical order.
    """
    needed = _q(Decimal(request.days))
    rows: list[LeaveConsumption] = []
    for alloc in allocations:
        if needed <= 0:
            break
        available = _q(Decimal(alloc.allocated_days) - Decimal(alloc.used_days))
        if available <= 0:
            continue
        take = min(available, needed)
        alloc.used_days = _q(Decimal(alloc.used_days) + take)
        rows.append(
            LeaveConsumption(
                company_id=request.company_id,
                leave_request_id=request.id,
                leave_allocation_id=alloc.id,
                days=take,
                for_date=request.start_date,
            )
        )
        needed = _q(needed - take)
    if needed > 0:
        if not allocations or not leave_type.negative_balance_allowed:
            raise LeaveInsufficientBalanceError(
                "Insufficient leave balance for this request"
            )
        alloc = allocations[0]
        alloc.used_days = _q(Decimal(alloc.used_days) + needed)
        rows.append(
            LeaveConsumption(
                company_id=request.company_id,
                leave_request_id=request.id,
                leave_allocation_id=alloc.id,
                days=needed,
                for_date=request.start_date,
            )
        )
    for row in rows:
        db.add(row)
    db.flush()
    return rows


def release_consumptions(
    db: Session,
    request: LeaveRequest,
    locked_allocations: list[LeaveAllocation],
) -> int:
    """Undo a request's consumption (cancel path). ``locked_allocations``
    are the rows locked in canonical order; usage is restored and the
    consumption rows deleted. Returns the number of released rows."""
    rows = list(
        db.execute(
            select(LeaveConsumption)
            .where(LeaveConsumption.leave_request_id == request.id)
            .order_by(LeaveConsumption.id)
        ).scalars()
    )
    if not rows:
        return 0
    by_id = {a.id: a for a in locked_allocations}
    for row in rows:
        alloc = by_id.get(row.leave_allocation_id)
        if alloc is not None:
            restored = _q(Decimal(alloc.used_days) - Decimal(row.days))
            alloc.used_days = restored if restored > 0 else Decimal("0.00")
        db.delete(row)
    db.flush()
    return len(rows)
