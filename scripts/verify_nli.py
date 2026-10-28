"""Verify real NLI inference and the running API; no mocked model predictions."""
import json
import time
from pathlib import Path
import httpx
import numpy as np
import torch
from backend.contradictions import model


def main():
    classifier = model()
    controls = [
        ('The bridge is open to all traffic.', 'The bridge is closed to all traffic.'),
        ('The bridge is open to all traffic.', 'Traffic can cross the bridge.'),
        ('The bridge is open to all traffic.', 'The mayor owns a red bicycle.'),
    ]
    logits = np.asarray(classifier.predict(controls, activation_fn=torch.nn.Identity(), show_progress_bar=False))
    exp = np.exp(logits - logits.max(axis=1, keepdims=True))
    scores = exp / exp.sum(axis=1, keepdims=True)
    labels = {int(k):str(v).lower() for k,v in classifier.model.config.id2label.items()}
    contradiction = next((k for k,v in labels.items() if 'contradiction' in v), 0)
    control_scores = scores[:, contradiction].tolist()
    print('Real model contradiction scores:', control_scores, flush=True)
    assert control_scores[0] > .8 and all(x < .8 for x in control_scores[1:])
    common = ' These statements are fictional verification examples about the same bridge at the same time.'
    payload = {'use_llm':False, 'articles':[
        {'title':'NLI verification: bridge open', 'text':controls[0][0]+common, 'fictional':True},
        {'title':'NLI verification: bridge closed', 'text':controls[0][1]+common, 'fictional':True},
    ]}
    with httpx.Client(base_url='http://127.0.0.1:8000', timeout=30, trust_env=False) as client:
        response = client.post('/api/analyses', json=payload)
        response.raise_for_status()
        job = response.json()['id']
        deadline = time.monotonic() + 300
        previous = None
        while time.monotonic() < deadline:
            response = client.get('/api/analyses/'+job)
            response.raise_for_status()
            row = response.json()
            state = row.get('stage') or row['status']
            if state != previous:
                print(state, flush=True)
                previous = state
            if row['status'] in ('completed','failed'):
                break
            time.sleep(1)
        assert row['status'] == 'completed', row.get('error') or row['status']
        result = row['result']
        conflicts = result['contradictions']
        report = {'live_model':True, 'job_id':job, 'control_contradiction_scores':control_scores,
                  'nlp_method':result['nlp']['method'], 'warnings':result['warnings'],
                  'contradictions':conflicts,
                  'passed':conflicts['status']=='completed' and len(conflicts['pairs'])>0}
        Path('runtime/nli-verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(json.dumps(report,indent=2), flush=True)
        assert report['passed']


if __name__ == '__main__':
    main()
