import json
from pathlib import Path
import pytest
from backend import config, llm, retrieval, store
from backend.pipeline import analyze
from backend.schemas import AnalysisRequest, Synthesis
from backend.timeline import extract_events
from backend.contradictions import context_flags

@pytest.fixture
def request_data(monkeypatch):
    monkeypatch.setattr(config,'MODE','lightweight')
    return AnalysisRequest(articles=json.loads(Path('data/demo.json').read_text()),use_llm=False)

def test_demo_preserves_conflicting_counts_and_provenance(request_data):
    r=analyze(request_data)
    assert len(r['articles'])==4
    assert len(r['nlp']['duplicates'])>0
    remaining=' '.join(s['text'] for s in r['nlp']['retained'])
    assert '12,000' in remaining and '9,500' in remaining
    ids={s['id'] for s in r['nlp']['sentences']}
    assert all(set(c['evidence_ids'])<=ids for c in r['summary']['claims'])
    assert r['timeline']['events']==sorted(r['timeline']['events'],key=lambda e:e['date'])
    assert r['contradictions']['status']=='not_evaluated'
    assert r['evaluation']['rouge'] is None

def test_relative_dates_require_metadata():
    base={'id':'A1:s1','text':'Yesterday the metro opened.','publication_date':''}
    events,unknown=extract_events([base]);assert not events and len(unknown)==1
    events,_=extract_events([{**base,'publication_date':'2026-04-15'}]);assert events[0]['date']=='2026-04-14'

def test_multiple_dates_are_not_guessed():
    events,unknown=extract_events([{'id':'A1:s1','text':'On April 10, 2026, officials announced the opening on April 14, 2026.','publication_date':''}])
    assert not events and len(unknown)==1

def test_invalid_citations_rejected():
    parsed=Synthesis(summary=[{'text':'Invented','evidence_ids':['A99:s1']}],events=[])
    with pytest.raises(ValueError):llm.validate_synthesis(parsed,[{'id':'A1:s1'}])

def test_valid_citation_does_not_claim_truth():
    parsed=Synthesis(summary=[{'text':'A claim','evidence_ids':['A1:s1']}],events=[{'text':'An event','date':'nonsense','evidence_ids':['A1:s1']}])
    summary,events,_=llm.validate_synthesis(parsed,[{'id':'A1:s1'}])
    assert summary and events[0]['date'] is None

def test_gemini_failure_falls_back(request_data,monkeypatch):
    request_data.use_llm=True
    monkeypatch.setattr(llm,'available',lambda:True)
    def fail(*a):raise RuntimeError('SECRET_KEY_NEVER_SHOW')
    monkeypatch.setattr(llm,'synthesize',fail)
    r=analyze(request_data)
    assert r['summary']['mode']=='extractive'
    assert 'SECRET_KEY' not in json.dumps(r)
    assert any('Gemini unavailable' in w for w in r['warnings'])

def test_rouge_requires_actual_reference(request_data):
    request_data.reference_summary='The Riverline metro opened on April 14, 2026.'
    r=analyze(request_data)
    assert set(r['evaluation']['rouge'])=={'rouge1','rouge2','rougeL'}

def test_numeric_and_temporal_context():
    flags=context_flags({'text':'12,000 journeys','publication_date':'2026-04-14'},{'text':'9,500 journeys','publication_date':'2026-04-15'})
    assert len(flags)==2

@pytest.mark.parametrize('url',['file:///etc/passwd','http://127.0.0.1','http://[::1]','http://localhost','http://user:password@example.com','http://example.com:9000'])
def test_private_urls_rejected(url):
    with pytest.raises((ValueError,OSError)):retrieval.validate_url(url)

def test_real_extraction_adapter(monkeypatch,tmp_path):
    monkeypatch.setattr(retrieval,'CACHE',tmp_path)
    monkeypatch.setattr(retrieval,'validate_url',lambda url:url)
    text='The Riverline metro opened to passengers after extensive safety inspections. Officials said the route connects eight stations across the city and will operate regular services throughout the week.'
    monkeypatch.setattr(retrieval,'fetch',lambda url:('<html><head><title>Metro opens</title></head><body><article><h1>Metro opens</h1><p>'+text+'</p><p>'+text+'</p></article></body></html>',url))
    a=retrieval.extract('https://example.com/story')
    assert 'Riverline' in a.text


def test_http_job_roundtrip(request_data,monkeypatch,tmp_path):
    import time
    from fastapi.testclient import TestClient
    from backend.main import app
    monkeypatch.setattr(store,'DB',tmp_path/'test.sqlite')
    with TestClient(app) as client:
        assert client.get('/').status_code==200
        assert client.get('/api/capabilities').status_code==200
        blocked=client.post('/api/analyses',json=request_data.model_dump(),headers={'origin':'https://other.example'})
        assert blocked.status_code==403
        job=client.post('/api/analyses',json=request_data.model_dump())
        assert job.status_code==202
        jid=job.json()['id']
        for _ in range(100):
            row=client.get('/api/analyses/'+jid).json()
            if row['status'] in ('completed','failed'):break
            time.sleep(.05)
        assert row['status']=='completed',row
        assert client.get('/api/analyses/'+jid+'/export').json()['summary']['mode']=='extractive'
        assert client.get('/api/analyses').json()['analyses'][0]['id']==jid
        assert client.get('/api/analyses/missing').status_code==404
