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

def search(topic, days, limit):
    warnings=[]; candidates=[]
    query=re.sub(r'[^\w\s-]',' ',topic).strip()
    try:
        raw,_=fetch('https://api.gdeltproject.org/api/v2/doc/doc',params={'query':query+' sourcelang:english','mode':'artlist','format':'json','maxrecords':min(30,limit*2),'timespan':f'{days}d','sort':'datedesc'})
        candidates=json.loads(raw).get('articles',[])
    except Exception:
        warnings.append('GDELT did not return usable results. Try again later or use article URLs.')
    if not candidates:
        for feed in filter(None,os.getenv('RSS_FEEDS','').split(',')):
            try:
                raw,_=fetch(feed.strip())
                for item in ET.fromstring(raw).findall('.//item'):
                    title=item.findtext('title','')
                    if any(t.lower() in title.lower() for t in query.split()):
                        candidates.append({'url':item.findtext('link','')})
                warnings.append('RSS fallback results may not respect the requested date range.')
            except Exception:
                warnings.append('An RSS feed was unavailable.')
    articles=[];seen=set();skipped=[]
    for row in candidates:
        if len(articles)>=limit: break
        url=row.get('url','')
        if not url or url in seen: continue
        seen.add(url)
        try: articles.append(extract(url).model_dump())
        except Exception as e: skipped.append({'url':url,'reason':str(e)[:180]})
    # GDELT seendate is discovery time, deliberately not used as publication date.
    return {'articles':articles,'found':len(candidates),'skipped':skipped,'warnings':warnings}
