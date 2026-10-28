"""Bounded, public-URL-only retrieval for the local demo (not a public proxy)."""
import ipaddress
import socket
import hashlib
import json
import os
import re
import xml.etree.ElementTree as ET
from urllib.parse import urlsplit, urljoin
from datetime import datetime, timezone
import httpx
from .config import RUNTIME
from .schemas import Article
from .news_search import GdeltSearch, GDELT_URL, fetch_gdelt
from .news_fallback import NewsFallback
CACHE = RUNTIME / 'article-cache'
CACHE.mkdir(exist_ok=True)
GDELT = GdeltSearch(RUNTIME / 'news-search.sqlite3')
FALLBACK = NewsFallback(RUNTIME / 'news-fallback.sqlite3')

def validate_url(url):
    p = urlsplit(url)
    if p.scheme not in ('http','https') or not p.hostname or p.username or p.password:
        raise ValueError('Only public HTTP(S) article URLs are supported.')
    if p.port not in (None,80,443):
        raise ValueError('Non-standard URL ports are not supported.')
    hosts = socket.getaddrinfo(p.hostname, p.port or (443 if p.scheme == 'https' else 80), type=socket.SOCK_STREAM)
    if not hosts or any(not ipaddress.ip_address(x[4][0]).is_global for x in hosts):
        raise ValueError('Local and private network addresses are not allowed.')
    return url

def fetch(url, params=None):
    if url == GDELT_URL:
        return fetch_gdelt(params)
    # Revalidate each redirect; body size and decompressed bytes are bounded.
    # Discovery can take longer than downloading an individual publisher page.
    timeout = httpx.Timeout(20, connect=8)
    with httpx.Client(timeout=timeout, follow_redirects=False, trust_env=False,
                      headers={'User-Agent':'ChronicleAI-academic-demo/1.0'}) as client:
        for _ in range(5):
            validate_url(url)
            with client.stream('GET',url,params=params) as r:
                if r.is_redirect:
                    url = urljoin(url, r.headers['location']); params = None; continue
                r.raise_for_status()
                data = bytearray()
                for block in r.iter_bytes():
                    data.extend(block)
                    if len(data)>3_000_000: raise ValueError('Response exceeds 3 MB limit.')
                return bytes(data).decode(r.encoding or 'utf-8', errors='replace'), str(r.url)
    raise ValueError('Too many redirects.')

def extract(url):
    validate_url(url)
    key = hashlib.sha256(url.encode()).hexdigest()
    path = CACHE / (key+'.json')
    if path.exists() and datetime.now().timestamp()-path.stat().st_mtime<21600:
        return Article.model_validate_json(path.read_text(encoding='utf-8'))
    html, final_url = fetch(url)
    import trafilatura
    doc = trafilatura.bare_extraction(html, url=final_url, with_metadata=True, include_comments=False)
    if not doc or not doc.text or len(doc.text.strip())<80:
        raise ValueError('No usable article body. The publisher may require login or block extraction.')
    a = Article(title=doc.title or 'Extracted article',text=doc.text[:40000],publisher=doc.sitename or urlsplit(final_url).hostname,date=doc.date or '',url=final_url)
    path.write_text(a.model_dump_json(),encoding='utf-8')
    return a

# Topic input is plain language, not a raw GDELT query language.
STOP_WORDS = set('and or the a an in on at of for to with about news latest recent updates update please show me articles related'.split())
ALIASES = {
    'bengaluru': ('bengaluru', 'bangalore'),
    'bangalore': ('bengaluru', 'bangalore'),
    'metro': ('metro', 'bmrcl'),
    'bmrcl': ('metro', 'bmrcl'),
}

def topic_groups(topic):
    groups = []
    for term in re.findall(r"[\w]+", topic.lower()):
        if term in STOP_WORDS:
            continue
        group = ALIASES.get(term, (term,))
        if group not in groups:
            groups.append(group)
    return groups

def build_query(groups):
    # Equivalent topic wording/order shares one provider cache entry.
    return ' '.join('(' + ' OR '.join(g) + ')' if len(g) > 1 else g[0] for g in sorted(groups))

