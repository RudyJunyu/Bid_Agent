from dataclasses import dataclass


@dataclass(frozen=True)
class Principal:
    id: str
    username: str
    is_admin: bool
