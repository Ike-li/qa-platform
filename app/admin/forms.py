"""WTForms for the admin blueprint."""

from flask_wtf import FlaskForm
from wtforms import BooleanField, EmailField, PasswordField, SelectField, StringField
from wtforms.validators import DataRequired, Email, Length, Optional

from app.models.user import Role


class UserAdminForm(FlaskForm):
    """Create / edit a user (admin only)."""

    username = StringField(
        "Username",
        validators=[DataRequired(), Length(min=3, max=80)],
    )
    email = EmailField(
        "Email",
        validators=[DataRequired(), Email(message="Enter a valid email address.")],
    )
    role = SelectField(
        "Role",
        choices=[(r.value, r.value.replace("_", " ").title()) for r in Role],
        validators=[DataRequired()],
    )
    password = PasswordField(
        "Password",
        validators=[Optional(), Length(min=8, message="Password must be at least 8 characters.")],
    )
    is_active = BooleanField("Active", default=True)


class SystemConfigForm(FlaskForm):
    """Dynamic form for editing system configuration.

    Fields are populated at runtime from SystemConfig.query.all().
    Because the set of keys is dynamic we don't declare static field
    attributes; instead the template renders raw ``<input>`` elements
    keyed by config key.  This class only exists to provide CSRF
    protection via Flask-WTF.
    """

    pass
