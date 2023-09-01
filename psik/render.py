""" Functionality for rendering scripts.
"""

from typing import Dict, Any
from functools import cache
import importlib.resources

import pystache # type: ignore

@cache
def read_template(backend : str, act : str) -> pystache.parsed.ParsedTemplate:
    s = importlib.resources.read_text(__package__ + '.templates',
                                      f"{backend}-{act}", encoding='utf-8')
    return pystache.parse(s)

@cache
def get_renderer() -> pystache.Renderer:
    """ Create the renderer for inserting JobStat into
        scripts.
    """
    partials : Dict[str, str] = {}
    for p in importlib.resources.files(__package__ \
                                    + '.templates.partials').iterdir():
        if p.is_file() and p.name[-3:] != '.py':
            partials[p.name] = p.read_text(encoding='utf-8')
    print(partials)

    # note: can specify partials={'script': script},
    # note: alt. escape fn: "'" + x.replace("'", "''") + "'",
    return pystache.Renderer(
                partials = partials,
                escape = lambda x: x,
                missing_tags = 'strict'
           )

def render_template(template : str, data : Dict[str, Any]) -> str:
    r = get_renderer()
    return r.render(template, data)
