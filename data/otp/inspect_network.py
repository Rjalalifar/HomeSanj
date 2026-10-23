import json
from pathlib import Path
import httpx

schema = json.loads(Path('data/otp/introspection.json').read_text(encoding='utf-8'))['data']['__schema']
lookup = {item['name']: item for item in schema['types']}
for name in ('ServiceJourney', 'JourneyPattern', 'Quay', 'EstimatedCall', 'RoutingErrorCode'):
    item = lookup.get(name, {})
    print(name, json.dumps([{'name': field['name'], 'type': field['type'], 'args': field.get('args', [])} for field in (item.get('fields') or []) if field['name'] in ('estimatedCalls','serviceJourney','serviceJourneys','journeyPatterns','quays','operatingDates','date','id','name','latitude','longitude','transportMode','passingTimes')], ensure_ascii=True))
    if name == 'RoutingErrorCode':
        print(item.get('enumValues'))
query = '{ serverInfo { version buildTime gitCommit internalTransitModelTimeZone } lines { id name publicCode transportMode } quays { id name latitude longitude } }'
response = httpx.post('http://127.0.0.1:8821/otp/transmodel/v3', json={'query':query}, timeout=30)
result = response.json()
Path('data/otp/network-metadata.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print('HTTP',response.status_code)
print('errors',result.get('errors'))
print('server',result.get('data',{}).get('serverInfo'))
print('lines',len(result.get('data',{}).get('lines',[])))
print('quays',len(result.get('data',{}).get('quays',[])))
print('first_line',result.get('data',{}).get('lines',[])[:1])
print('first_quays',result.get('data',{}).get('quays',[])[:3])
