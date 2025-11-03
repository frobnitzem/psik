""" Functionality for calling modules implemented
    in the backends/ directory.
"""

from typing import (
    Dict,
    Any,
    List,
    Union,
    Optional,
    Callable,
    get_args,
    get_origin
)
import pkgutil
import importlib
import inspect
from functools import cache
import logging
_logger = logging.getLogger(__name__)

from .models import JobState
import psik.backends

def compare_types(actual: Any, expected: Any) -> bool:
    """
    Compares simple and complex types, especially for Optional[T] and Union[T, None].
    """
    if actual is expected or actual == expected:
        return True

    actual_origin = get_origin(actual)
    expected_origin = get_origin(expected)

    actual_args = get_args(actual)
    expected_args = get_args(expected)

    # rewrite Optional[X] to Union[X, None]
    if actual_origin == Optional:
        actual_origin = Union
        actual_args = (actual_args[0], None)
    if expected_origin == Optional:
        expected_origin = Union
        expected_args = (expected_args[0], None)
    if actual_origin != expected_origin:
        return False

    if actual_origin == Union: # sort unions
        actual_args = tuple(sorted(actual_args, key=str))
        expected_args = tuple(sorted(expected_args, key=str))

    return all(compare_types(x,y) \
               for x, y in zip(actual_args, expected_args))

def check_function_signature(func: Callable[..., Any], expected_sig: List[Any]) -> Optional[str]:
    """
    Checks if a dynamically loaded function matches the target asynchronous signature.
    """
    if not inspect.iscoroutinefunction(func):
        return "is not asynchronous."

    try:
        sig = inspect.signature(func)
    except ValueError as e:
        return f"could not inspect signature: {e}"

    params = sig.parameters

    expected_arg_count = len(expected_sig) - 1 # Subtract 'return'
    if len(params) != expected_arg_count:
        return f"Expected {expected_arg_count} arguments, found {len(params)}."

    for i, ((name, actual), expected_type) in enumerate(zip(params.items(), expected_sig)):
        if not compare_types(actual.annotation, expected_type):
            return (
                f"Positional argument {i+1} (called '{name}') type mismatch. "
                f"Found {actual.annotation}, expected {expected_type}."
            )

    actual_return_type = sig.return_annotation
    expected_return_type = expected_sig[-1]
    if not compare_types(actual_return_type, expected_return_type):
        return f"Return type mismatch. Found {actual_return_type}, expected {expected_return_type}."

    return None

@cache
def _lookup(backend, name):
    """ Lookup a function from a backend.
    """
    mod = importlib.import_module(
                f".backends.{backend}", package="psik")
    return getattr(mod, name)

async def submit_at(backend: str, job, jobndx: int) -> Optional[str]: # type: ignore[name-defined]
    submit = _lookup(backend, "submit")
    return await submit(job, jobndx)

async def cancel_at(backend: str, jobids: List[str]) -> None:
    cancel = _lookup(backend, "cancel")
    await cancel(jobids)

async def poll_at(backend: str, job) -> None:
    poll = _lookup(backend, "poll")
    await poll(job)

def check(backend):
    try:
        submit = _lookup(backend, "submit")
        cancel = _lookup(backend, "cancel")
        poll = _lookup(backend, "poll")
    except Exception as e:
        raise ImportError(f"Unable to load backend module {backend}") from e
    err = check_function_signature(submit, ['Job', int, Optional[str]])
    if err:
        raise KeyError(f"{backend}.submit: {err}")
    err = check_function_signature(cancel, [List[str], None])
    if err:
        raise KeyError(f"{backend}.cancel: {err}")
    err = check_function_signature(poll, ['Job', None])
    if err:
        raise KeyError(f"{backend}.poll: {err}")

def list_backends() -> List[str]:
    backends = []
    import psik
    for importer, modname, ispkg in pkgutil.iter_modules(psik.backends.__path__):
        check(modname)
        backends.append(modname)
    return backends
