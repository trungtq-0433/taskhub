"""RFC 9457 Problem Details — the error representation for every endpoint.

One shape for every failure, standardised rather than invented here. The
registered members are `type`, `title`, `status`, `detail` and `instance`; the
spec permits extension members, which is where `errors` and `request_id` live.
"""

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
