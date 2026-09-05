import asyncio
import inspect

import pytest


@pytest.hookimpl(tryfirst=True)
def pytest_pyfunc_call(pyfuncitem):
    """Let test functions be `async def` without pulling in pytest-asyncio:
    each async test gets its own fresh event loop via asyncio.run. This is
    what the server tier needs - handlers, GameSession and AsyncClock are
    the only async code in the project. (EventBus itself is synchronous and
    needs no loop at all.)"""
    test_func = pyfuncitem.obj
    if not inspect.iscoroutinefunction(test_func):
        return None
    argnames = pyfuncitem._fixtureinfo.argnames
    kwargs = {name: pyfuncitem.funcargs[name] for name in argnames}
    asyncio.run(test_func(**kwargs))
    return True
