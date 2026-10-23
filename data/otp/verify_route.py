import asyncio,json
from pathlib import Path
from datetime import datetime,timezone
import httpx
from backend.app.routing import OTPSettings,OTPAdapter,TRANSMODEL_QUERY,evaluate_itineraries,request_datetime
from backend.app.contracts import Itinerary

async def main():
 network=json.loads(Path('data/otp/service-dates.json').read_text(encoding='utf-8'))['data']['quays'][0]['journeyPatterns'][0]
 journey=network['serviceJourneys'][0]
 today=datetime.now(timezone.utc).date().isoformat()
 date=today if today in journey['activeDates'] else journey['activeDates'][0]
 origin={k:network['quays'][0][k] for k in ('latitude','longitude')}
 destination={k:network['quays'][-1][k] for k in ('latitude','longitude')}
 travel={'destination':{**destination,'confirmed':True},'date':date,'time':'08:00:00','timezone':'Asia/Tehran','time_mode':'DEPART_AT','modes':[journey['transportMode'].upper()],'include_walk_only':False}
 settings=OTPSettings(api_path='/otp/transmodel/v3',api_type='transmodel_v3',supported_modes=travel['modes'],schedule_basis='unknown')
 variables={'from':{'coordinates':origin},'to':{'coordinates':destination},'dateTime':request_datetime(travel).isoformat(),'arriveBy':False,'modes':{'accessMode':'foot','egressMode':'foot','directMode':None,'transportModes':[{'transportMode':journey['transportMode']}]}}
 payload={'query':TRANSMODEL_QUERY,'variables':variables}
 async with httpx.AsyncClient(timeout=30) as client:
  response=await client.post(settings.base_url+settings.api_path,json=payload)
  raw=response.json()
 result=OTPAdapter(settings)._normalize_response(raw,origin,travel,'contract-live-1')
 if result['status']=='ok':
  for item in result['itineraries']: Itinerary.model_validate(item)
  result.update(evaluate_itineraries(result['itineraries'],travel))
 target=Path('data/otp')
 for name,value in [('contract-input.json',{'origin':origin,'travel':travel}),('contract-http-request.json',payload),('contract-result.json',result)]:
  (target/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
 report=json.loads((target/'connection-report.json').read_text(encoding='utf-8'))
 report.update(routing_api_verified=result['status']=='ok',contract_test_status='passed' if result['status']=='ok' else 'failed',route_status=result['status'],checked_at=datetime.now(timezone.utc).isoformat(),otp_version=json.loads((target/'server.json').read_text(encoding='utf-8'))['data']['serverInfo']['version'])
 report['reason']='Real coordinate route validated from the backend Python environment' if result['status']=='ok' else 'A real routing contract was attempted; see stored response.'
 (target/'connection-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 if result['status']=='ok':
  profile={'base_url':settings.base_url,'api_path':settings.api_path,'api_type':settings.api_type,'routing_api_verified':True,'supported_modes':settings.supported_modes,'graph_version':None,'schedule_basis':'unknown','otp_version':report['otp_version'],'verified_at':report['checked_at'],'routing_query':TRANSMODEL_QUERY,'transfer_count_available':False,'evidence':['connection-report.json','introspection.json','contract-http-request.json','contract-result.json']}
  (target/'api-profile.json').write_text(json.dumps(profile,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({'status':result['status'],'count':len(result.get('itineraries',[])),'raw_errors':raw.get('errors'),'invalid':result.get('invalid_itineraries'),'date':date,'modes':travel['modes']},ensure_ascii=True))
asyncio.run(main())
