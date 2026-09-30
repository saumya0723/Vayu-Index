import json,re,secrets,time
from fastapi.responses import JSONResponse
from .config import API_VERSION
BASE={'/api/v1/health':set(),'/api/v1/status':set(),'/api/v1/metadata':set(),'/api/v1/frontend-data':set(),'/api/v1/cpi-comparison':set(),'/api/v1/collection/live':set(),'/api/v1/index':{'route','variant','start','end','limit','offset'},'/api/v1/index/latest':{'variant'},'/api/v1/index/history':{'variant','start','end','limit','offset'},'/api/v1/index/period':{'variant','grain','period_id','limit','offset'},'/api/v1/index/coverage':{'variant','round_id'},'/api/v1/routes':{'coverage_status','route','limit','offset'},'/api/v1/fares':{'route','fare_class','apw','start','end','limit','offset'},'/api/v1/lead-time':{'route','apw','limit','offset'},'/api/v1/data-quality':{'variant'},'/api/v1/sources':set(),'/api/v1/collection/status':set(),'/api/v1/backtest/status':set(),'/api/v1/anomalies':{'severity','rule_id','route_id','recommended_review','limit','offset'},'/api/v1/exports':set(),'/api/v1/methodology':{'phase'},'/dashboard':set(),'/dashboard/phase14':set(),'/':set()}
async def controls(request,call_next):
 request.state.request_id='REQ14::'+secrets.token_hex(12)
 if request.method not in {'GET','HEAD','OPTIONS'}:return JSONResponse(status_code=405,content={'error':{'error_code':'METHOD_NOT_ALLOWED','message':'Only read-only methods are supported.','details':{},'request_id':request.state.request_id,'api_version':API_VERSION}})
 path=request.url.path;allowed=BASE.get(path)
 if re.fullmatch(r'/api/v1/routes/[A-Z]{3}-[A-Z]{3}',path):allowed={'variant'}
 if re.fullmatch(r'/api/v1/routes/[A-Z]{3}-[A-Z]{3}/history',path):allowed={'fare_class','apw','start','end','limit','offset'}
 if re.fullmatch(r'/api/v1/exports/[a-z-]+',path):allowed={'format','variant','route_id','grain','period_id','round_id','severity','rule_id','coverage_status','start','end','fare_class','apw'}
 unknown=sorted(set(request.query_params)-(allowed or set())) if allowed is not None else []
 if unknown:return JSONResponse(status_code=422,content={'error':{'error_code':'INVALID_PARAMETER','message':'Unknown query parameters are not accepted.','details':{'parameters':unknown},'request_id':request.state.request_id,'api_version':API_VERSION}})
 response=await call_next(request);response.headers['X-Request-ID']=request.state.request_id;response.headers['Cache-Control']='no-store';response.headers['X-Content-Type-Options']='nosniff';return response
