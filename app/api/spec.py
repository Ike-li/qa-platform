"""OpenAPI / Swagger UI configuration via flask-smorest."""

from flask_smorest import Api

from app.api import api_bp


def init_spec(app):
    """Register the ApiSpec with the Flask app and enable Swagger UI.

    Swagger UI is served at ``/api/docs``.
    """
    api = Api(app, spec_kwargs={
        "title": "QA Platform API",
        "version": "1.0",
        "openapi_version": "3.0.3",
    })
    api.register_blueprint(api_bp)
    return api
