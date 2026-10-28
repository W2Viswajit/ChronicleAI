import json
import threading
from datetime import datetime, timezone
from email.utils import format_datetime

import httpx
import pytest

from backend.news_search import GdeltSearch, retry_seconds
from backend import retrieval
from backend.schemas import Article


class Clock:
    now = 1000.
    def __call__(self):
        return self.now
    def sleep(self, seconds):
        self.now += seconds


def error(code, retry=None):
    req = httpx.Request('GET', 'https://api.gdeltproject.org/api/v2/doc/doc')
    response = httpx.Response(code, request=req, headers={'Retry-After': retry} if retry else {})
    return httpx.HTTPStatusError('provider error', request=req, response=response)


@pytest.fixture
def client(tmp_path):
    clock = Clock()
    return GdeltSearch(tmp_path/'search.sqlite3', clock=clock, sleep=clock.sleep), clock


def test_two_topics_are_paced_and_repeat_is_cached(client):
    search, clock = client
    calls = []
    def fetch(url, params):
        assert params['maxrecords'] == 10 and params['sort'] == 'datedesc'
        calls.append((clock(), params['query']))
        return json.dumps({'articles':[{'url':'https://example.com/'+str(len(calls))}]}), url
    a = search.search('bengaluru metro', 7, fetch)
    b = search.search('india cricket', 7, fetch)
    repeat = search.search('bengaluru metro', 7, fetch)
    assert a.status == b.status == 'ok'
    assert len(calls) == 2 and calls[1][0] - calls[0][0] >= 6
    assert repeat.cached and repeat.requests == 0 and repeat.articles == a.articles


def test_retry_waits_for_server_then_recovers(client):
    search, clock = client
    times = []
    def fetch(url, params):
        times.append(clock())
        if len(times) == 1:
            raise error(429, '40')
        return '{"articles": []}', url
    result = search.search('metro', 7, fetch)
    assert result.status == 'ok' and result.requests == 2
    assert times[1] - times[0] >= 40
    assert search._state('failure_streak') == 0


def test_persistent_429_is_bounded_and_shared_across_topics(client):
    search, clock = client
    times = []
    def fetch(url, params):
        times.append(clock())
        raise error(429)
    result = search.search('metro', 7, fetch)
    assert result.status == 'rate_limited' and result.requests == 2
    assert result.retry_after == 60
    assert times == [1000, 1030]
    another = search.search('cricket', 7, fetch)
    assert another.status == 'rate_limited' and another.requests == 0
    # A new client after a server restart keeps the cooldown.
    restarted = GdeltSearch(search.db_path, clock=clock, sleep=clock.sleep)
    assert restarted.search('science', 7, fetch).requests == 0
    assert len(times) == 2


def test_long_retry_after_returns_without_sleeping(client):
    search, clock = client
    def fetch(url, params):
        raise error(429, '180')
    result = search.search('metro', 7, fetch)
    assert result.retry_after == 180 and result.requests == 1 and clock() == 1000


def test_retry_after_date_and_malformed_header():
    date = format_datetime(datetime.fromtimestamp(1090, timezone.utc), usegmt=True)
    assert retry_seconds(date, 1000) == 90
    for value in [None, 'bad', 'inf', 'NaN']:
        assert retry_seconds(value, 1000) == 30


def test_failures_are_not_cached_as_empty(client):
    search, clock = client
    responses = iter(['<html>Server busy</html>', '{"error":"bad query"}', '{"articles":[]}'])
    def fetch(url, params):
        return next(responses), url
    assert search.search('metro', 7, fetch).status == 'invalid_response'
    assert search.search('metro', 7, fetch).status == 'invalid_response'
    assert search.search('metro', 7, fetch).status == 'ok'
    assert search.search('metro', 7, fetch).cached


