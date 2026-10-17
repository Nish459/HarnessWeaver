import pytest
from pydantic import BaseModel, ValidationError

from harnessweaver import errors


def test_error_info_carries_code_type_and_details() -> None:
    error = errors.LockViolation("observability.capture_content is locked", path="observability")
    info = error.to_info()
    assert info.code is errors.ErrorCode.SPEC_INVALID
    assert info.type == "LockViolation"
    assert info.details == {"path": "observability"}
    assert info.retryable is False
    assert errors.ProviderError("upstream 503").to_info().retryable is True


def test_taxonomy_hierarchy() -> None:
    assert issubclass(errors.LockViolation, errors.SpecError)
    assert issubclass(errors.ExpressionSyntaxError, errors.ExpressionError)
    assert issubclass(errors.SpecError, errors.HarnessError)


def test_from_known_translates_timeouts_and_validation_errors() -> None:
    assert isinstance(errors.from_known(TimeoutError()), errors.DeadlineExceeded)

    class Model(BaseModel):
        n: int

    with pytest.raises(ValidationError) as caught:
        Model.model_validate({"n": "secret-value"})
    translated = errors.from_known(caught.value)
    assert isinstance(translated, errors.ValidationFailed)
    # R9: the offending value must not leak into the error.
    assert "secret-value" not in str(translated.to_info().model_dump())

    original = errors.ToolError("boom")
    assert errors.from_known(original) is original
    assert errors.from_known(KeyError("x")) is None


def test_classify_falls_back_to_internal_without_the_message() -> None:
    classified = errors.classify(KeyError("raw prompt text"))
    assert isinstance(classified, errors.InternalError)
    assert "raw prompt text" not in classified.message
