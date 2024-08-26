""" Functionality for rendering templates in this directory.
"""

from typing import Dict, Any, List
from functools import cache
import importlib.resources
import logging
_logger = logging.getLogger(__name__)

import pystache # type: ignore

actions = ["submit", "job", "cancel"]

@cache
def _load(backend : str, act : str) -> pystache.parsed.ParsedTemplate:
    s = importlib.resources.read_text(__package__ + f'.{backend}',
                                      act, encoding='utf-8')
    return pystache.parse(s)

@cache
def _get() -> pystache.Renderer:
    """ Create the renderer for inserting data into templates.
    """
    partials : Dict[str, str] = {}
    for p in importlib.resources.files(__package__ \
                                    + '._partials').iterdir():
        if p.is_file() and p.name[-3:] != '.py':
            partials[p.name] = p.read_text(encoding='utf-8')

    return pystache.Renderer(
                partials = partials,
                escape = lambda x: x.replace("'", "''"),
                missing_tags = 'strict'
           )

def render(backend : str, act : str, data : Dict[str, Any]) -> str:
    #u = {"psik": psik_path()}
    #u.update(data)
    return _get().render(_load(backend, act), data)

def render_all(backend : str, actions : List[str],
               data : Dict[str, Any]) -> Dict[str, str]:
    # I, sir, render all.
    return dict((act, render(backend, act, data)) \
                      for act in actions)

def check(backend):
    for act in actions:
        try:
            _load(backend, act)
        except FileNotFoundError:
            raise KeyError(f"'{backend}' backed is missing a template for {act}.")

def list_backends() -> List[str]:
    backends = []
    for b in importlib.resources.files(__package__).iterdir():
        if b.is_dir() and str(b.name).count("_") == 0:
            try:
                check(b.name)
                backends.append(b.name)
            except Exception as e:
                _logger.error("list_backends: %s", e)
    return backends
