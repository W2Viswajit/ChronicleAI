"""Persistent GDELT cache and pacing for the single-process local server."""
from dataclasses import dataclass, field
from contextlib import contextmanager
from email.utils import parsedate_to_datetime
import hashlib
import json
import math
import sqlite3
import threading
import time
import urllib.request
import urllib.error
from urllib.parse import urlencode

import httpx

GDELT_URL = 'https://api.gdeltproject.org/api/v2/doc/doc'


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch_gdelt(params):
    return fetch_discovery(GDELT_URL, params, timeout=60)


def fetch_discovery(endpoint, params, timeout=25):
    """Fetch an internal provider endpoint with bounded size and verified TLS.

    Callers supply fixed provider endpoints, never user URLs. Refuse redirects
    and translate errors for the shared retry policy.
    """
    url = endpoint + '?' + urlencode(params or {})
    request = urllib.request.Request(url, headers={
        'User-Agent': 'ChronicleAI-academic-demo/1.0', 'Accept-Encoding': 'identity'})
    opener = urllib.request.build_opener(NoRedirect())
    try:
        with opener.open(request, timeout=timeout) as response:
            body = response.read(3_000_001)
            if len(body) > 3_000_000:
                raise ValueError('Response exceeds 3 MB limit.')
            return body.decode('utf-8', errors='replace'), response.geturl()
    except urllib.error.HTTPError as exc:
        # Preserve Retry-After, including HTTP dates. Never auto-retry here.
        req = httpx.Request('GET', url)
        response = httpx.Response(exc.code, headers=dict(exc.headers or {}), request=req)
        exc.close()
        raise httpx.HTTPStatusError('GDELT HTTP error', request=req, response=response) from exc
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, TimeoutError):
            raise httpx.TimeoutException('GDELT standard-client timeout') from exc
        raise httpx.ConnectError('GDELT standard-client connection failed') from exc
    except TimeoutError as exc:
        raise httpx.TimeoutException('GDELT standard-client timeout') from exc


@dataclass
class SearchResult:
    articles: list = field(default_factory=list)
    status: str = 'ok'
    warnings: list = field(default_factory=list)
    retry_after: int = 0
    cached: bool = False
    requests: int = 0


def retry_seconds(value, now, fallback=30):
    """Retry-After can be seconds or an HTTP date; never shorten it."""
    try:
        seconds = float(value)
        if not math.isfinite(seconds):
            raise ValueError('Nonfinite delay')
    except (TypeError, ValueError):
        try:
            seconds = parsedate_to_datetime(value).timestamp() - now
        except (TypeError, ValueError, OverflowError):
            seconds = fallback
    return max(6, math.ceil(seconds))


