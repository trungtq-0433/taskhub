"""Every `$ref` in the generated document has to resolve.

A schema handed to `responses` as a plain dict is embedded verbatim: FastAPI
does not register its nested models under `components/schemas` and does not
rewrite their refs. A `$ref` produced by `model_json_schema()` points at
`#/$defs/...`, which is the root of openapi.json once embedded, and there is no
`$defs` there. Nothing fails at runtime — the API answers correctly — but
Swagger UI refuses to render the page and shows "Could not resolve reference".

The failure is invisible from the application's own tests, which is why it is
worth asserting directly.
"""

from typing import Any

from app.main import app


def _refs(node: Any, path: str = "") -> list[tuple[str, str]]:
    """Every `$ref` in the document, with where it was found."""
    if isinstance(node, dict):
        found = []
        for key, value in node.items():
            if key == "$ref" and isinstance(value, str):
                found.append((path, value))
            else:
                found.extend(_refs(value, f"{path}/{key}"))
        return found
    if isinstance(node, list):
        return [ref for i, item in enumerate(node) for ref in _refs(item, f"{path}/{i}")]
    return []


def _resolve(document: dict[str, Any], ref: str) -> Any:
    """Follow a local JSON pointer, or return None if it leads nowhere."""
    if not ref.startswith("#/"):
        return None
    node: Any = document
    for token in ref.removeprefix("#/").split("/"):
        key = token.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    return node


def test_every_reference_in_the_document_resolves() -> None:
    document = app.openapi()
    refs = _refs(document)

    assert refs, "no $ref found at all — the document is not what this test thinks it is"

    dangling = [(path, ref) for path, ref in refs if _resolve(document, ref) is None]
    assert not dangling, "\n".join(f"{ref} referenced at {path}" for path, ref in dangling)
