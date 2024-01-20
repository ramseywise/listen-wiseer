from datetime import datetime
from typing import Any, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, validator

from porto.exceptions import PortoExceptionError


class PortoSchemaExceptionError(PortoExceptionError):
    """Schema related exception."""


def validate_score(score: float) -> float:
    """Score validator to be used in the schemas.
    Validates a score in a range between 0 and 1.

    Args:
        score (float): score value

    Raises:
        ValueError: validation is not passed

    Returns:
        float: validated score
    """
    min_, max_ = 0.0, 1.0
    if score < min_ or score > max_:
        msg = "Score must in the range of [0, 1]"
        raise PortoSchemaExceptionError(msg)
    return score


class ModelInfo(BaseModel):
    """Model Information schema."""

    id: UUID = Field(default_factory=uuid4)
    version: str
    name: str
    is_application: bool
    meta: Optional[BaseModel]
    created: datetime
    updated: datetime

    class Config:
        """BaseModel config."""

        orm_mode = True

    _AVAILABLE_SCORE_NAMES: tuple[str] = ("overdraft",)

    @validator("name")
    def name_validation(cls, v: str) -> str:  # noqa: N805
        """Validate a model info name being one of supported names.

        Args:
            v (str): name

        Raises:
            ValueError: validation is not passed

        Returns:
            str: validated value
        """
        if v not in cls._AVAILABLE_SCORE_NAMES:
            msg = (
                f"Score name {v} is not in available. "
                f"Possible values: {cls._AVAILABLE_SCORE_NAMES}"
            )
            raise PortoSchemaExceptionError(msg)
        return v

    # TODO: version validation


class UserScore(BaseModel):
    """User score schema."""

    id: UUID = Field(default_factory=uuid4)
    user_id: UUID
    model_id: UUID
    rating_class: int
    pd: float
    tnc_country: str
    score_type: str
    is_valid: bool
    features: dict[str, Any]
    meta: BaseModel
    created: datetime
    updated: datetime

    class Config:
        """BaseModel config."""

        orm_mode = True

    @validator("rating_class")
    def rating_class_validation(cls, v: int) -> int:  # noqa: N805
        """Validate rating class being in a certain range.

        Args:
            v (int): rating class

        Raises:
            ValueError: validation is not passed

        Returns:
            int: validated rating class
        """
        min_, max_ = 1, 20
        if v < min_ or v > max_:
            msg = "Rating class must in the range of [1, 20]"
            raise PortoSchemaExceptionError(msg)
        return v

    _pd_validation = validator("pd", allow_reuse=True)(validate_score)
