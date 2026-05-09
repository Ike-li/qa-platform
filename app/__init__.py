import os

from flask import Flask, jsonify, redirect, render_template, request, url_for

from config import config_by_name
from app.extensions import csrf, db, login_manager, mail, migrate, socketio


def create_app(config_name=None):
    """Application factory for the QA platform."""

    if config_name is None:
        config_name = os.getenv("FLASK_ENV", "development")

    app = Flask(__name__)
    app.config.from_object(config_by_name[config_name])

    # Initialize extensions
    db.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)
    mail.init_app(app)
    socketio.init_app(app, async_mode="threading", message_queue=app.config.get("SOCKETIO_MESSAGE_QUEUE"))
    csrf.exempt("/socketio/")

    # Configure Flask-Login
    _configure_login(app)

    # Configure Celery
    _configure_celery(app)

    # Register blueprints
    _register_blueprints(app)

    # Register OpenAPI / Swagger UI (flask-smorest)
    from app.api.spec import init_spec
    init_spec(app)

    # Register error handlers
    _register_error_handlers(app)

    # Root route: redirect to dashboard (or login)
    @app.route("/")
    def index():
        from flask_login import current_user
        if current_user.is_authenticated:
            return redirect(url_for("dashboard.index"))
        return redirect(url_for("auth.login"))

    # Health check endpoint
    @app.route("/health")
    def health():
        return jsonify({"status": "ok"}), 200

    return app


def _configure_celery(app):
    """Bind Celery to the Flask app config."""
    from app.extensions import celery

    celery.conf.update(
        broker_url=app.config["CELERY_BROKER_URL"],
        result_backend=app.config["CELERY_RESULT_BACKEND"],
        accept_content=app.config.get("CELERY_ACCEPT_CONTENT", ["json"]),
        task_serializer=app.config.get("CELERY_TASK_SERIALIZER", "json"),
        result_serializer=app.config.get("CELERY_RESULT_SERIALIZER", "json"),
        timezone=app.config.get("CELERY_TIMEZONE", "UTC"),
        enable_utc=app.config.get("CELERY_ENABLE_UTC", True),
    )

    class FlaskTask(celery.Task):
        """Celery Task that runs within the Flask application context."""

        def __call__(self, *args, **kwargs):
            with app.app_context():
                return self.run(*args, **kwargs)

    celery.Task = FlaskTask
    celery.autodiscover_tasks(["app.tasks"])


def _configure_login(app):
    """Configure Flask-Login callbacks and user loader."""
    from app.models.user import User

    login_manager.login_view = "auth.login"
    login_manager.login_message = "Please log in to access this page."
    login_manager.login_message_category = "warning"

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))


def _register_blueprints(app):
    """Register all application blueprints."""
    from app.auth import auth_bp
    from app.admin import admin_bp
    from app.projects import projects_bp
    from app.executions import executions_bp
    from app.dashboard import dashboard_bp
    from app.notifications import notifications_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(projects_bp)
    app.register_blueprint(executions_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(notifications_bp)
    # api_bp is registered via flask-smorest in init_spec()


def _is_browser_request():
    """Return True if the request Accept header indicates a browser."""
    accept = request.headers.get("Accept", "")
    return "text/html" in accept


def _register_error_handlers(app):
    """Register HTTP error handlers.

    Browser requests receive rendered HTML templates.
    API / non-browser requests receive JSON.
    """

    @app.errorhandler(403)
    def forbidden(error):
        if _is_browser_request():
            return render_template("errors/403.html"), 403
        return jsonify({"error": "Forbidden", "message": "You do not have permission to access this resource."}), 403

    @app.errorhandler(404)
    def not_found(error):
        if _is_browser_request():
            return render_template("errors/404.html"), 404
        return jsonify({"error": "Not Found", "message": "The requested resource was not found."}), 404

    @app.errorhandler(500)
    def internal_error(error):
        db.session.rollback()
        if _is_browser_request():
            return render_template("errors/404.html"), 500  # reuse generic template
        return jsonify({"error": "Internal Server Error", "message": "An unexpected error has occurred."}), 500
