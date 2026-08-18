import pytest
from pydantic import BaseModel, Field

from tests.agents._schema_guard import assert_strict_schema_safe


class _SafeModel(BaseModel):
    name: str
    count: int


class _UnsafeModel(BaseModel):
    weight: float = Field(gt=0)


def test_assert_strict_schema_safe_passes_for_unconstrained_model():
    assert_strict_schema_safe(_SafeModel)


def test_assert_strict_schema_safe_fails_for_gt_constrained_model():
    with pytest.raises(AssertionError):
        assert_strict_schema_safe(_UnsafeModel)
