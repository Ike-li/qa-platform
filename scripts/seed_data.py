"""Development seed data script.

Creates:
- Admin user: admin / admin123 (super_admin role)
- Sample project linked to a test repo
- Sample cron schedule (daily at 2:00 AM UTC)

Production guard: refuses to run if FLASK_ENV=production.

Usage:
    python scripts/seed_data.py
    FLASK_ENV=development python scripts/seed_data.py
"""

import os
import sys

# Ensure the project root is on the Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    env = os.getenv("FLASK_ENV", "development")
    if env == "production":
        print("ERROR: seed_data.py must NOT be run in production.", file=sys.stderr)
        print("       Set FLASK_ENV=development or remove it.", file=sys.stderr)
        sys.exit(1)

    from app import create_app
    from app.extensions import db
    from app.models.user import Role, User
    from app.models.project import Project
    from app.models.cron_schedule import CronSchedule

    app = create_app(env)

    with app.app_context():
        # ------------------------------------------------------------------
        # 1. Admin user
        # ------------------------------------------------------------------
        admin = User.query.filter_by(username="admin").first()
        if admin is None:
            admin = User(
                username="admin",
                email="admin@qa-platform.local",
                role=Role.SUPER_ADMIN,
                is_active=True,
            )
            admin.set_password("admin123")
            db.session.add(admin)
            db.session.commit()
            print("[seed] Created admin user (admin / admin123)")
        else:
            print("[seed] Admin user already exists, skipping.")

        # ------------------------------------------------------------------
        # 2. Sample project
        # ------------------------------------------------------------------
        project = Project.query.filter_by(name="Sample QA Project").first()
        if project is None:
            project = Project(
                name="Sample QA Project",
                description="A sample project for demonstration and testing purposes.",
                git_url="https://github.com/example/qa-sample-tests.git",
                git_branch="main",
                owner_id=admin.id,
            )
            db.session.add(project)
            db.session.commit()
            print(f"[seed] Created sample project (id={project.id})")
        else:
            print(f"[seed] Sample project already exists (id={project.id}), skipping.")

        # ------------------------------------------------------------------
        # 3. Sample cron schedule (daily at 2:00 AM UTC)
        # ------------------------------------------------------------------
        existing_cron = CronSchedule.query.filter_by(
            project_id=project.id,
            cron_expr="0 2 * * *",
        ).first()
        if existing_cron is None:
            cron = CronSchedule(
                project_id=project.id,
                cron_expr="0 2 * * *",
                is_active=True,
            )
            db.session.add(cron)
            db.session.commit()
            print(f"[seed] Created daily cron schedule (id={cron.id}, cron='0 2 * * *')")
        else:
            print("[seed] Daily cron schedule already exists, skipping.")

        print("\n[seed] Seed data complete.")
        print("       Login with: admin / admin123")


if __name__ == "__main__":
    main()
