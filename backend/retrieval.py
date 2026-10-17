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
CACHE = RUNTIME / 'article-cache'
CACHE.mkdir(exist_ok=True)

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
    # Revalidate each redirect; body size and decompressed bytes are bounded.
    with httpx.Client(timeout=httpx.Timeout(20, connect=8), follow_redirects=False, trust_env=False,
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
    return ' '.join('(' + ' OR '.join(g) + ')' if len(g) > 1 else g[0] for g in groups)

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
    try:
        raw,_=fetch('https://api.gdeltproject.org/api/v2/doc/doc',params={'query':query+' sourcelang:english','mode':'artlist','format':'json','maxrecords':min(30,limit*3),'timespan':f'{days}d','sort':'hybridrel'})
        decoded=json.loads(raw)
        if not isinstance(decoded,dict) or not isinstance(decoded.get('articles',[]),list):
            raise ValueError('Unexpected search response structure')
        candidates=decoded.get('articles',[])
    except httpx.TimeoutException:
        warnings.append('GDELT search timed out. Try again later, widen the date range, or paste article URLs.')
    except httpx.HTTPStatusError as e:
        warnings.append(f'GDELT returned HTTP {e.response.status_code}. Try again later or paste article URLs.')
    except (json.JSONDecodeError,ValueError):
        warnings.append('GDELT returned an invalid or non-JSON response. No search results were assumed.')
    except Exception:
        warnings.append('Could not connect to GDELT. Check the network or use article URLs.')
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
    if not articles:warnings.append('No relevant accessible articles found. Try a broader date range or paste direct article URLs. Unrelated stories are not used to fill the collection.')
    # GDELT seendate is discovery time, deliberately not used as publication date.
    return {'articles':articles,'found':len(candidates),'skipped':skipped,'warnings':warnings,'query_used':query,'relevance_method':'all topic concepts in headline/lead; at least one in headline'}
