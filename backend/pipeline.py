import time
from . import nlp, timeline, llm, contradictions

def analyze(request,progress=lambda stage:None):
    started=time.perf_counter()
    articles=[{**a.model_dump(),'id':f'A{i+1}'} for i,a in enumerate(request.articles)]
    if sum(len(a['text']) for a in articles)>160000:raise ValueError('Collection exceeds 160,000 characters.')
    progress('Preprocessing, similarity and duplicate analysis')
    processed,similarity=nlp.process(articles,request.duplicate_threshold)
    baseline=[{'text':s['text'],'evidence_ids':s['evidence_ids']} for s in processed['ranked'][:8]]
    progress('Resolving dated evidence')
    events,unresolved=timeline.extract_events(processed['retained'])
    generated=None;warnings=list(processed['warnings'])
    if request.use_llm and llm.available():
        progress('Generating Gemini briefing and events')
        try:
            generated=llm.synthesize(processed)
            warnings.extend(generated['warnings'])
            events=sorted([e for e in generated['events'] if e['date']],key=lambda x:x['date'])
            unresolved.extend(e for e in generated['events'] if not e['date'])
        except Exception as e:warnings.append(f'Gemini unavailable ({type(e).__name__}); extractive baseline shown. Check API key, model and quota.')
    elif request.use_llm:warnings.append('GEMINI_API_KEY is not set. Showing the extractive baseline.')
    progress('Comparing cross-source claims')
    conflicts=contradictions.detect(processed,similarity,request.use_llm)
    claims=generated['claims'] if generated else baseline
    scores={'rouge':None,'bertscore':None,'timeline_accuracy':None,'contradiction_f1':None,'factual_consistency':None}
    if request.reference_summary:
        from rouge_score import rouge_scorer
        scorer=rouge_scorer.RougeScorer(['rouge1','rouge2','rougeL'],use_stemmer=True)
        scores['rouge']={name:float(v.fmeasure) for name,v in scorer.score(request.reference_summary,' '.join(c['text'] for c in claims)).items()}
    progress('Saving source-linked results')
    return {'articles':articles,'fictional_demo':all(a['fictional'] for a in articles),'nlp':processed,'summary':{'mode':'gemini' if generated else 'extractive','claims':claims,'baseline':baseline,'model':generated['model'] if generated else None,'evidence_count':generated['evidence_count'] if generated else len(processed['retained']),'omitted_sentences':generated['omitted_sentences'] if generated else 0},'timeline':{'events':events,'unresolved':unresolved},'contradictions':conflicts,'evaluation':scores,'warnings':warnings,'elapsed_seconds':round(time.perf_counter()-started,2)}
