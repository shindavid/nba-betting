import datetime
import os
import requests
from urllib.parse import urlparse

import repo


def fetch(url: str, force_refresh=False, stale_is_ok=False, verbose=True):
    """
    Fetches the text of the given url.

    By default, uses a cached copy of the file if it exists. If the write timestamp of the cached copy is from a
    previous day, the cache will be updated.

    To force a refresh, set force_refresh=True.

    If you are ok using a cached copy from a previous day, set stale_is_ok=True.
    """
    url_components = urlparse(url)
    assert not url_components.params, url
    assert not url_components.fragment, url
    cached_file = os.path.join(repo.downloads(), url_components.netloc, url_components.path[1:])
    while cached_file.endswith('/'):
        cached_file = cached_file[:-1]

    if url_components.query:
        sanitized_query = url_components.query.replace('/', '_').replace('?', '_').replace('&', '_')
        cached_file += f'__{sanitized_query}'

    if not force_refresh and os.path.exists(cached_file):
        ts = os.path.getmtime(cached_file)
        dt = datetime.datetime.fromtimestamp(ts)
        if stale_is_ok or dt.date() >= datetime.datetime.now().date():
            if verbose:
                print(f'Using cached copy of {url}')
            with open(cached_file, 'r') as f:
                return f.read()

    if verbose:
        print(f'Issuing request: {url}')
    response = requests.get(url)
    response.raise_for_status()
    os.makedirs(os.path.dirname(cached_file), exist_ok=True)
    with open(cached_file, 'w') as f:
        f.write(response.text)

    return response.text
