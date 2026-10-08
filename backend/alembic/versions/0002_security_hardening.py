"""users security guard trigger (direct-SQL self-escalation protection)

Revision ID: 0002_security_hardening
Revises: 0001_phase1
Create Date: 2026-10-06

Adds a BEFORE INSERT/UPDATE trigger on users that enforces, at the
database layer, what the application already enforces:

- only a platform-admin GUC context may create platform admins or change
  is_platform_admin / company_id / email / employee_id (tenant identity
  and authorization columns),
- a non-admin actor may never change their own is_active (self-reactivation),
- a non-admin actor may never change another account's password_hash,
- last_login_at and other profile fields keep their legitimate update
  paths (login, profile edits, deactivation by company managers).

RLS remains the tenant-isolation layer; this trigger is defense in depth
for authorization-sensitive columns on a single table.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0002_security_hardening"
down_revision: Union[str, None] = "0001_phase1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

GUARD_FUNCTION = """
CREATE OR REPLACE FUNCTION app.guard_users_security() RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    actor_id INTEGER;
BEGIN
    IF app.is_platform_admin() THEN
        RETURN NEW;
    END IF;

    actor_id := app.current_user_id();

    IF TG_OP = 'INSERT' THEN
        IF NEW.is_platform_admin THEN
            RAISE EXCEPTION
                'users: platform administrators can only be created in platform administrator context';
        END IF;
        RETURN NEW;
    END IF;

    IF NEW.is_platform_admin IS DISTINCT FROM OLD.is_platform_admin
       OR NEW.company_id IS DISTINCT FROM OLD.company_id
       OR NEW.email IS DISTINCT FROM OLD.email
       OR NEW.employee_id IS DISTINCT FROM OLD.employee_id THEN
        RAISE EXCEPTION
            'users: security-sensitive columns require platform administrator context';
    END IF;

    IF actor_id IS NOT NULL AND actor_id = NEW.id THEN
        IF NEW.is_active IS DISTINCT FROM OLD.is_active THEN
            RAISE EXCEPTION
                'users: a user cannot change their own active state';
        END IF;
    ELSIF actor_id IS DISTINCT FROM OLD.id THEN
        IF NEW.password_hash IS DISTINCT FROM OLD.password_hash THEN
            RAISE EXCEPTION
                'users: password changes on other accounts require platform administrator context';
        END IF;
    END IF;

    RETURN NEW;
END;
$$;
"""


def upgrade() -> None:
    op.execute(GUARD_FUNCTION)
    op.execute("DROP TRIGGER IF EXISTS trg_users_security_guard ON users")
    op.execute(
        "CREATE TRIGGER trg_users_security_guard "
        "BEFORE INSERT OR UPDATE ON users "
        "FOR EACH ROW EXECUTE FUNCTION app.guard_users_security()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_users_security_guard ON users")
    op.execute("DROP FUNCTION IF EXISTS app.guard_users_security()")
