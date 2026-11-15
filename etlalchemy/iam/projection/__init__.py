"""IAM read model: view interface, SQLAlchemy implementation and projection."""

from etlalchemy.iam.projection.projection import (
    IamEventApplication,
    IamProjection,
    IamProjectionError,
    run_iam_projection,
)
from etlalchemy.iam.projection.sqlalchemy import SQLAlchemyIamView
from etlalchemy.iam.projection.view import IamView

__all__ = [
    "IamEventApplication",
    "IamProjection",
    "IamProjectionError",
    "IamView",
    "SQLAlchemyIamView",
    "run_iam_projection",
]
