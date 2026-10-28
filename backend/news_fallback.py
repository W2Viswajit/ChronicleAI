"""Personal local news-reader fallback, with its own persistent pacing/cache."""
import json
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit, parse_qs
import xml.etree.ElementTree as ET

from .news_search import GdeltSearch, fetch_discovery

BING_RSS = 'https://www.bing.com/news/search'


def rss_articles(raw, days, now=None):
    now = now or datetime.now(timezone.utc)
    root = ET.fromstring(raw)
    if root.tag != 'rss' or root.find('channel') is None:
        raise ValueError('Expected a news RSS feed')
    rows = []
    for item in root.findall('./channel/item')[:30]:
        try:
            published = parsedate_to_datetime(item.findtext('pubDate', ''))
            if published.tzinfo is None:
                published = published.replace(tzinfo=timezone.utc)
            if not now - timedelta(days=days) <= published <= now:
                continue
        except (TypeError, ValueError, OverflowError):
            continue
        url = item.findtext('link', '')
        parsed = urlsplit(url)
        if parsed.hostname in ('bing.com', 'www.bing.com'):
            url = parse_qs(parsed.query).get('url', [''])[0]
        if urlsplit(url).scheme not in ('http', 'https'):
            continue
        rows.append({'url': url, 'title': item.findtext('title', ''),
                     'published': published.isoformat()})
    # Publisher pages are more likely to expose text than aggregator shells.
    rows.sort(key=lambda r: urlsplit(r['url']).hostname in ('msn.com', 'www.msn.com'))
    return rows


class NewsFallback(GdeltSearch):
    def cached_search(self, query, days):
        result = super().cached_search(query, days)
        if result is not None:
            result.warnings = [w.replace('GDELT', 'Bing News') for w in result.warnings]
        return result

    def search(self, query, days, fetcher=None):
        def fetch_rss(url, params):
            raw, final = fetch_discovery(BING_RSS, {'q': query, 'format': 'rss', 'setlang': 'en'})
            try:
                rows = rss_articles(raw, days)
            except ET.ParseError as exc:
                raise ValueError('Invalid RSS') from exc
            return json.dumps({'articles': rows}), final
        result = super().search(query, days, fetcher or fetch_rss)
        result.warnings = [w.replace('GDELT', 'Bing News') for w in result.warnings]
        return result
