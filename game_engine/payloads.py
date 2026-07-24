from dataclasses import dataclass

from rules.rules_engine import MoveValidation


@dataclass(frozen=True)
class MoveValidationPayload:
    is_valid: bool
    reason: str

    @classmethod
    def from_move_validation(cls, validation: MoveValidation) -> "MoveValidationPayload":
        return cls(is_valid=validation.is_valid, reason=validation.reason)
