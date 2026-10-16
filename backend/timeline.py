import re
from datetime import datetime
import dateparser
PATTERN=re.compile(r'\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2}(?:,?\s+\d{4})?|\b\d{4}-\d{2}-\d{2}\b|\b(?:yesterday|today|tomorrow)\b',re.I)
def extract_events(sentences):
    events=[];unresolved=[]
    for s in sentences:
        matches=list(PATTERN.finditer(s['text']))
        if not matches: continue
        if len(matches)!=1:
            unresolved.append({**s,'reason':'Multiple date mentions; event-date association needs review.'});continue
        raw=matches[0].group();relative=raw.lower() in ('yesterday','today','tomorrow')
        base=dateparser.parse(s.get('publication_date') or '')
        if (relative or not re.search(r'\d{4}',raw)) and not base:
            unresolved.append({**s,'reason':'Missing publication date for relative or yearless date.'});continue
        settings={'RELATIVE_BASE':base} if base else {'STRICT_PARSING':True}
        d=dateparser.parse(raw,settings=settings)
        if not d:
            unresolved.append({**s,'reason':'Date could not be resolved.'});continue
        events.append({'text':s['text'],'date':d.date().isoformat(),'evidence_ids':s.get('evidence_ids',[s['id']]),'method':'dated_sentence','needs_review':True})
    return sorted(events,key=lambda e:e['date']),unresolved
