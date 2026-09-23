"""RFC 9457 Problem Details — the error representation for every endpoint.

One shape for every failure, standardised rather than invented here. The
registered members are `type`, `title`, `status`, `detail` and `instance`; the
spec permits extension members, which is where `errors` and `request_id` live.
"""

from typing import Any

from pydantic import BaseModel, Field

PROBLEM_MEDIA_TYPE = "application/problem+json"

# A URN rather than an https:// URL: the spec encourages a dereferenceable URI,
# but there is no documentation site to point at yet, and a URL that 404s is
# worse than an honest identifier. Swap the scheme once docs are published —
# the suffix is what clients branch on and it stays stable either way.
PROBLEM_TYPE_PREFIX = "urn:taskhub:problem:"


def problem_type_uri(slug: str) -> str:
    """Full `type` URI for a problem slug, e.g. `urn:taskhub:problem:not-found`."""
    return f"{PROBLEM_TYPE_PREFIX}{slug}"


class InvalidField(BaseModel):
    """One field-level cause, carried in the `errors` extension member."""

    field: str | None = Field(default=None, description="Dotted path to the offending field")
    message: str
    type: str | None = Field(default=None, description="Machine-readable cause")


class ProblemDetail(BaseModel):
    """The body returned with `application/problem+json`."""

    type: str = Field(
        default="about:blank",
        description="Stable identifier for the problem kind — the field clients branch on",
    )
    title: str = Field(description="Short, human-readable summary of the problem kind")
    status: int = Field(description="HTTP status code, repeated for clients that lose it")
    detail: str | None = Field(
        default=None, description="Human-readable explanation of this specific occurrence"
    )
    instance: str | None = Field(
        default=None, description="Path of the request that produced this problem"
    )

    # Extension members permitted by RFC 9457 §3.2.
    errors: list[InvalidField] | None = Field(
        default=None, description="Field-level causes, when the problem has any"
    )
    request_id: str | None = Field(
        default=None, description="Correlation id, echoed in the X-Request-ID header"
    )


def _inline_defs(schema: dict[str, Any]) -> dict[str, Any]:
    """Substitute a model's local `$defs` into the schema body.

    `model_json_schema()` hoists a nested model into a `$defs` section and
    points at it with `$ref: "#/$defs/InvalidField"`. The leading `#` means the
    root of the *document*, which is this schema only while it stands alone.
    Embedded in openapi.json it becomes the root of that file, where no `$defs`
    exists, and Swagger UI reports "Could not resolve reference".

    FastAPI's own models escape this because it registers them under
    `components/schemas` and rewrites the refs to match. A schema handed to
    `responses` as a plain dict gets neither, so the definition is substituted
    here instead and the result stands on its own.

    Substituting rather than rewriting would not terminate on a self-referencing
    model. None of the problem models refer to themselves, and one that did
    could not be inlined at all.
    """
    defs = schema.pop("$defs", {})

    def resolve(node: Any) -> Any:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/$defs/"):
                return resolve(defs[ref.removeprefix("#/$defs/")])
            return {key: resolve(value) for key, value in node.items()}
        if isinstance(node, list):
            return [resolve(item) for item in node]
        return node

    # Mapped over the members rather than passed whole: the top-level schema of
    # a model is an object, never a bare `$ref`, and this keeps the return typed.
    return {key: resolve(value) for key, value in schema.items()}


PROBLEM_SCHEMA = _inline_defs(ProblemDetail.model_json_schema())
"""The problem document as OpenAPI, self-contained — see `_inline_defs`."""
