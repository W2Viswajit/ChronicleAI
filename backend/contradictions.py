import re
from functools import lru_cache
import numpy as np
from . import config, llm

@lru_cache(maxsize=1)
def model():
    from sentence_transformers import CrossEncoder
    return CrossEncoder(config.NLI_MODEL,device='cpu',max_length=384)

def context_flags(a,b):
    flags=[]
    if a.get('publication_date') and b.get('publication_date') and a['publication_date']!=b['publication_date']:
        flags.append('Reports have different publication dates; check whether this is an update.')
    if set(re.findall(r'\b\d[\d,.]*\b',a['text'])) != set(re.findall(r'\b\d[\d,.]*\b',b['text'])):
        flags.append('Numeric values differ; verify date, units and counting scope.')
    return flags

def detect(nlp,similarity,use_llm):
    if config.MODE!='models':return {'status':'not_evaluated','reason':'Enable NLP_MODE=models and install model dependencies.','pairs':[],'tested_pairs':0}
    sentences=nlp['sentences'];candidates=[]
    for i,a in enumerate(sentences):
        for j in range(i):
            b=sentences[j]
            if a['article_id']==b['article_id'] or a['text'].lower()==b['text'].lower():continue
            score=float(similarity[i,j])
            if score>=0.45:candidates.append((score,j,i))
    candidates=sorted(candidates,reverse=True)[:config.MAX_NLI_PAIRS]
    if not candidates:return {'status':'completed','pairs':[],'tested_pairs':0,'reason':'No sufficiently similar cross-source sentence pairs.'}
    try:
        classifier=model()
        # This model family documents contradiction=0, entailment=1, neutral=2.
        labels={int(k):str(v).lower() for k,v in classifier.model.config.id2label.items()}
        ci=next((i for i,l in labels.items() if 'contradiction' in l),None)
        if ci is None:
            if config.NLI_MODEL=='cross-encoder/nli-deberta-v3-small':ci=0
            else:raise ValueError('Unknown NLI labels; choose a model with explicit id2label.')
        pairs=[(sentences[j]['text'],sentences[i]['text']) for _,j,i in candidates]
        # Compute raw logits explicitly, then softmax; do not treat them as calibrated truth.
        import torch
        logits=np.asarray(classifier.predict(pairs,batch_size=4,activation_fn=torch.nn.Identity(),show_progress_bar=False))
        exp=np.exp(logits-logits.max(axis=1,keepdims=True));probs=exp/exp.sum(axis=1,keepdims=True)
        output=[]
        for (_,j,i),p in zip(candidates,probs):
            if p[ci]<config.NLI_THRESHOLD:continue
            a,b=sentences[j],sentences[i]
            item={'a':a,'b':b,'nli_score':round(float(p[ci]),4),'classification':'potential_contradiction','explanation':'NLI flagged this sentence pair; human review required.','context_flags':context_flags(a,b),'llm_reviewed':False}
            if use_llm and llm.available() and len(output)<5:
                try:item.update(llm.review_pair(a,b));item['llm_reviewed']=True
                except Exception:item['context_flags'].append('Gemini review unavailable; retained as an unverified NLI flag.')
            output.append(item)
        return {'status':'completed','pairs':output,'tested_pairs':len(candidates),'model':config.NLI_MODEL,'threshold':config.NLI_THRESHOLD,'reason':'NLI scores are uncalibrated model scores, not truth probabilities.'}
    except ModuleNotFoundError as e:
        missing = e.name or 'unknown dependency'
        return {'status':'unavailable','reason':f"NLI dependency missing: {missing}. Stop the server and run setup-models.ps1 from the project folder, then restart and analyze again.",'missing_module':missing,'pairs':[],'tested_pairs':0}
    except Exception as e:
        return {'status':'unavailable','reason':f'NLI could not run ({type(e).__name__}). Check model installation and download access.','pairs':[],'tested_pairs':0}
