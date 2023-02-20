"""
This module defines a convenient function decorator, @cached, which can be used like this:

@cached(ignore_cache_if=lambda x: x % 2 == 0)
def foo(x):
    ...

Under the hood, this function uses the joblib.Memory class to cache the results of calls to foo() on disk. The
ignore_cache_if= argument to the decorator allows you to conditionally ignore the cache. This is useful for functions
that parse crawled web pages that are expected to be static on the server-side in certain cases.
"""
from typing import Callable

from joblib import Memory

import repo


memory = Memory(repo.joblib_cache(), verbose=0)


def cached(ignore_cache_if: Callable[..., bool] = lambda *args, **kwargs: False):
    def decorator(func):
        @memory.cache
        def func_cached(*args, **kwargs):
            return func(*args, **kwargs)

        def wrapper(*args, **kwargs):
            if ignore_cache_if(*args, **kwargs):
                return func(*args, **kwargs)
            return func_cached(*args, **kwargs)

        return wrapper

    return decorator
