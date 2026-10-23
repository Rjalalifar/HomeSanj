import httpx,json
from pathlib import Path
query='query($ids:[String]){quays(ids:$ids){id journeyPatterns{id quays{id latitude longitude} serviceJourneys{id activeDates transportMode}}}}'
quays=json.loads(Path('data/otp/quays.json').read_text(encoding='utf-8'))['data']['quays']
r=httpx.post('http://127.0.0.1:8821/otp/transmodel/v3',json={'query':query,'variables':{'ids':[quays[0]['id']]}},timeout=30).json()
Path('data/otp/service-dates.json').write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(r,ensure_ascii=True)[:6000])
