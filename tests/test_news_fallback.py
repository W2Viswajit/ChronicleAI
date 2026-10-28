from datetime import datetime, timezone
from backend import retrieval
from backend.news_fallback import rss_articles
from backend.news_search import SearchResult
from backend.schemas import Article


def test_feed_filters_dates_and_unwraps_publisher_urls():
    raw = '''<rss><channel>
      <item><title>Claude</title><link>https://www.bing.com/news/apiclick.aspx?url=https%3A%2F%2Fexample.com%2Fnews</link><pubDate>Tue, 27 Oct 2026 12:00:00 GMT</pubDate></item>
      <item><link>https://example.com/old</link><pubDate>Tue, 01 Sep 2026 12:00:00 GMT</pubDate></item>
      <item><link>https://example.com/undated</link></item>
      <item><link>https://example.com/future</link><pubDate>Thu, 29 Oct 2026 12:00:00 GMT</pubDate></item>
    </channel></rss>'''
    rows = rss_articles(raw, 7, datetime(2026, 10, 28, tzinfo=timezone.utc))
    assert len(rows) == 1 and rows[0]['url'] == 'https://example.com/news'


def test_fallback_recovers_and_repeat_does_not_call_primary(monkeypatch):
    monkeypatch.setenv('NEWS_RSS_FALLBACK', '1')
    monkeypatch.setenv('RSS_FEEDS', '')
    calls = []
    class Primary:
        def search(self, *args):
            calls.append('primary')
            return SearchResult(status='rate_limited', retry_after=120, requests=1)
    class Fallback:
        cached = None
        def cached_search(self, *args):
            return self.cached
        def search(self, *args):
            calls.append('fallback')
            rows = [{'url':'https://example.com/claude'}]
            self.cached = SearchResult(articles=rows, cached=True)
            return SearchResult(articles=rows, requests=1)
    monkeypatch.setattr(retrieval, 'GDELT', Primary())
    monkeypatch.setattr(retrieval, 'FALLBACK', Fallback())
    monkeypatch.setattr(retrieval, 'extract', lambda url: Article(title='Claude news', text='Claude reporting. '*20, url=url))
    first = retrieval.search('Claude', 7, 2)
    assert first['search_status'] == 'ok' and first['retry_after_seconds'] == 0
    assert first['search_provider'] == 'Bing News RSS' and first['provider_requests'] == 2
    assert len(first['articles']) == 1
    repeat = retrieval.search('Claude', 7, 2)
    assert repeat['search_cached'] and repeat['provider_requests'] == 0
    assert calls == ['primary', 'fallback']
