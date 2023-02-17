import datetime
import os
import time
from typing import Optional

import requests
from urllib.parse import urlparse

import repo


def url_to_cached_file(url: str) -> str:
    url_components = urlparse(url)
    assert not url_components.params, url
    assert not url_components.fragment, url
    cached_file = os.path.join(repo.downloads(), url_components.netloc, url_components.path[1:])
    while cached_file.endswith('/'):
        cached_file = cached_file[:-1]

    if url_components.query:
        sanitized_query = url_components.query.replace('/', '_').replace('?', '_').replace('&', '_')
        cached_file += f'__{sanitized_query}'

    return cached_file


def check_cached_file(cached_file: str, force_refresh=False, stale_is_ok=False, stale_window_in_days=1) -> bool:
    """
    Returns true if the given path exists and is valid.
    """
    if force_refresh:
        return False
    if not os.path.exists(cached_file):
        return False
    if stale_is_ok:
        return True

    ts = os.path.getmtime(cached_file)
    dt = datetime.datetime.fromtimestamp(ts)
    today = datetime.date.today()
    return dt.date() > today - datetime.timedelta(days=stale_window_in_days)


def check_url(url: str, force_refresh=False, stale_is_ok=False, stale_window_in_days=1):
    """
    Returns true if there is a valid cached copy of the given url.
    """
    return check_cached_file(url_to_cached_file(url), force_refresh, stale_is_ok, stale_window_in_days)


def fetch(url: str, force_refresh=False, stale_is_ok=False, stale_window_in_days=1, verbose=True, pause_sec=1):
    """
    Fetches the text of the given url.

    By default, uses a cached copy of the file if it exists. If the write timestamp of the cached copy is stale, the
    cached copy is ignored, unless stale_is_ok=True. The definition of "stale" is controlled by stale_window_in_days.

    To force a refresh, set force_refresh=True.

    pause_sec is the number of seconds to pause between requests. This is to avoid hammering the server. Specifically,
    basketball-reference.com has a 20-requests-per-minute limit, a violation of which lands your session in jail for
    an hour (https://www.sports-reference.com/bot-traffic.html). The default of 1sec I'm using here technically violates
    that limit, but I'm hoping that the server will be lenient.
    """
    cached_file = url_to_cached_file(url)
    if check_cached_file(cached_file, force_refresh, stale_is_ok, stale_window_in_days):
        if verbose:
            print(f'Using cached copy of {url}')
        with open(cached_file, 'r') as f:
            return f.read()

    if verbose:
        print(f'Issuing request (after {pause_sec}sec pause): {url}')

    time.sleep(pause_sec)
    response = requests.get(url)
    response.raise_for_status()
    os.makedirs(os.path.dirname(cached_file), exist_ok=True)
    with open(cached_file, 'w') as f:
        f.write(response.text)

    return response.text
