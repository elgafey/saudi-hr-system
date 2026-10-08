from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.orm import Session

# ---------------------------------------------------------------------------
# Row Level Security framework (Phase 1, reused by every future module).
#
# Layer 1: application scope checks (routers/services)
# Layer 2: service-layer authorization (permissions + company membership)
# Layer 3: PostgreSQL RLS with FORCE ROW LEVEL SECURITY - even the table
#          owner (saudi_hr_user) is subject to tenant isolation.
#
# Context is always set via set_config(..., is_local=true) so it exists only
# inside the current transaction and can never leak into later requests.
# Default with no context = deny (empty company scope, non-admin).
# ---------------------------------------------------------------------------

GUC_COMPANY_IDS = "app.company_ids"
GUC_PLATFORM_ADMIN = "app.is_platform_admin"
GUC_USER_ID = "app.user_id"


@dataclass(frozen=True)
class RLSRule:
    """Tenant-isolation policy definition for one company-scoped table.

    extra_using / extra_check allow narrow row-level exceptions (e.g. a user
    reading their own profile during context bootstrap). They are ANDed into
    the respective clause with OR.
    """

    table: str
    company_column: str = "company_id"
    policy_name: str = ""
    extra_using: str = ""
    extra_check: str = ""
    columns: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.policy_name:
            object.__setattr__(self, "policy_name", f"{self.table}_tenant_isolation")


RLS_REGISTRY: dict[str, RLSRule] = {}


def register_rls(rule: RLSRule) -> RLSRule:
    RLS_REGISTRY[rule.table] = rule
    return rule


def company_scoped(
    table: str,
    company_column: str = "company_id",
    extra_using: str = "",
    extra_check: str = "",
) -> RLSRule:
    return register_rls(
        RLSRule(
            table=table,
            company_column=company_column,
            extra_using=extra_using,
            extra_check=extra_check,
        )
    )


# ---------------------------------------------------------------------------
# PostgreSQL helper functions (idempotent DDL, applied by migration/CLI)
# ---------------------------------------------------------------------------

SQL_FUNCTIONS = """
CREATE SCHEMA IF NOT EXISTS app;

CREATE OR REPLACE FUNCTION app.current_company_ids() RETURNS integer[]
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
    raw_value TEXT;
    parts TEXT[];
    part TEXT;
    result INTEGER[] := '{}'::integer[];
BEGIN
    raw_value := current_setting('app.company_ids', true);
    IF raw_value IS NULL THEN
        RETURN '{}'::integer[];
    END IF;
    raw_value := btrim(raw_value);
    IF raw_value = '' THEN
        RETURN '{}'::integer[];
    END IF;
    parts := string_to_array(raw_value, ',');
    FOREACH part IN ARRAY parts LOOP
        part := btrim(part);
        IF part ~ '^[0-9]{1,10}$' AND part <> '0' THEN
            result := result || (part::integer);
        END IF;
    END LOOP;
    RETURN result;
EXCEPTION
    WHEN OTHERS THEN
        RETURN '{}'::integer[];
END;
$$;

CREATE OR REPLACE FUNCTION app.is_platform_admin() RETURNS boolean
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
    raw_value TEXT;
BEGIN
    raw_value := current_setting('app.is_platform_admin', true);
    RETURN COALESCE(raw_value, '') = 'true';
EXCEPTION
    WHEN OTHERS THEN
        RETURN false;
END;
$$;

CREATE OR REPLACE FUNCTION app.current_user_id() RETURNS integer
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
    raw_value TEXT;
BEGIN
    raw_value := current_setting('app.user_id', true);
    IF raw_value IS NULL OR btrim(raw_value) = '' THEN
        RETURN NULL;
    END IF;
    IF btrim(raw_value) !~ '^[0-9]{1,10}$' THEN
        RETURN NULL;
    END IF;
    RETURN (btrim(raw_value))::integer;
EXCEPTION
    WHEN OTHERS THEN
        RETURN NULL;
END;
$$;
"""


def policy_sql(rule: RLSRule) -> str:
    col = rule.company_column
    using = f"(app.is_platform_admin() OR {col} = ANY (app.current_company_ids())"
    if rule.extra_using:
        using += f" OR ({rule.extra_using})"
    using += ")"
    check = f"(app.is_platform_admin() OR {col} = ANY (app.current_company_ids())"
    if rule.extra_check:
        check += f" OR ({rule.extra_check})"
    check += ")"
    return (
        f"CREATE POLICY {rule.policy_name} ON {rule.table}\n"
        f"    USING {using}\n"
        f"    WITH CHECK {check};"
    )


def ensure_functions(session: Session) -> None:
    session.execute(text(SQL_FUNCTIONS))
    session.flush()


def apply_policy(session: Session, rule: RLSRule) -> None:
    session.execute(text(f"ALTER TABLE {rule.table} ENABLE ROW LEVEL SECURITY"))
    session.execute(text(f"ALTER TABLE {rule.table} FORCE ROW LEVEL SECURITY"))
    session.execute(
        text(f"DROP POLICY IF EXISTS {rule.policy_name} ON {rule.table}")
    )
    session.execute(text(policy_sql(rule)))
    session.flush()


def apply_all_policies(session: Session) -> None:
    ensure_functions(session)
    for rule in RLS_REGISTRY.values():
        apply_policy(session, rule)


# ---------------------------------------------------------------------------
# Transaction-local context
# ---------------------------------------------------------------------------

def set_context(
    session: Session,
    *,
    user_id: int | None,
    company_ids: list[int] | None,
    is_platform_admin: bool,
) -> None:
    ids = ",".join(str(int(c)) for c in (company_ids or []))
    session.execute(
        text(
            "SELECT set_config(:k_uid, :v_uid, true), "
            "set_config(:k_cids, :v_cids, true), "
            "set_config(:k_admin, :v_admin, true)"
        ),
        {
            "k_uid": GUC_USER_ID,
            "v_uid": str(user_id) if user_id is not None else "",
            "k_cids": GUC_COMPANY_IDS,
            "v_cids": ids,
            "k_admin": GUC_PLATFORM_ADMIN,
            "v_admin": "true" if is_platform_admin else "false",
        },
    )


def clear_context(session: Session) -> None:
    """Reset to deny-by-default (empty scope, non-admin, no user)."""
    set_context(session, user_id=None, company_ids=[], is_platform_admin=False)


def elevate_for_seed(session: Session) -> None:
    """Explicit platform-admin context for seed/bootstrap work.

    Callers MUST clear_context() (or end the transaction) immediately after
    so the elevated state cannot leak into subsequent operations.
    """
    set_context(session, user_id=None, company_ids=[], is_platform_admin=True)
