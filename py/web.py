import datetime
import os
import requests
from urllib.parse import urlparse

import repo


def fetch(url: str, force_refresh=False):
    """
    Fetches the text of the given url.

    By default, uses a cached copy of the file if it exists. If the write timestamp of the cached copy is from a
    previous day, the cache will be updated.

    To force a refresh, set force_refresh=True.
    """
    url_components = urlparse(url)
    assert not url_components.params, url
    assert not url_components.query, url
    assert not url_components.fragment, url
    cached_file = os.path.join(repo.downloads(), url_components.netloc, url_components.path[1:])

    if not force_refresh and os.path.exists(cached_file):
        ts = os.path.getmtime(cached_file)
        dt = datetime.datetime.fromtimestamp(ts)
        if dt.date() >= datetime.datetime.now().date():
            print(f'Using cached copy of {url}')
            with open(cached_file, 'r') as f:
                return f.read()

    print(f'Issuing request: {url}')
    response = requests.get(url)
    response.raise_for_status()
    os.makedirs(os.path.dirname(cached_file), exist_ok=True)
    with open(cached_file, 'w') as f:
        f.write(response.text)

    return response.text
