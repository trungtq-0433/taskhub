"""Email templates: one Jinja2 environment for every message the app sends.

Templates live in `templates/` next to this module. A `.txt` template is not
escaped (an `&` must reach the reader as `&`); an `.html` one, should one be
added, is escaped by `select_autoescape`.

User text goes in as a template variable, never as template source, so a
comment holding `{{ ... }}` is printed, not run. A variable the template names
but the caller does not pass is an error (`StrictUndefined`), not an empty
string.
"""

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, Template, select_autoescape

_environment = Environment(
    loader=FileSystemLoader(Path(__file__).with_name("templates")),
    autoescape=select_autoescape(),
    undefined=StrictUndefined,
)


def load_template(name: str) -> Template:
    """Load and compile `templates/<name>`.

    Called at import time, so a missing or broken template stops the app from
    starting instead of failing the request that would have sent it.
    """
    return _environment.get_template(name)
