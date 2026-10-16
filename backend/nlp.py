import re
from functools import lru_cache
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from . import config

@lru_cache(maxsize=1)
def linguistic_model():
    import spacy
    return spacy.load('en_core_web_sm')

@lru_cache(maxsize=1)
def encoder():
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(config.EMBEDDING_MODEL,device='cpu')

def split(text):
    return [s.strip() for s in re.split(r'(?<=[.!?])\s+|\n+',text) if s.strip()]

def normalize(s): return re.sub(r'\W+',' ',s.lower()).strip()

def process(articles, threshold):
    warnings=[];sentences=[];entities=[];ling=None
    if config.MODE=='models':
        try: ling=linguistic_model()
        except Exception: warnings.append('spaCy model unavailable; using punctuation-based sentence splitting.')
    for a in articles:
        doc=ling(a['text']) if ling else None
        pieces=[s.text.strip() for s in doc.sents] if doc else split(a['text'])
        if doc:
            entities.extend({'text':e.text,'label':e.label_,'article_id':a['id']} for e in doc.ents)
        for i,s in enumerate(pieces):
            if s: sentences.append({'id':f"{a['id']}:s{i+1}",'text':s,'article_id':a['id'],'publication_date':a['date']})
    if len(sentences)>600: raise ValueError('Collection exceeds 600 sentences. Select fewer or shorter articles.')
    texts=[s['text'] for s in sentences]
    vectorizer=TfidfVectorizer(stop_words='english',token_pattern=r'(?u)\b\w+\b')
    try: tf=vectorizer.fit_transform(texts)
    except ValueError:
        vectorizer=TfidfVectorizer(analyzer='char',ngram_range=(2,3));tf=vectorizer.fit_transform(texts)
    vectors=tf.toarray();method='TF-IDF cosine similarity'
    if config.MODE=='models':
        try:
            vectors=encoder().encode(texts,batch_size=8,normalize_embeddings=True,show_progress_bar=False)
            method='Sentence-transformer embeddings'
        except Exception: warnings.append('Embedding model unavailable; using TF-IDF similarity.')
    sim=cosine_similarity(vectors)
    # Preserve near-duplicates as evidence. Never remove semantically similar claims
    # automatically: numbers, negations and time can carry important disagreements.
    retained=[]; seen={}; duplicates=[];near=[]
    for i,s in enumerate(sentences):
        key=normalize(s['text'])
        if key in seen:
            kept=seen[key];kept['evidence_ids'].append(s['id'])
            duplicates.append({'removed':s['id'],'retained':kept['id'],'kind':'exact_normalized'})
        else:
            row={**s,'evidence_ids':[s['id']],'index':i}
            seen[key]=row;retained.append(row)
        for j in range(i):
            if sentences[j]['article_id']!=s['article_id'] and sim[i,j]>=threshold and normalize(sentences[j]['text'])!=key:
                if len(near)<100: near.append({'a':sentences[j]['id'],'b':s['id'],'similarity':round(float(sim[i,j]),4),'action':'retained_for_claim_review'})
    centroid=np.asarray(tf.mean(axis=0))
    ranks=cosine_similarity(tf,centroid).ravel()
    for s in retained: s['score']=float(ranks[s['index']])
    ranked=sorted(retained,key=lambda s:s['score'],reverse=True)
    av=np.vstack([np.mean(vectors[[i for i,s in enumerate(sentences) if s['article_id']==a['id']]],axis=0) for a in articles])
    am=cosine_similarity(av)
    # Deterministic connected components over document cosine threshold.
    groups=[];remaining=set(range(len(articles)))
    while remaining:
        seed=min(remaining);remaining.remove(seed);group=[seed];front=[seed]
        while front:
            i=front.pop()
            connected=[j for j in sorted(remaining) if am[i,j]>=0.55]
            for j in connected: remaining.remove(j);group.append(j);front.append(j)
        groups.append([articles[i]['id'] for i in sorted(group)])
    keywords=[{'term':str(vectorizer.get_feature_names_out()[i]),'weight':round(float(np.asarray(tf.sum(axis=0)).ravel()[i]),3)} for i in np.argsort(np.asarray(tf.sum(axis=0)).ravel())[-14:][::-1]]
    return {'sentences':sentences,'retained':retained,'ranked':ranked,'entities':entities,'duplicates':duplicates,'near_duplicates':near,'similarity_matrix':am.round(4).tolist(),'article_ids':[a['id'] for a in articles],'clusters':groups,'keywords':keywords,'method':method,'warnings':warnings},sim
