"""WTForms for the projects blueprint."""

from flask_wtf import FlaskForm
from wtforms import PasswordField, StringField, TextAreaField
from wtforms.validators import DataRequired, Length, Optional, URL


class ProjectForm(FlaskForm):
    """Create / edit a project."""

    name = StringField(
        "Project Name",
        validators=[
            DataRequired(message="Project name is required."),
            Length(max=120, message="Name must be 120 characters or fewer."),
        ],
    )
    git_url = StringField(
        "Git Repository URL",
        validators=[
            DataRequired(message="Git URL is required."),
            Length(max=512),
        ],
    )
    git_branch = StringField(
        "Branch",
        validators=[
            DataRequired(message="Branch is required."),
            Length(max=120),
        ],
        default="main",
    )
    description = TextAreaField(
        "Description",
        validators=[Optional(), Length(max=2000)],
    )
    git_credential = PasswordField(
        "Git Credential / Token",
        validators=[Optional()],
        description="Leave blank to keep current credential.",
    )
