"""Quiz package format v1. These models are the format; `json_schema()` is generated from them."""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, PositiveInt, StringConstraints, field_validator, model_validator

from quizz.checkers import REGISTRY

Slug = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CheckSpec(Model):
    checker: str
    params: dict[str, Any] = Field(default_factory=dict)

    @field_validator("checker")
    @classmethod
    def _known(cls, name: str) -> str:
        if name not in REGISTRY:
            raise ValueError(f"unknown checker {name!r}; available: {', '.join(REGISTRY)}")
        return name


class Choice(Model):
    id: Slug
    text: str = Field(min_length=1)


class QuestionBase(Model):
    id: Slug
    prompt: str = Field(min_length=1, description="Markdown with $...$ LaTeX and ![](assets/...) images")
    source_slides: list[PositiveInt] = Field(default_factory=list, description="1-based pages of the ingested PDF")
    explanation: str = ""
    points: PositiveInt = 1


class MCQ(QuestionBase):
    type: Literal["mcq"]
    choices: list[Choice] = Field(min_length=2, max_length=6)
    answer: Slug


class MultiSelect(QuestionBase):
    type: Literal["multi_select"]
    choices: list[Choice] = Field(min_length=2, max_length=8)
    answer: list[Slug] = Field(min_length=1)
    scoring: Literal["all_or_nothing", "partial"] = "all_or_nothing"


class Blank(Model):
    accept: list[str] = Field(min_length=1)
    match: Literal["normalized", "exact", "regex"] = "normalized"


class FillBlank(QuestionBase):
    type: Literal["fill_blank"]
    blanks: dict[str, Blank] = Field(min_length=1, description="keys match {{key}} placeholders in the prompt")


class MathAnswer(QuestionBase):
    type: Literal["math_answer"]
    check: CheckSpec


class SymbolDecl(Model):
    assumptions: list[Literal["real", "positive", "nonnegative", "integer"]] = Field(default_factory=list)
    unit: str | None = None
    description: str = ""


class Given(Model):
    value: float
    unit: str = ""


class Context(Model):
    symbols: dict[str, SymbolDecl] = Field(default_factory=dict, description="keys are LaTeX names, e.g. q or \\Delta H")
    givens: dict[str, Given] = Field(default_factory=dict)
    relations: list[str] = Field(default_factory=list, description="governing equations in LaTeX, e.g. F=ma")
    functions: dict[str, Literal["heaviside", "dirac"]] = Field(
        default_factory=dict, description="names written f(t) that are function calls, e.g. u -> heaviside"
    )


class RefStep(Model):
    latex: str = Field(min_length=1)
    justification: str = ""
    agent_graded: bool = False


class Exercise(QuestionBase):
    type: Literal["exercise"]
    context: Context = Field(default_factory=Context)
    steps_mode: Literal["chain", "derivation"]
    start: str | None = None
    final: CheckSpec
    reference_solution: list[RefStep] = Field(min_length=1)
    rubric: str = ""

    @model_validator(mode="after")
    def _chain_needs_start(self):
        if self.steps_mode == "chain" and not self.start:
            raise ValueError("chain exercises need `start`, the expression line 0 is compared against")
        return self


Question = Annotated[MCQ | MultiSelect | FillBlank | MathAnswer | Exercise, Field(discriminator="type")]
QUESTION_TYPES: dict[str, type[QuestionBase]] = {
    "mcq": MCQ, "multi_select": MultiSelect, "fill_blank": FillBlank, "math_answer": MathAnswer, "exercise": Exercise,
}  # fmt: skip


class Source(Model):
    filename: str
    sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class Package(Model):
    format_version: Literal[1]
    id: Slug
    title: str = Field(min_length=1)
    course: str = Field(min_length=1)
    source: Source
    questions: list[Question] = Field(min_length=1)


def json_schema(question_type: str | None = None) -> dict:
    if question_type is None:
        return Package.model_json_schema()
    if question_type not in QUESTION_TYPES:
        raise ValueError(f"unknown question type {question_type!r}; available: {', '.join(QUESTION_TYPES)}")
    return QUESTION_TYPES[question_type].model_json_schema()
