"""
This module defines a convenient function decorator, @cached, which is an extension of the decorator
joblib.Memory.cache().

The key difference is that @cached allows you to specify a time-to-live for the cached results. For example, if you
want cached results for func() to only be valid for 1 hour, you can do:

@cached(expires_after_sec=3600)
def foo(x):
    ...

A None value for expires_after_sec means that the cached results are never invalidated. This is the default behavior.

The expires_after_sec kwarg can also be set to a function which takes the same arguments as the function being
decorated. In this case, the expiry time is determined by the return value of the function. Example:

@cached(expires_after_sec=lambda player: 24*60*60 if player.is_active() else None)
def get_data(player):
    ...

In the above example, the cached results are only valid for 1 day if the player is active, but are always valid if
the player is retired.
"""
import functools
import os
import time
import types
from typing import Callable, Optional, Union

from joblib import Memory
from joblib.memory import MemorizedFunc

import repo

SEC_PER_DAY = 24 * 60 * 60


def args_str(*args, **kwargs):
    tokens = list(map(str, args))
    tokens.extend(f'{k}={v}' for k, v in kwargs.items())
    return ', '.join(tokens)


def cached(f: Optional[Callable] = None, *, expires_after_sec: Union[float, None, Callable[..., float]] = None):
    class MyMemorizedFunc(MemorizedFunc):
        def __call__(self: MemorizedFunc, *args, **kwargs):
            out = self._cached_call(args, kwargs)
            metadata = out[-1]
            hit_cache = metadata is None
            func_id, args_id = self._get_output_identifiers(*args, **kwargs)
            path = [func_id, args_id]
            full_path = os.path.join(self.store_backend.location, *path)
            if hit_cache and expires_after_sec is not None:
                mtime = os.path.getmtime(full_path)
                now = time.time()

                sec = expires_after_sec(*args, **kwargs) if callable(expires_after_sec) else expires_after_sec
                expired = sec is not None and now - mtime > sec
                if expired:
                    out = self.call(*args, **kwargs)[0]

            return out[0]

    class MyMemory(Memory):
        def cache(self, func=None, ignore=None, verbose=None, mmap_mode=False):
            """ Decorates the given function func to only compute its return
                value for input arguments not cached on disk.

                Parameters
                ----------
                func: callable, optional
                    The function to be decorated
                ignore: list of strings
                    A list of arguments name to ignore in the hashing
                verbose: integer, optional
                    The verbosity mode of the function. By default that
                    of the memory object is used.
                mmap_mode: {None, 'r+', 'r', 'w+', 'c'}, optional
                    The memmapping mode used when loading from cache
                    numpy arrays. See numpy.load for the meaning of the
                    arguments. By default that of the memory object is used.

                Returns
                -------
                decorated_func: MemorizedFunc object
                    The returned object is a MemorizedFunc object, that is
                    callable (behaves like a function), but offers extra
                    methods for cache lookup and management. See the
                    documentation for :class:`joblib.memory.MemorizedFunc`.
            """
            if func is None:
                # Partial application, to be able to specify extra keyword
                # arguments in decorators
                return functools.partial(self.cache, ignore=ignore,
                                         verbose=verbose, mmap_mode=mmap_mode)

            assert self.store_backend is not None
            if verbose is None:
                verbose = self._verbose
            if mmap_mode is False:
                mmap_mode = self.mmap_mode
            if isinstance(func, MemorizedFunc):
                func = func.func
            return MyMemorizedFunc(func, location=self.store_backend,
                                   backend=self.backend,
                                   ignore=ignore, mmap_mode=mmap_mode,
                                   compress=self.compress,
                                   verbose=verbose, timestamp=self.timestamp)

    memory = MyMemory(repo.joblib_cache(), verbose=0)

    if f is not None:
        assert expires_after_sec is None
        return memory.cache(f)

    def decorator(func):
        return memory.cache(func)

    return decorator
