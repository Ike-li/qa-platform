import os

import click
from flask.cli import with_appcontext

from app import create_app

app = create_app()


@app.cli.group()
def db_commands():
    """Database management commands."""
    pass


@db_commands.command("init")
@with_appcontext
def db_init():
    """Initialize the migrations repository."""
    from flask_migrate import init as migrate_init
    migrate_init()
    click.echo("Initialized the migrations repository.")


@db_commands.command("migrate")
@click.option("-m", "--message", default=None, help="Migration message.")
@with_appcontext
def db_migrate(message):
    """Create a new migration."""
    from flask_migrate import migrate as migrate_generate
    migrate_generate(message=message)
    click.echo("Generated a new migration.")


@db_commands.command("upgrade")
@click.option("--revision", default="head", help="Revision to upgrade to.")
@with_appcontext
def db_upgrade(revision):
    """Upgrade the database to a later revision."""
    from flask_migrate import upgrade as migrate_upgrade
    migrate_upgrade(revision=revision)
    click.echo(f"Database upgraded to {revision}.")


@db_commands.command("downgrade")
@click.option("--revision", default="-1", help="Revision to downgrade to.")
@with_appcontext
def db_downgrade(revision):
    """Downgrade the database to an earlier revision."""
    from flask_migrate import downgrade as migrate_downgrade
    migrate_downgrade(revision=revision)
    click.echo(f"Database downgraded to {revision}.")


@app.cli.command("create-admin")
@click.option("--username", prompt=True, help="Admin username.")
@click.option("--email", prompt=True, help="Admin email address.")
@click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True, help="Admin password.")
@with_appcontext
def create_admin(username, email, password):
    """Create an initial admin user."""
    click.echo("Admin creation is available after the User model is implemented (Phase 1).")
    click.echo(f"Received: username={username}, email={email}")


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=os.getenv("FLASK_DEBUG", "false").lower() == "true")
