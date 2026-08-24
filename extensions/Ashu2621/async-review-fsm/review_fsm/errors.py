from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ReviewTransitionError(Exception):
    code: str
    message: str

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"
