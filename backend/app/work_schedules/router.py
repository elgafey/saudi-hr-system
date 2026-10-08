from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import (
    Principal,
    client_ip,
    optional_company_header,
    require_permission,
)
from app.core.pagination import Page, PageParams, pagination_params
from app.work_schedules.schemas import (
    BreakOut,
    DayOut,
    ResolvedScheduleOut,
    ScheduleCreate,
    ScheduleDaysOut,
    ScheduleDaysPut,
    ScheduleOut,
    SchedulePage,
    ScheduleUpdate,
)
from app.work_schedules.service import (
    create_schedule,
    day_break_map,
    delete_schedule,
    get_schedule,
    list_days,
    list_schedules,
    put_days,
    resolve_for_employee,
    update_schedule,
)

router = APIRouter(prefix="/work-schedules", tags=["work-schedules"])
resolve_router = APIRouter(
    prefix="/employees/{employee_id}/schedule", tags=["employee-schedule"]
)


def _day_out(day, breaks) -> DayOut:
    return DayOut(
        id=day.id,
        schedule_id=day.schedule_id,
        weekday=day.weekday,
        is_working=day.is_working,
        start_time=day.start_time,
        end_time=day.end_time,
        shift_id=day.shift_id,
        breaks=[BreakOut.model_validate(b) for b in breaks],
    )


@router.get("", response_model=SchedulePage)
def list_all(
    company_id: int | None = Query(default=None, ge=1),
    status: str | None = Query(default=None, pattern="^(active|archived)$"),
    search: str | None = Query(default=None, max_length=100),
    page_params: PageParams = Depends(pagination_params),
    principal: Principal = Depends(require_permission("work_schedule.view")),
    scoped_company: int | None = Depends(optional_company_header),
    db: Session = Depends(get_db),
) -> SchedulePage:
    target = company_id if company_id is not None else scoped_company
    items, total = list_schedules(
        db,
        principal,
        company_id=target,
        status=status,
        search=search,
        page=page_params,
    )
    return SchedulePage(
        items=[ScheduleOut.model_validate(s) for s in items],
        page=Page(
            page=page_params.page,
            page_size=page_params.page_size,
            total=total,
        ),
    )


@router.post("", response_model=ScheduleOut, status_code=201)
def create(
    payload: ScheduleCreate,
    request: Request,
    principal: Principal = Depends(require_permission("work_schedule.create")),
    db: Session = Depends(get_db),
) -> ScheduleOut:
    schedule = create_schedule(
        db, payload=payload, principal=principal, ip=client_ip(request)
    )
    return ScheduleOut.model_validate(schedule)


@router.get("/{schedule_id}", response_model=ScheduleOut)
def read(
    schedule_id: int,
    principal: Principal = Depends(require_permission("work_schedule.view")),
    db: Session = Depends(get_db),
) -> ScheduleOut:
    return ScheduleOut.model_validate(
        get_schedule(db, schedule_id, principal)
    )


@router.patch("/{schedule_id}", response_model=ScheduleOut)
def update(
    schedule_id: int,
    payload: ScheduleUpdate,
    request: Request,
    principal: Principal = Depends(require_permission("work_schedule.update")),
    db: Session = Depends(get_db),
) -> ScheduleOut:
    schedule = update_schedule(
        db,
        schedule_id=schedule_id,
        payload=payload,
        principal=principal,
        ip=client_ip(request),
    )
    return ScheduleOut.model_validate(schedule)


@router.delete("/{schedule_id}", status_code=204)
def remove(
    schedule_id: int,
    request: Request,
    principal: Principal = Depends(require_permission("work_schedule.delete")),
    db: Session = Depends(get_db),
) -> Response:
    delete_schedule(
        db, schedule_id=schedule_id, principal=principal, ip=client_ip(request)
    )
    return Response(status_code=204)


@router.get("/{schedule_id}/days", response_model=ScheduleDaysOut)
def read_days(
    schedule_id: int,
    principal: Principal = Depends(require_permission("work_schedule.view")),
    db: Session = Depends(get_db),
) -> ScheduleDaysOut:
    days = list_days(db, schedule_id=schedule_id, principal=principal)
    breaks = day_break_map(db, days)
    return ScheduleDaysOut(
        items=[_day_out(day, breaks.get(day.id, [])) for day in days]
    )


@router.put("/{schedule_id}/days", response_model=ScheduleDaysOut)
def replace_days(
    schedule_id: int,
    payload: ScheduleDaysPut,
    request: Request,
    principal: Principal = Depends(require_permission("work_schedule.update")),
    db: Session = Depends(get_db),
) -> ScheduleDaysOut:
    days = put_days(
        db,
        schedule_id=schedule_id,
        payload=payload,
        principal=principal,
        ip=client_ip(request),
    )
    breaks = day_break_map(db, days)
    return ScheduleDaysOut(
        items=[_day_out(day, breaks.get(day.id, [])) for day in days]
    )


@resolve_router.get("", response_model=ResolvedScheduleOut)
def resolve(
    employee_id: int,
    on_date: date | None = Query(default=None, alias="date"),
    principal: Principal = Depends(
        require_permission("employee_work_assignment.view")
    ),
    db: Session = Depends(get_db),
) -> ResolvedScheduleOut:
    target = on_date if on_date is not None else date.today()
    resolved = resolve_for_employee(
        db, employee_id=employee_id, on_date=target, principal=principal
    )
    return ResolvedScheduleOut(
        date=resolved.day,
        weekday=resolved.weekday,
        is_working=resolved.is_working,
        timezone=resolved.timezone,
        crosses_midnight=resolved.crosses_midnight,
        assignment_id=resolved.assignment.id if resolved.assignment else None,
        schedule_id=resolved.schedule.id if resolved.schedule else None,
        schedule_code=resolved.schedule.code if resolved.schedule else None,
        schedule_name_en=resolved.schedule.name_en if resolved.schedule else None,
        schedule_name_ar=resolved.schedule.name_ar if resolved.schedule else None,
        shift_id=resolved.shift.id if resolved.shift else None,
        shift_code=resolved.shift.code if resolved.shift else None,
        shift_name_en=resolved.shift.name_en if resolved.shift else None,
        start_time=resolved.start_time,
        end_time=resolved.end_time,
        breaks=[BreakOut.model_validate(b) for b in resolved.breaks],
    )
