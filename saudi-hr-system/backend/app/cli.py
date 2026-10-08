from __future__ import annotations

import sys

import typer

cli = typer.Typer(help="Saudi HR System administration commands")


@cli.command("create-platform-admin")
def create_platform_admin(
    email: str = typer.Option(..., prompt=True),
    full_name: str = typer.Option(..., prompt=True),
    password: str = typer.Option(..., prompt=True, hide_input=True,
                                 confirmation_prompt=True),
) -> None:
    """Create the first platform administrator account."""
    from sqlalchemy import select

    from app.core.database import SessionLocal
    from app.core.rls import clear_context, elevate_for_seed
    from app.core.security import hash_password
    from app.shared.models import User

    db = SessionLocal()
    try:
        email_norm = email.strip().lower()
        elevate_for_seed(db)
        existing = db.execute(
            select(User).where(User.email == email_norm)
        ).scalar_one_or_none()
        if existing is not None:
            if existing.is_platform_admin:
                clear_context(db)
                typer.echo("Platform admin already exists.")
                raise typer.Exit(code=0)
            existing.is_platform_admin = True
            existing.is_active = True
            db.add(existing)
            db.commit()
            clear_context(db)
            typer.echo(f"Promoted {email_norm} to platform administrator.")
            return

        user = User(
            email=email_norm,
            full_name=full_name,
            password_hash=hash_password(password),
            is_active=True,
            is_platform_admin=True,
        )
        db.add(user)
        db.commit()
        clear_context(db)
        typer.echo(f"Created platform administrator {email_norm}.")
    finally:
        db.close()


@cli.command("apply-rls")
def apply_rls() -> None:
    """(Re)apply RLS functions and policies to the configured database."""
    import app.audit.model  # noqa: F401 - registers audit table rules
    import app.shared.models  # noqa: F401 - registers shared table rules
    from app.core.database import SessionLocal
    from app.core.rls import apply_all_policies, clear_context
    from app.core.rls_phase2 import register_phase2_rls
    from app.core.rls_phase3 import register_phase3_rls
    from app.core.rls_phase4 import register_phase4_rls
    from app.core.rls_phase5 import register_phase5_rls
    from app.core.rls_phase6 import register_phase6_rls
    from app.core.rls_phase7 import register_phase7_rls
    from app.core.rls_phase8 import register_phase8_rls

    register_phase2_rls()
    register_phase3_rls()
    register_phase4_rls()
    register_phase5_rls()
    register_phase6_rls()
    register_phase7_rls()
    register_phase8_rls()

    db = SessionLocal()
    try:
        apply_all_policies(db)
        db.commit()
        clear_context(db)
        typer.echo("RLS functions and policies applied.")
    finally:
        db.close()


def main() -> None:
    sys.path.insert(0, ".")
    cli()


if __name__ == "__main__":
    main()
