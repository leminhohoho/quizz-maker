"""Verdicts shared by checkers, the step pipeline, the agent grader and the web UI."""

from dataclasses import asdict, dataclass

PASSING = {"pass", "pass_numeric", "agent_pass"}
FAILING = {"fail", "agent_fail", "parse_error"}
STATUSES = PASSING | FAILING | {"undecided", "unverified"}


@dataclass
class Verdict:
    status: str
    reason: str = ""
    counterexample: dict[str, str] | None = None

    def __post_init__(self):
        if self.status not in STATUSES:
            raise ValueError(f"unknown verdict status {self.status!r}")

    @property
    def passed(self) -> bool:
        return self.status in PASSING

    @property
    def failed(self) -> bool:
        return self.status in FAILING

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v not in (None, "")}

    @classmethod
    def from_dict(cls, data: dict) -> "Verdict":
        return cls(data["status"], data.get("reason", ""), data.get("counterexample"))
