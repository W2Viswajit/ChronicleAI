import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
import json
import logging
import uuid
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from . import config, store, retrieval, llm
from .schemas import AnalysisRequest, SearchRequest, ExtractRequest
from .pipeline import analyze
log=logging.getLogger('chronicle')
worker=ThreadPoolExecutor(max_workers=1)
active=set()

def run_job(job,request):
    try:
        result=analyze(request,lambda stage:store.update(job,'running',stage))
        store.update(job,'completed','Complete',result)
    except Exception as e:
        log.error('Analysis failed: %s',type(e).__name__)
        store.update(job,'failed',error=str(e)[:250] if isinstance(e,ValueError) else 'Analysis failed. Check model setup and input size.')
    finally:active.discard(job)

@asynccontextmanager
async def lifespan(app):
    store.init()
    yield
    worker.shutdown(wait=True)

app=FastAPI(title='ChronicleAI Local API',version='0.1.0',lifespan=lifespan)

@app.middleware('http')
async def local_guard(request:Request,call_next):
    # Loopback server only. Block browser requests from other origins.
    if request.method not in ('GET','HEAD','OPTIONS'):
        origin=request.headers.get('origin')
        allowed={'http://127.0.0.1:8000','http://localhost:8000'}
        if origin and origin not in allowed:return JSONResponse({'detail':'Open the local ChronicleAI UI to use this API.'},status_code=403)
    return await call_next(request)

@app.get('/api/health')
def health():return {'status':'ok','mode':config.MODE}

@app.get('/api/capabilities')
def capabilities():return {'nlp_mode':config.MODE,'gemini_configured':llm.available(),'nli_enabled':config.MODE=='models','model_readiness':'Validated on first inference; configuration alone does not confirm availability.'}

@app.post('/api/articles/search')
def search(req:SearchRequest):return retrieval.search(req.topic,req.days,req.limit)

@app.post('/api/articles/extract')
def extract(req:ExtractRequest):
    articles=[];skipped=[]
    for url in dict.fromkeys(req.urls):
        try:articles.append(retrieval.extract(url).model_dump())
        except Exception as e:skipped.append({'url':url,'reason':str(e)[:180]})
    return {'articles':articles,'skipped':skipped,'warnings':[]}

@app.post('/api/analyses',status_code=202)
def create(req:AnalysisRequest):
    if len(active)>=3:raise HTTPException(429,'Three analyses are already queued. Wait for one to finish.')
    job=uuid.uuid4().hex;store.create(job);active.add(job);worker.submit(run_job,job,req)
    return {'id':job,'status':'queued'}

@app.get('/api/analyses')
def history():return {'analyses':store.history()}

@app.get('/api/analyses/{job}')
def get(job:str):
    row=store.get(job)
    if row is None:raise HTTPException(404,'Analysis not found')
    return row

@app.get('/api/analyses/{job}/export')
def export(job:str):
    row=get(job)
    if row['status']!='completed':raise HTTPException(409,'Analysis is not complete')
    return JSONResponse(row['result'],headers={'Content-Disposition':'attachment; filename="chronicle-analysis.json"'})

app.mount('/',StaticFiles(directory=config.ROOT/'frontend',html=True),name='frontend')
