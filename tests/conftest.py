import asyncio
import inspect

import pytest


@pytest.hookimpl(tryfirst=True)
def pytest_pyfunc_call(pyfuncitem):
    """Let test functions be `async def` without pulling in pytest-asyncio:
    each async test gets its own fresh event loop via asyncio.run, which is
    exactly what EventBus (asyncio.Queue-backed) needs to be constructed
    and subscribed to."""
    test_func = pyfuncitem.obj
    if not inspect.iscoroutinefunction(test_func):
        return None
    argnames = pyfuncitem._fixtureinfo.argnames
    kwargs = {name: pyfuncitem.funcargs[name] for name in argnames}
    asyncio.run(test_func(**kwargs))
    return True