def matches_topic(text, groups):
    words = set(re.findall(r"[\w]+", text.lower()))
    return bool(groups) and all(any(term in words for term in g) for g in groups)

def relevant_article(article, groups):
    # Require every topic concept in the headline/lead, with at least one in
    # the headline. Exclude late-page navigation and unrelated appended stories.
    title = article.title
    lead = title + ' ' + article.text[:1800]
    headline_hit = any(matches_topic(title, [g]) for g in groups)
    return headline_hit and matches_topic(lead, groups)

def search(topic, days, limit):
    warnings=[]; candidates=[]; skipped=[]
    groups=topic_groups(topic)
    if not groups:
        return {'articles':[], 'found':0, 'skipped':[], 'warnings':['Enter a specific subject, for example Bengaluru metro.']}
    query=build_query(groups)
    fallback_enabled = os.getenv('NEWS_RSS_FALLBACK', '1') == '1'
    cached_fallback = FALLBACK.cached_search(query, days) if fallback_enabled else None
    provider = cached_fallback or GDELT.search(query, days, fetch)
    primary_status = 'not_requested' if cached_fallback else provider.status
    source = 'Bing News RSS' if cached_fallback else 'GDELT'
    request_count = provider.requests
    if provider.status != 'ok' and fallback_enabled:
        fallback = FALLBACK.search(query, days)
        request_count += fallback.requests
        if fallback.status == 'ok':
            provider = fallback
            source = 'Bing News RSS'
            warnings.append('GDELT is temporarily unavailable. Using Bing News RSS; publisher text is extracted and checked for relevance.')
        else:
            warnings.extend(fallback.warnings)
            provider.retry_after = max(provider.retry_after, fallback.retry_after)
    candidates = list(provider.articles)
    warnings.extend(provider.warnings)
    if not candidates:
        for feed in filter(None,os.getenv('RSS_FEEDS','').split(',')):
            try:
                raw,_=fetch(feed.strip())
                for item in ET.fromstring(raw).findall('.//item'):
                    # All substantive concepts must match; "and" is never a term.
                    text=item.findtext('title','')+' '+item.findtext('description','')
                    if matches_topic(text,groups):
                        candidates.append({'url':item.findtext('link','')})
                warnings.append('RSS fallback results may not respect the requested date range.')
            except Exception:
                warnings.append('An RSS feed was unavailable.')
    articles=[];seen=set();content_seen=set();filtered=0
    for row in candidates[:30]:
        if len(articles)>=limit: break
        if not isinstance(row,dict):continue
        url=row.get('url','')
        if not url or url in seen: continue
        seen.add(url)
        try:
            a=extract(url)
            if not relevant_article(a,groups):
                filtered+=1
                skipped.append({'url':url,'reason':'Excluded: headline and opening text do not match all topic concepts.'})
                continue
            content_key=hashlib.sha256(re.sub(r'\s+',' ',a.text.lower()).strip().encode()).hexdigest()
            if content_key in content_seen:
                skipped.append({'url':url,'reason':'Excluded: duplicate article text.'});continue
            content_seen.add(content_key)
            articles.append(a.model_dump())
        except Exception as e: skipped.append({'url':url,'reason':str(e)[:180]})
    if filtered:warnings.append(f'Excluded {filtered} off-topic articles using headline/lead keyword checks.')
    if not articles:
        if candidates:
            warnings.append('Candidate links were found, but none produced a relevant readable article. '
                            'See the skipped-link reasons or paste article text directly.')
        elif provider.status == 'ok':
            warnings.append('The search completed but returned no matching links. '
                            'Try a broader date range or a shorter, specific topic.')
    # GDELT seendate is discovery time, deliberately not used as publication date.
    return {'articles':articles,'found':len(candidates),'skipped':skipped,'warnings':warnings,
            'query_used':query,'relevance_method':'all topic concepts in headline/lead; at least one in headline',
            'search_status':provider.status,'retry_after_seconds':provider.retry_after,
            'search_cached':provider.cached,'provider_requests':request_count,
            'search_provider':source,'primary_status':primary_status}
