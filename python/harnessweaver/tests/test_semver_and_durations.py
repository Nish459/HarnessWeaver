from datetime import timedelta

import pytest
from pydantic import BaseModel, ValidationError

from harnessweaver import Duration
from harnessweaver.core.durations import duration_ms
from harnessweaver.core.semver import Version, VersionRange


def test_max_satisfying_picks_the_highest_match() -> None:
    versions = [Version.parse(v) for v in ["1.0.0", "2.1.0", "2.3.1", "3.0.0-rc.1", "3.0.0"]]
    assert VersionRange.parse("^2").max_satisfying(versions) == Version.parse("2.3.1")
    assert VersionRange.parse("^4").max_satisfying(versions) is None


def test_range_membership_operator() -> None:
    assert "1.4.0" in VersionRange.parse(">=1.0,<2")
    assert Version(2, 0, 0) not in VersionRange.parse(">=1.0,<2")
    assert 3 not in VersionRange.parse("*")
    assert str(VersionRange.parse(" ^1.2 ")) == "^1.2"


def test_duration_type_in_a_model() -> None:
    class Settings(BaseModel):
        timeout: Duration

    settings = Settings.model_validate({"timeout": "1h30m"})
    assert settings.timeout == timedelta(hours=1, minutes=30)
    assert settings.model_dump(mode="json") == {"timeout": "1h30m"}
    with pytest.raises(ValidationError):
        Settings.model_validate({"timeout": "soon"})


def test_duration_ms_rejects_sub_millisecond_and_negative_values() -> None:
    with pytest.raises(ValueError, match="sub-millisecond"):
        duration_ms(timedelta(microseconds=1500))
    with pytest.raises(ValueError, match="negative"):
        duration_ms(timedelta(seconds=-1))
