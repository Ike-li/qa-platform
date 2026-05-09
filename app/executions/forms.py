"""WTForms for the executions blueprint."""

from flask_wtf import FlaskForm
from wtforms import SelectField, TextAreaField
from wtforms.validators import Optional


class ExecutionTriggerForm(FlaskForm):
    """Form for triggering a new test execution."""

    suite_id = SelectField(
        "Test Suite",
        coerce=int,
        validators=[Optional()],
        description="Select a suite to execute (leave empty to run all suites).",
    )
    extra_args = TextAreaField(
        "Extra Pytest Arguments",
        validators=[Optional()],
        description="Additional CLI arguments passed to pytest, e.g. -k 'smoke' --timeout=60.",
    )