def test_cache_expiry(client):
    search, clock = client
    calls = []
    def fetch(url, params):
        calls.append(1)
        return '{"articles":[{"url":"https://example.com/news"}]}', url
    search.search('metro', 7, fetch)
    clock.sleep(899)
    assert search.search('metro', 7, fetch).cached
    clock.sleep(2)
    assert not search.search('metro', 7, fetch).cached
    assert len(calls) == 2


def test_cache_remains_usable_during_cooldown(client):
    search, _ = client
    search.search('metro', 7, lambda u, params: ('{"articles":[{"url":"https://example.com"}]}', u))
    def fail(url, params):
        raise error(429, '180')
    search.search('cricket', 7, fail)
    assert search.search('metro', 7, fail).cached


def test_concurrent_call_does_not_send_a_second_request(client):
    search, _ = client
    started, release = threading.Event(), threading.Event()
    def fetch(url, params):
        started.set()
        assert release.wait(5)
        return '{"articles":[]}', url
    thread = threading.Thread(target=lambda: search.search('metro', 7, fetch))
    thread.start()
    try:
        assert started.wait(5)
        assert search.search('cricket', 7, fetch).status == 'busy'
    finally:
        release.set()
        thread.join(5)


def test_provider_503_opens_cooldown_without_retry_storm(client):
    search, _ = client
    def fail(url, params):
        raise error(503, '120')
    first = search.search('metro', 7, fail)
    assert first.status == 'provider_unavailable' and first.requests == 1
    assert search.search('cricket', 7, fail).requests == 0


@pytest.fixture
def integration(client, monkeypatch):
    search, clock = client
    monkeypatch.setattr(retrieval, 'GDELT', search)
    monkeypatch.setenv('RSS_FEEDS', '')
    monkeypatch.setenv('NEWS_RSS_FALLBACK', '0')
    return search, clock


def test_rate_limited_search_does_not_claim_no_articles(integration, monkeypatch):
    def fail(url, params):
        raise error(429, '120')
    monkeypatch.setattr(retrieval, 'fetch', fail)
    result = retrieval.search('Bengaluru metro', 7, 10)
    assert result['search_status'] == 'rate_limited'
    assert result['retry_after_seconds'] == 120
    assert not any('No relevant accessible' in w or 'no matching links' in w for w in result['warnings'])


def test_successful_two_topic_extraction_and_alias_cache(integration, monkeypatch):
    _, clock = integration
    calls = []
    def fetch(url, params):
        calls.append(clock())
        topic = 'metro' if 'metro' in params['query'] else 'cricket'
        return json.dumps({'articles':[{'url':'https://example.com/'+topic}]}), url
    def extract(url):
        topic = 'Bangalore metro' if url.endswith('metro') else 'India cricket'
        return Article(title=topic+' latest report', text=(topic+' reporting on new developments. ')*5, url=url)
    monkeypatch.setattr(retrieval, 'fetch', fetch)
    monkeypatch.setattr(retrieval, 'extract', extract)
    assert len(retrieval.search('Bengaluru and metro', 7, 2)['articles']) == 1
    assert len(retrieval.search('India cricket', 7, 2)['articles']) == 1
    assert retrieval.search('metro Bangalore', 7, 10)['search_cached']
    assert len(calls) == 2 and calls[1] - calls[0] >= 6


def test_extraction_failure_is_distinct_from_empty_search(integration, monkeypatch):
    monkeypatch.setattr(retrieval, 'fetch', lambda u, params: ('{"articles":[{"url":"https://example.com"}]}',u))
    def fail(url):
        raise ValueError('Publisher blocked extraction')
    monkeypatch.setattr(retrieval, 'extract', fail)
    result = retrieval.search('metro', 7, 2)
    assert result['found'] == 1 and not result['articles']
    assert any('Candidate links were found' in w for w in result['warnings'])


def test_relevance_still_rejects_unrelated_articles():
    groups = retrieval.topic_groups('Bengaluru and metro')
    assert retrieval.relevant_article(Article(title='Bangalore metro update',text='BMRCL in Bengaluru. '*10), groups)
    assert not retrieval.relevant_article(Article(title='Delhi housing update',text='Apartment ownership report. '*10), groups)


