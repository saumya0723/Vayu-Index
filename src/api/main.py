from contextlib import asynccontextmanager
import asyncio
from pathlib import Path
import time
from fastapi import FastAPI,Request,Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse,Response,HTMLResponse,RedirectResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment,FileSystemLoader,select_autoescape
from .catalog import VERSIONS,EXPORTS
from .config import Settings,API_PREFIX,API_VERSION,SCHEMA_VERSION,DATA_STATUS,OFFICIAL_STATUS
from .errors import APIError
from .middleware import controls
from .repository import Repository
from .snapshot import Snapshot
from .services.core import *
from .services.frontend_compat import canonical_route_id, data_quality_summary, fare_rows, frontend_data, lead_time_rows, route_index
from .services.cpi_comparison import compare_cpi
from ..collection.skyscanner_live import prune_expired as prune_expired_live_collection
from ..collection.skyscanner_live import readiness as live_collection_readiness
from ..collection.ignav_live import readiness as ignav_collection_readiness
from ..collection.serpapi_live import prune_expired as prune_expired_serpapi
from ..collection.serpapi_live import readiness as serpapi_collection_readiness
import os
import re
def create_app(root=None):
 settings=Settings.load(root);started=time.monotonic()
 @asynccontextmanager
 async def lifespan(app):
  app.state.snapshot=Snapshot.load(Repository(settings))
  prune_expired_live_collection(settings.root)
  prune_expired_serpapi(settings.root)
  async def retention_sweeper():
   while True:
    await asyncio.sleep(60)
    await asyncio.to_thread(prune_expired_live_collection,settings.root)
    await asyncio.to_thread(prune_expired_serpapi,settings.root)
  cleanup_task=asyncio.create_task(retention_sweeper())
  try:yield
  finally:
   cleanup_task.cancel()
 app=FastAPI(title='VAYU INDEX Read-Only API',version=API_VERSION,openapi_url=API_PREFIX+'/openapi.json',docs_url=API_PREFIX+'/docs',redoc_url=None,lifespan=lifespan);app.state.settings=settings;app.add_middleware(CORSMiddleware,allow_origins=list(settings.origins),allow_credentials=False,allow_methods=['GET','HEAD','OPTIONS'],allow_headers=['Accept','Content-Type','X-Request-ID']);app.middleware('http')(controls)
 def env(request,data,classification='PUBLISHED',ids=()):
  s=request.app.state.snapshot;refs=[{'path':s.records[x]['path'],'sha256':s.records[x]['sha256'],'schema_version':None} for x in ids]
  return {'meta':{'api_version':API_VERSION,'response_schema_version':SCHEMA_VERSION,'pipeline_versions':VERSIONS,'publication_timestamp':s.publication_timestamp,'data_status':DATA_STATUS,'official_status':OFFICIAL_STATUS,'is_real_market_collection':False,'publication_class':classification,'request_id':request.state.request_id,'source_files':refs},'data':data}
 @app.get(API_PREFIX+'/health')
 def health(request:Request):return env(request,{'application_status':'HEALTHY','uptime_seconds':format(time.monotonic()-started,'.6f')},'INTERNAL')
 @app.get(API_PREFIX+'/status')
 def status(request:Request):
  s=request.app.state.snapshot;b=backtest(s);c=collection(s);i=latest(s);return env(request,{'application_status':'HEALTHY','analytical_outputs_status':'AVAILABLE','schema_compatibility':'COMPATIBLE','data_status':DATA_STATUS,'collection_status':c['live_collection_status'],'index_status':'AVAILABLE_SYNTHETIC_PROTOTYPE','latest_published_index_round':i['timestamp'],'latest_collection_timestamp':None,'backtest_status':b['backtest_status'],'backtest_overlap_status':b['overlap_status'],'production_status':b['production_status'],'snapshot_id':s.identity},ids=('round_index','collection_run','backtest_summary'))
 @app.get(API_PREFIX+'/metadata')
 def meta(request:Request):return env(request,metadata(request.app.state.snapshot),ids=('basket',))
 @app.get(API_PREFIX+'/frontend-data')
 def frontend_dashboard_data(request:Request):return env(request,frontend_data(request.app.state.snapshot,request),'DIAGNOSTIC',('round_index','route_history','anomalies','validated_observations','mospi_cpi','source_coverage','backtest_summary'))
 @app.get(API_PREFIX+'/cpi-comparison')
 def cpi_comparison(request:Request):
  s=request.app.state.snapshot;return env(request,compare_cpi(s.tables['period_index'],s.tables['mospi_cpi']),'DIAGNOSTIC',('period_index','mospi_cpi','backtest_summary','backtest_metrics'))
 @app.get(API_PREFIX+'/collection/live')
 def live_collection_status(request:Request):
  serp = serpapi_collection_readiness(settings.root)
  if serp.get("status") in ("VERIFIED_CACHE_WARM", "LIVE_API_READY") or bool(os.environ.get("SERPAPI_API_KEY", "").strip()):
   return env(request,serp,'DIAGNOSTIC')
  return env(request,ignav_collection_readiness(settings.root),'DIAGNOSTIC')
 @app.get(API_PREFIX+'/collection/serpapi')
 def serpapi_live_collection_status(request:Request):return env(request,serpapi_collection_readiness(settings.root),'DIAGNOSTIC')
 @app.get(API_PREFIX+'/collection/ignav')
 def ignav_live_collection_status(request:Request):return env(request,ignav_collection_readiness(settings.root),'DIAGNOSTIC')
 @app.get(API_PREFIX+'/collection/skyscanner')
 def skyscanner_live_collection_status(request:Request):return env(request,live_collection_readiness(settings.root),'DIAGNOSTIC')
 @app.get(API_PREFIX+'/index')
 def frontend_index(request:Request,route:str|None=None,variant:str='PRIMARY',start:str|None=None,end:str|None=None,limit:int=Query(100,ge=1,le=1000),offset:int=Query(0,ge=0)):
  s=request.app.state.snapshot
  if route:return env(request,route_index(s,route,variant),ids=('round_index','route_components'))
  rows=[r for r in history(s,variant) if (not start or r['round_sort_key']>=start) and (not end or r['round_sort_key']<=end)]
  return env(request,page(rows,limit,offset),ids=('round_index',))
 @app.get(API_PREFIX+'/index/latest')
 def index_latest(request:Request,variant:str='PRIMARY'):return env(request,latest(request.app.state.snapshot,variant),ids=('round_index',))
 @app.get(API_PREFIX+'/index/history')
 def index_history(request:Request,variant:str='PRIMARY',start:str|None=None,end:str|None=None,limit:int=Query(100,ge=1,le=1000),offset:int=Query(0,ge=0)):
  rows=[r for r in history(request.app.state.snapshot,variant) if (not start or r['round_sort_key']>=start) and (not end or r['round_sort_key']<=end)];return env(request,page(rows,limit,offset),ids=('round_index',))
 @app.get(API_PREFIX+'/index/period')
 def index_period(request:Request,variant:str='PRIMARY',grain:str|None=None,period_id:str|None=None,limit:int=Query(100,ge=1,le=1000),offset:int=Query(0,ge=0)):
  rows=[dict(r) for r in request.app.state.snapshot.tables['period_index'] if r['series_variant']==variant and (not grain or r['period_grain']==grain) and (not period_id or r['period_id']==period_id)];return env(request,page(rows,limit,offset),ids=('period_index',))
 @app.get(API_PREFIX+'/index/coverage')
 def index_coverage(request:Request,variant:str='PRIMARY',round_id:str|None=None):
  s=request.app.state.snapshot;round_id=round_id or latest(s,variant)['collection_round_id'];rows=[dict(r) for r in s.tables['index_coverage'] if r['series_variant']==variant and r['collection_round_id']==round_id];return env(request,{'series_variant':variant,'collection_round_id':round_id,'routes':rows},ids=('index_coverage',))
 @app.get(API_PREFIX+'/routes')
 def route_list(request:Request,coverage_status:str|None=None,route:str|None=None,limit:int=Query(100,ge=1,le=1000),offset:int=Query(0,ge=0)):
  route_id=canonical_route_id(route) if route else None;rows=routes(request.app.state.snapshot,request);rows=[r for r in rows if (not coverage_status or r['coverage_status']==coverage_status) and (not route_id or r['route_id']==route_id)];return env(request,page(rows,limit,offset),ids=('basket','route_coverage'))
 @app.get(API_PREFIX+'/routes/{route_id}')
 def route_detail(request:Request,route_id:str,variant:str='PRIMARY'):
  if not re.fullmatch(r'[A-Z]{3}-[A-Z]{3}',route_id):raise APIError(422,'INVALID_PARAMETER','Route ID must use AAA-BBB syntax.')
  found=next((r for r in routes(request.app.state.snapshot,request) if r['route_id']==route_id),None)
  if not found:raise APIError(404,'ROUTE_NOT_FOUND','Requested basket route does not exist.')
  return env(request,found,ids=('basket','route_coverage'))
 @app.get(API_PREFIX+'/routes/{route_id}/history')
 def route_history(request:Request,route_id:str,fare_class:str|None=None,apw:str|None=None,start:str|None=None,end:str|None=None,limit:int=Query(100,ge=1,le=1000),offset:int=Query(0,ge=0)):
  rows=[dict(r) for r in request.app.state.snapshot.tables['route_history'] if r['route_id']==route_id and (not fare_class or r['fare_class']==fare_class) and (not apw or r['advance_purchase_window']==apw) and (not start or r['round_sort_key']>=start) and (not end or r['round_sort_key']<=end)];return env(request,page(rows,limit,offset),ids=('route_history',))
 @app.get(API_PREFIX+'/fares')
 def frontend_fares(request:Request,route:str|None=None,fare_class:str|None=None,apw:str|None=None,start:str|None=None,end:str|None=None,limit:int=Query(100,ge=1,le=1000),offset:int=Query(0,ge=0)):
  rows=fare_rows(request.app.state.snapshot,route,fare_class,apw,start,end);return env(request,page(rows,limit,offset),ids=('route_history',))
 @app.get(API_PREFIX+'/lead-time')
 def frontend_lead_time(request:Request,route:str|None=None,apw:str|None=None,limit:int=Query(100,ge=1,le=1000),offset:int=Query(0,ge=0)):
  rows=lead_time_rows(request.app.state.snapshot,route,apw);return env(request,page(rows,limit,offset),ids=('route_history',))
 @app.get(API_PREFIX+'/data-quality')
 def frontend_data_quality(request:Request,variant:str='PRIMARY'):
  return env(request,data_quality_summary(request.app.state.snapshot,variant),'DIAGNOSTIC',('anomalies','round_index'))
 @app.get(API_PREFIX+'/sources')
 def sources(request:Request):
  safe=('source_id','source_name','source_type','canonical_domain','collection_mode','authorization_status','robots_status','terms_review_status','allowed_automation','adapter_status','notes','phase13_schema_version');return env(request,[{k:r.get(k,'') for k in safe} for r in request.app.state.snapshot.tables['source_compliance']],'DIAGNOSTIC',('source_compliance',))
 @app.get(API_PREFIX+'/collection/status')
 def collection_status(request:Request):return env(request,collection(request.app.state.snapshot),'DIAGNOSTIC',('collection_run','source_compliance','source_coverage'))
 @app.get(API_PREFIX+'/backtest/status')
 def backtest_status(request:Request):return env(request,backtest(request.app.state.snapshot),'DIAGNOSTIC',('backtest_summary','backtest_metrics','backtest_gates'))
 @app.get(API_PREFIX+'/anomalies')
 def anomaly_list(request:Request,severity:str|None=None,rule_id:str|None=None,route_id:str|None=None,recommended_review:bool|None=None,limit:int=Query(100,ge=1,le=1000),offset:int=Query(0,ge=0)):
  rows=[dict(r) for r in request.app.state.snapshot.tables['anomalies'] if (not severity or r['severity']==severity) and (not rule_id or r['rule_id']==rule_id) and (recommended_review is None or (r['recommended_review']=='True')==recommended_review)];return env(request,page(rows,limit,offset),'DIAGNOSTIC',('anomalies',))
 @app.get(API_PREFIX+'/exports')
 def export_catalog(request:Request):return env(request,[{'export_id':x,'formats':['csv','json']} for x in EXPORTS])
 @app.get(API_PREFIX+'/exports/{export_id}')
 def export(request:Request,export_id:str,format:str='json',variant:str='PRIMARY',route_id:str|None=None,grain:str|None=None,period_id:str|None=None,round_id:str|None=None,severity:str|None=None,rule_id:str|None=None,coverage_status:str|None=None,start:str|None=None,end:str|None=None,fare_class:str|None=None,apw:str|None=None):
  if format not in {'csv','json'}:raise APIError(422,'INVALID_PARAMETER','Format must be csv or json.')
  params={k:v for k,v in locals().items() if isinstance(v,(str,int,bool))};rows=export_rows(request.app.state.snapshot,export_id,params)
  if len(rows)>settings.max_export_rows:raise APIError(413,'EXPORT_TOO_LARGE','Requested export exceeds the row limit.')
  meta=env(request,None)['meta'];body,media=render(rows,format,meta);return Response(body,media_type=media,headers={'Content-Disposition':f'attachment; filename="{export_id}.{format}"'})
 @app.get(API_PREFIX+'/methodology')
 def methodology(request:Request,phase:int|None=None):
  rows=[{'phase':9,'title':'Anomaly detection','path':'docs/anomaly_detection_methodology.md'},{'phase':10,'title':'Route aggregation','path':'docs/route_aggregation_methodology.md'},{'phase':11,'title':'Index methodology','path':'docs/index_methodology.md'},{'phase':12,'title':'Backtesting methodology','path':'docs/backtesting_methodology.md'},{'phase':13,'title':'Real airfare collection','path':'docs/real_airfare_collection_methodology.md'}];return env(request,[x for x in rows if phase is None or x['phase']==phase])
 static=settings.root/'src/dashboard/static';template=settings.root/'src/dashboard/templates/dashboard.html';app.mount('/dashboard/static',StaticFiles(directory=str(static)),name='dashboard-static');templates=Environment(loader=FileSystemLoader(str(template.parent)),autoescape=select_autoescape(('html','xml')))
 frontend=static/'vayu_frontend';frontend_pages={'index','anomaly-routes','lead-time','data-quality','cpi-validation','api'}
 def frontend_document(name):
  if name not in frontend_pages:return HTMLResponse('Not found',status_code=404)
  source=(frontend/(name+'.html')).read_text(encoding='utf-8')
  bridge='<script src="/dashboard/static/vayu-frontend-bridge.js" defer></script>'
  return HTMLResponse(source.replace('</body>',bridge+'</body>',1),headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})
 @app.get('/ui/',include_in_schema=False,response_class=HTMLResponse)
 def frontend_index_page():return frontend_document('index')
 @app.get('/ui/{page_name}.html',include_in_schema=False,response_class=HTMLResponse)
 def frontend_html_page(page_name:str):return frontend_document(page_name)
 app.mount('/ui',StaticFiles(directory=str(frontend),html=True),name='frontend')
 @app.get('/',include_in_schema=False)
 def root_redirect():return RedirectResponse('/ui/')
 @app.get('/dashboard',response_class=HTMLResponse,include_in_schema=False)
 def dashboard():return phase14_dashboard()
 @app.get('/dashboard/phase14',response_class=HTMLResponse,include_in_schema=False)
 def phase14_dashboard():return templates.get_template(template.name).render(api_prefix=API_PREFIX,dashboard_schema_version='phase14-dashboard-v1')
 @app.exception_handler(APIError)
 async def api_error(request,exc):return JSONResponse(status_code=exc.status_code,content={'error':{'error_code':exc.code,'message':exc.message,'details':exc.details,'request_id':getattr(request.state,'request_id','REQ14::unavailable'),'api_version':API_VERSION}})
 @app.exception_handler(Exception)
 async def internal(request,exc):return JSONResponse(status_code=500,content={'error':{'error_code':'INTERNAL_ERROR','message':'An internal service error occurred.','details':{},'request_id':getattr(request.state,'request_id','REQ14::unavailable'),'api_version':API_VERSION}})
 return app
app=create_app()
