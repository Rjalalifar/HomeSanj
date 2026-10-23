import httpx,json
from pathlib import Path
client=httpx.Client(timeout=30)
queries={
 'server': '{serverInfo {version buildTime gitCommit internalTransitModelTimeZone}}',
 'quays': '{quays {id name latitude longitude}}',
 'line_ids': '{lines {id transportMode}}',
}
for name,query in queries.items():
 response=client.post('http://127.0.0.1:8821/otp/transmodel/v3',json={'query':query})
 value=response.json()
 Path(f'data/otp/{name}.json').write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
 print(name,response.status_code, json.dumps(value,ensure_ascii=True)[:1800])
