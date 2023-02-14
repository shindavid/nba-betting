import os


def root() -> str:
    """Return the root directory of the repository."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def downloads() -> str:
    """Return the downloads directory of the repository."""
    return os.path.join(root(), 'downloads')


def joblib_cache() -> str:
    """Return the joblib cache directory of the repository."""
    return os.path.join(root(), 'joblib_cache')
