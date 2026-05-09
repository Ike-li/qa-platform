"""WTForms for the authentication blueprint."""

from flask_wtf import FlaskForm
from wtforms import BooleanField, PasswordField, StringField
from wtforms.validators import DataRequired, Email, EqualTo, Length, Optional


class LoginForm(FlaskForm):
    """Login form."""

    username = StringField(
        "Username",
        validators=[DataRequired(message="Username is required.")],
    )
    password = PasswordField(
        "Password",
        validators=[DataRequired(message="Password is required.")],
    )
    remember_me = BooleanField("Remember me")


class ProfileForm(FlaskForm):
    """Profile / password-change form."""

    email = StringField(
        "Email",
        validators=[DataRequired(), Email(message="Enter a valid email address.")],
    )
    current_password = PasswordField(
        "Current password",
        validators=[Optional()],
    )
    new_password = PasswordField(
        "New password",
        validators=[
            Optional(),
            Length(min=8, message="Password must be at least 8 characters."),
        ],
    )
    confirm_password = PasswordField(
        "Confirm new password",
        validators=[
            EqualTo("new_password", message="Passwords must match."),
        ],
    )
