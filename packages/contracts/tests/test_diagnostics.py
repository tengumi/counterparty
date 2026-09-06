"""A published warning is a typed diagnostic, not a free-form sentence."""

import pytest
from pydantic import ValidationError

from counterparty_contracts import (
    Availability,
    ContractWarning,
    FactValue,
    ValueType,
    WarningCode,
    unspecified_warning,
)


def test_warning_carries_code_message_and_pointer() -> None:
    """A warning names its category and the source field it is about."""
    warning = ContractWarning(
        code=WarningCode.PRECISION_REDUCED,
        message="registration date arrived as a timestamp and was truncated",
        source_path="/baseInfo/registrationInfo/registrationDate",
    )

    assert warning.model_dump(mode="json") == {
        "code": "precision_reduced",
        "message": "registration date arrived as a timestamp and was truncated",
        "source_path": "/baseInfo/registrationInfo/registrationDate",
    }


def test_warning_rejects_prose_instead_of_a_pointer() -> None:
    """``source_path`` stays resolvable rather than a human description."""
    with pytest.raises(ValidationError):
        ContractWarning(
            code=WarningCode.SOURCE_MISSING,
            message="the section is absent",
            source_path="baseInfo.registrationInfo",
        )


def test_warning_requires_a_message() -> None:
    """A code alone is not displayable, so the message stays mandatory."""
    with pytest.raises(ValidationError):
        ContractWarning(code=WarningCode.SOURCE_MISSING, message="")


def test_unknown_code_does_not_become_a_softer_one() -> None:
    """An unknown code is refused instead of collapsing into ``unspecified``."""
    with pytest.raises(ValidationError):
        ContractWarning.model_validate({"code": "made_up", "message": "note"})


def test_domain_sentence_is_wrapped_without_guessing_a_category() -> None:
    """A plain lower-layer note keeps its text and claims no category."""
    warning = unspecified_warning("both are kept as provided and are not added together")

    assert warning.code is WarningCode.UNSPECIFIED
    assert warning.source_path is None


def test_fact_warnings_are_typed() -> None:
    """A fact carries typed warnings, so a client can group or suppress them."""
    fact = FactValue(
        key="equity",
        label="Капитал",
        value="-300000",
        value_type=ValueType.DECIMAL,
        availability=Availability.AVAILABLE,
        evidence_refs=["ev-equity"],
        warnings=[
            ContractWarning(
                code=WarningCode.PERIOD_MISMATCH,
                message="2025 has no comparable earlier period",
            )
        ],
    )

    assert fact.warnings[0].code is WarningCode.PERIOD_MISMATCH
    with pytest.raises(ValidationError):
        FactValue.model_validate(
            {
                "key": "equity",
                "label": "Капитал",
                "value": "-300000",
                "value_type": ValueType.DECIMAL,
                "availability": Availability.AVAILABLE,
                "evidence_refs": ["ev-equity"],
                "warnings": ["a bare sentence"],
            }
        )
