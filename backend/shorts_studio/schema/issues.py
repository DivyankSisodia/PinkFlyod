from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Issue:
    """A problem found in a project. ``error`` blocks saving or rendering (see where it is raised);
    ``warning`` is shown to the user and never blocks."""
    code: str
    message: str
    severity: str = "error"          # error | warning
    path: str = ""                   # JSON pointer-ish location, e.g. /scenes/0/layers/primary
    scene_id: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def errors_only(issues: list[Issue]) -> list[Issue]:
    return [i for i in issues if i.severity == "error"]
