import json,httpx
from pathlib import Path
s=json.loads(Path('data/otp/introspection.json').read_text(encoding='utf-8'))['data']['__schema']
t={x['name']:x for x in s['types']}
print('ServiceJourney fields',[(f['name'],f['type'].get('name')) for f in t['ServiceJourney']['fields']])
print('Query fields',[(f['name'],f.get('args')) for f in t['QueryType']['fields'] if 'date' in f['name'].lower() or 'journey' in f['name'].lower() or 'feed' in f['name'].lower()])
q='query($ids:[String]){quays(ids:$ids){id estimatedCalls(startTime:"2026-10-20T08:00:00+03:30",timeRange:86400,numberOfDepartures:1){date expectedDepartureTime serviceJourney{id transportMode quays{id latitude longitude}}}}}'
ids=[x['id'] for x in json.loads(Path('data/otp/quays.json').read_text(encoding='utf-8'))['data']['quays'][:3]]
r=httpx.post('http://127.0.0.1:8821/otp/transmodel/v3',json={'query':q,'variables':{'ids':ids}},timeout=30).json()
Path('data/otp/departures.json').write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(r,ensure_ascii=True)[:5000])
