import csv,io,json,re
from ..catalog import EXPORTS
from ..config import DATA_STATUS,OFFICIAL_STATUS,COLLECTION_STATUS
from ..errors import APIError
def nullable(v):return None if v in ('',None) else v
def page(rows,limit,offset):
 rows=list(rows);items=rows[offset:offset+limit];return {'items':items,'page':{'limit':limit,'offset':offset,'returned':len(items),'total':len(rows),'next_offset':offset+limit if offset+limit<len(rows) else None}}
def latest(s,variant='PRIMARY'):
 rows=[r for r in s.tables['round_index'] if r['series_variant']==variant]
 if not rows:raise APIError(404,'INDEX_NOT_FOUND','Index variant unavailable.')
 r=max(rows,key=lambda x:(x['round_sort_key'],int(x['link_sequence'])))
 return {'series_variant':r['series_variant'],'index_series_id':r['index_series_id'],'collection_round_id':r['collection_round_id'],'timestamp':r['round_sort_key'],'base_round_id':r['base_round_id'],'base_level':r['index_base_level'],'index_level':r['index_level'],'change_pct_vs_previous_round':nullable(r['index_change_pct_vs_prev_round']),'routes_represented':int(r['basket_routes_represented']),'routes_total':int(r['basket_routes_total']),'basket_weight_represented':r['basket_weight_represented'],'basket_coverage_pct':r['basket_coverage_pct'],'coverage_status':r['coverage_status'],'data_status':DATA_STATUS,'schema_version':r['phase11_schema_version']}
def history(s,variant='PRIMARY'):return [dict(r) for r in s.tables['round_index'] if r['series_variant']==variant]
from .route_catalog import get_enriched_routes
def routes(s, request=None):
 return get_enriched_routes(s, request=request)
def collection(s):
 r=s.tables['collection_run'][-1];sources=s.tables['source_compliance']
 return {'run_id':r['run_id'],'run_mode':r['run_mode'],'run_status':r['run_status'],'live_collection_status':COLLECTION_STATUS,'real_collection_started':False,'source_count':len(sources),'authorized_source_count':sum(x['authorization_status']=='APPROVED' for x in sources),'blocked_source_count':sum(x['allowed_automation']!='True' for x in sources),'attempt_count':int(r['attempt_count']),'success_count':int(r['success_count']),'failure_count':int(r['failure_count']),'compliance_block_count':int(r['compliance_block_count']),'observation_count':int(r['observation_count']),'source_coverage':[dict(x) for x in s.tables['source_coverage']]}
def backtest(s):
 r=s.tables['backtest_summary'][0];metrics=[]
 for x in s.tables['backtest_metrics']:y=dict(x);y['metric_value']=nullable(y['metric_value']);metrics.append(y)
 return {'backtest_status':r['backtest_status'],'production_status':r['production_status'],'reference_series_id':r['reference_series_id'],'overlap_status':r['overall_evaluation_status'],'complete_vayu_month_count':int(r['vayu_complete_month_count']),'reference_period_count':int(r['reference_period_count']),'metrics':metrics,'production_gates':[dict(x) for x in s.tables['backtest_gates']]}
def metadata(s):return {'snapshot_id':s.identity,'snapshot_loaded_at':s.loaded_at,'publication_timestamp':s.publication_timestamp,'data_status':DATA_STATUS,'official_status':OFFICIAL_STATUS,'is_real_market_collection':False,'collection_status':COLLECTION_STATUS,'basket_sha256':s.records['basket']['sha256']}
def export_rows(s,name,params):
 variant=params.get('variant','PRIMARY');mapping={'latest-index':lambda:[latest(s,variant)],'index-history':lambda:history(s,variant),'index-periods':lambda:[dict(x) for x in s.tables['period_index'] if x['series_variant']==variant],'index-coverage':lambda:[dict(x) for x in s.tables['index_coverage'] if x['series_variant']==variant],'routes':lambda:routes(s),'route-history':lambda:[dict(x) for x in s.tables['route_history'] if x['route_id']==params.get('route_id')],'anomalies':lambda:[dict(x) for x in s.tables['anomalies']],'collection-status':lambda:[collection(s)],'source-compliance':lambda:[dict(x) for x in s.tables['source_compliance']],'backtest-summary':lambda:[dict(s.tables['backtest_summary'][0])],'backtest-metrics':lambda:[dict(x) for x in s.tables['backtest_metrics']],'production-gates':lambda:[dict(x) for x in s.tables['backtest_gates']]}
 if name not in mapping:raise APIError(404,'EXPORT_NOT_FOUND','Requested export unavailable.')
 return mapping[name]()
def render(rows,kind,meta):
 if kind=='json':return json.dumps({'meta':meta,'data':rows},sort_keys=True,separators=(',',':'))+'\\n','application/json'
 b=io.StringIO(newline='');fields=list(rows[0]) if rows else [];writer=csv.DictWriter(b,fieldnames=fields,lineterminator='\\n');writer.writeheader();writer.writerows(rows);return b.getvalue(),'text/csv'