@pytest.mark.parametrize('exception,phrase', [(httpx.ConnectTimeout, 'connecting to GDELT'),
                                            (httpx.ReadTimeout, 'waiting for GDELT response data')])
def test_timeout_diagnostics(client, exception, phrase):
    search, _ = client
    def fail(url, params):
        raise exception('timeout')
    result = search.search('india cricket', 7, fail)
    assert result.status == 'timeout' and result.requests == 1
    assert phrase in result.warnings[0]
    assert exception.__name__ in result.warnings[0]


def test_discovery_timeout_does_not_change_publisher_timeout(monkeypatch):
    settings = []
    class Client:
        def __init__(self, **kwargs):
            settings.append(kwargs)
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def stream(self, *args, **kwargs):
            raise httpx.ReadTimeout('fixture')
    monkeypatch.setattr(retrieval.httpx, 'Client', Client)
    monkeypatch.setattr(retrieval, 'validate_url', lambda u: u)
    for url in ['https://example.com/article']:
        with pytest.raises(httpx.ReadTimeout):
            retrieval.fetch(url)
    assert settings[0]['timeout'].read == 20 and settings[0]['timeout'].connect == 8


def test_stdlib_429_retains_retry_header(client, monkeypatch):
    import io
    import urllib.error
    from backend import news_search
    search, clock = client
    class Opener:
        def open(self, request, timeout):
            assert timeout == 60
            raise urllib.error.HTTPError(request.full_url, 429, 'Limited',
                                         {'Retry-After': '120'}, io.BytesIO(b'limited'))
    monkeypatch.setattr(news_search.urllib.request, 'build_opener', lambda *a: Opener())
    result = search.search('india cricket', 7, retrieval.fetch)
    assert result.status == 'rate_limited' and result.retry_after == 120
    assert result.requests == 1 and clock() == 1000


def test_stdlib_success_and_size_limit(monkeypatch):
    from backend import news_search
    class Response:
        body = b'{"articles":[]}'
        def __enter__(self):return self
        def __exit__(self, *a):return False
        def read(self, n):return self.body[:n]
        def geturl(self):return news_search.GDELT_URL
    class Opener:
        def open(self, request, timeout):
            assert 'query=india+cricket' in request.full_url
            return Response()
    monkeypatch.setattr(news_search.urllib.request, 'build_opener', lambda *a: Opener())
    raw, _ = retrieval.fetch(news_search.GDELT_URL, {'query':'india cricket'})
    assert json.loads(raw) == {'articles':[]}
    Response.body = b'x' * 3_000_001
    with pytest.raises(ValueError):news_search.fetch_gdelt({'query':'india cricket'})


def test_stdlib_does_not_follow_redirects():
    from backend.news_search import NoRedirect
    assert NoRedirect().redirect_request(None, None, 302, '', {}, 'http://127.0.0.1') is None


def test_stdlib_socket_timeout_is_reported(client, monkeypatch):
    from backend import news_search
    search, _ = client
    class Opener:
        def open(self, *a, **kw):raise TimeoutError('timed out')
    monkeypatch.setattr(news_search.urllib.request, 'build_opener', lambda *a: Opener())
    result = search.search('india cricket', 7, retrieval.fetch)
    assert result.status == 'timeout' and result.requests == 1


def test_timeout_cooldown_expires_and_allows_next_topic(client):
    search, clock = client
    def timeout(url, params):
        raise httpx.ReadTimeout('provider slow')
    first = search.search('claude', 7, timeout)
    assert first.retry_after == 30
    blocked = search.search('cricket', 7, timeout)
    assert blocked.requests == 0 and blocked.retry_after == 30
    clock.sleep(31)
    recovered = search.search('cricket', 7, lambda u, params: ('{"articles":[]}', u))
    assert recovered.status == 'ok' and recovered.requests == 1