class GdeltSearch:
    def __init__(self, db_path, clock=time.time, sleep=time.sleep):
        self.db_path = str(db_path)
        self.clock, self.sleep = clock, sleep
        self.lock = threading.Lock()
        with self._db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS search_cache '
                       '(key TEXT PRIMARY KEY, expires REAL, payload TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS search_state '
                       '(key TEXT PRIMARY KEY, value REAL)')

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.db_path, timeout=5)
        try:
            with db:
                yield db
        finally:
            db.close()

    def _state(self, key):
        with self._db() as db:
            row = db.execute('SELECT value FROM search_state WHERE key=?', (key,)).fetchone()
        return row[0] if row else 0

    def _set_state(self, key, value):
        with self._db() as db:
            db.execute('INSERT OR REPLACE INTO search_state VALUES (?,?)', (key, value))

    def _cached(self, key):
        with self._db() as db:
            row = db.execute('SELECT payload FROM search_cache WHERE key=? AND expires>?',
                             (key, self.clock())).fetchone()
        if row:
            return SearchResult(articles=json.loads(row[0]), cached=True,
                                warnings=['Using cached GDELT results; no new search request was sent.'])

    def _store(self, key, rows):
        with self._db() as db:
            db.execute('DELETE FROM search_cache WHERE expires<=?', (self.clock(),))
            # Briefly cache true empty responses; never cache provider failures as empty results.
            db.execute('INSERT OR REPLACE INTO search_cache VALUES (?,?,?)',
                       (key, self.clock() + (900 if rows else 60), json.dumps(rows)))

    def _parameters(self, query, days):
        params = {'query': query + ' sourcelang:english', 'mode': 'artlist',
                  'format': 'json', 'maxrecords': 10, 'timespan': f'{days}d', 'sort': 'datedesc'}
        key = hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()
        return params, key

    def cached_search(self, query, days):
        return self._cached(self._parameters(query, days)[1])

    def search(self, query, days, fetcher):
        params, key = self._parameters(query, days)
        cached = self._cached(key)
        if cached is not None:
            return cached
        if not self.lock.acquire(blocking=False):
            return SearchResult(status='busy', retry_after=6, warnings=[
                'Another news search is running. Wait for it to finish before searching again.'])
        try:
            # A previous request may have filled the cache before we acquired the lock.
            cached = self._cached(key)
            if cached is not None:
                return cached
            remaining = math.ceil(self._state('cooldown_until') - self.clock())
            if remaining > 0:
                return self._cooldown(remaining, 0)
            requests = 0
            for attempt in range(2):
                spacing = max(0, self._state('next_request_at') - self.clock())
                if spacing:
                    self.sleep(spacing)
                self._set_state('next_request_at', self.clock() + 6)
                requests += 1
                try:
                    raw, _ = fetcher(GDELT_URL, params=params)
                    decoded = json.loads(raw)
                    if (not isinstance(decoded, dict) or 'articles' not in decoded
                            or not isinstance(decoded['articles'], list)):
                        raise ValueError('Unexpected GDELT response')
                    rows = [row for row in decoded['articles'] if isinstance(row, dict)][:30]
                    self._store(key, rows)
                    self._set_state('cooldown_until', 0)
                    self._set_state('failure_streak', 0)
                    warnings = (['GDELT recovered after one paced retry.'] if attempt else [])
                    return SearchResult(articles=rows, warnings=warnings, requests=requests)
                except httpx.HTTPStatusError as exc:
                    code = exc.response.status_code
                    if code in (429, 503):
                        streak = min(4, int(self._state('failure_streak')))
                        delay = retry_seconds(exc.response.headers.get('Retry-After'), self.clock(),
                                              fallback=min(300, 30 * 2 ** streak))
                        self._set_state('failure_streak', streak + 1)
                        self._set_state('cooldown_until', self.clock() + delay)
                        self._set_state('last_status', code)
                        # One automatic retry only. Long server delays return immediately.
                        if code == 429 and attempt == 0 and delay <= 45:
                            self.sleep(delay)
                            continue
                        return self._cooldown(delay, requests)
                    return SearchResult(status='provider_error', requests=requests, warnings=[
                        f'GDELT search failed (HTTP {code}). Search could not establish whether '
                        'matching articles exist. Try later or paste direct article URLs.'])
                except httpx.TimeoutException as exc:
                    # A timeout is a provider failure too: do not let repeated
                    # clicks or a different topic immediately hammer it again.
                    self._set_state('cooldown_until', self.clock() + 30)
                    self._set_state('last_status', 503)
                    phase = ('connecting to GDELT' if isinstance(exc, httpx.ConnectTimeout)
                             else 'waiting for GDELT response data' if isinstance(exc, httpx.ReadTimeout)
                             else 'communicating with GDELT')
                    return SearchResult(status='timeout', retry_after=30, requests=requests, warnings=[
                        f'GDELT search timed out while {phase} ({type(exc).__name__}). '
                        'Request: 10 candidates, date-descending; standard-client socket timeout 60s. '
                        'No conclusion about available articles could be made.'])
                except (json.JSONDecodeError, ValueError):
                    return SearchResult(status='invalid_response', requests=requests, warnings=[
                        'GDELT returned an invalid search response. This is not a zero-results response. '
                        'Try later or paste direct article URLs.'])
                except (httpx.RequestError, OSError):
                    return SearchResult(status='network_error', requests=requests, warnings=[
                        'Could not connect to GDELT. Check your connection or paste direct article URLs.'])
        finally:
            self.lock.release()

    def _cooldown(self, seconds, requests):
        limited = self._state('last_status') != 503
        problem = 'rate limited the search (HTTP 429)' if limited else 'is temporarily unavailable (HTTP 503)'
        return SearchResult(status='rate_limited' if limited else 'provider_unavailable',
                            retry_after=seconds, requests=requests, warnings=[
            f'GDELT {problem}. Automatic searches are paused for about {seconds} seconds. '
            'This does not mean your topic has no news. Use direct article URLs meanwhile.'])
