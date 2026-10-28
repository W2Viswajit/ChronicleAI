"""Run real searches sequentially, then check the cache. No mocked results."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time

from backend.retrieval import search


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--topics', nargs=2, default=['Bengaluru metro', 'India cricket'])
    parser.add_argument('--gap', type=int, default=35)
    parser.add_argument('--days', type=int, default=7, choices=range(1, 31))
    parser.add_argument('--limit', type=int, default=2, choices=range(2, 11))
    args = parser.parse_args()
    print('Live news verification: paced GDELT plus cached Bing News RSS fallback.', flush=True)
    records = []
    for index, topic in enumerate(args.topics):
        if index:
            wait = max(6, args.gap, records[-1]['retry_after_seconds'] + 1)
            print(f'Waiting {wait}s before the second topic...', flush=True)
            # Remain observable even if the provider requests a long pause.
            while wait > 0:
                chunk = min(30, wait)
                time.sleep(chunk)
                wait -= chunk
                if wait > 0:
                    print(f'{wait}s remaining...', flush=True)
        start = time.time()
        print(f'Searching: {topic}', flush=True)
        result = search(topic, args.days, args.limit)
        record = {'topic': topic, 'at': datetime.now(timezone.utc).isoformat(),
                  'elapsed_seconds': round(time.time() - start, 2),
                  'search_status': result.get('search_status'),
                  'search_provider': result.get('search_provider'),
                  'retry_after_seconds': result.get('retry_after_seconds', 0),
                  'provider_requests': result.get('provider_requests', 0),
                  'cached': result.get('search_cached', False),
                  'candidate_links': result['found'],
                  'readable_articles': len(result['articles']),
                  'articles': [{'title': a['title'], 'url': a['url']} for a in result['articles']],
                  'warnings': result['warnings'], 'skipped': result['skipped']}
        records.append(record)
        print(json.dumps(record, indent=2), flush=True)
    report = {'live_test': True, 'results': records,
              'passed': all(r['search_status'] == 'ok' and r['readable_articles'] >= 2 for r in records)}
    if records[0]['search_status'] == 'ok':
        start = time.time()
        repeat = search(args.topics[0], args.days, args.limit)
        report['repeat_elapsed_seconds'] = round(time.time() - start, 2)
        report['repeat_used_cache'] = repeat.get('search_cached', False)
        report['repeat_provider_requests'] = repeat.get('provider_requests', 0)
        report['passed'] = report['passed'] and report['repeat_used_cache']
    output = Path('runtime/news-search-verification.json')
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(f"{'PASS' if report['passed'] else 'NOT PASSED'}: {output}", flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
