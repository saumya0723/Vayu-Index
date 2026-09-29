from dataclasses import dataclass
@dataclass(frozen=True)
class Publication:path:str;schema:str|None;classification:str
PUBLICATIONS={
'basket':Publication('data/official/dgca/processed/vayu_route_basket_2024_25.csv',None,'PUBLISHED'),
'route_coverage':Publication('outputs/phase10_coverage_report.csv','phase10-v1','PUBLISHED'),'route_history':Publication('outputs/phase10_route_series.csv','phase10-v1','PUBLISHED'),'route_lineage':Publication('outputs/phase10_route_lineage_map.csv','phase10-v1','INTERNAL'),
'round_index':Publication('outputs/phase11_round_index.csv','phase11-v1','PUBLISHED'),'period_index':Publication('outputs/phase11_period_index.csv','phase11-v1','PUBLISHED'),'index_coverage':Publication('outputs/phase11_index_coverage_report.csv','phase11-v1','PUBLISHED'),'route_components':Publication('outputs/phase11_route_index_components.csv','phase11-v1','DIAGNOSTIC'),
'anomalies':Publication('outputs/phase9_anomaly_report.csv','phase9-v1','DIAGNOSTIC'),
'collection_run':Publication('outputs/phase13_collection_run_report.csv','phase13-v1','DIAGNOSTIC'),'source_compliance':Publication('outputs/phase13_compliance_registry.csv','phase13-v1','DIAGNOSTIC'),'source_coverage':Publication('outputs/phase13_source_coverage.csv','phase13-v1','DIAGNOSTIC'),'route_collection_coverage':Publication('outputs/phase13_route_coverage.csv','phase13-v1','DIAGNOSTIC'),'round_collection_coverage':Publication('outputs/phase13_round_coverage.csv','phase13-v1','DIAGNOSTIC'),
'backtest_summary':Publication('outputs/phase12_backtest_summary.csv','phase12-v1','DIAGNOSTIC'),'backtest_metrics':Publication('outputs/phase12_metric_report.csv','phase12-v1','DIAGNOSTIC'),'backtest_references':Publication('outputs/phase12_reference_metadata.csv','phase12-v1','DIAGNOSTIC'),'backtest_gates':Publication('outputs/phase12_thirty_day_gate.csv','phase12-v1','DIAGNOSTIC')}
PUBLICATIONS.update({
'validated_observations':Publication('outputs/validated_airfare_observations.csv',None,'DIAGNOSTIC'),
'mospi_cpi':Publication('data/official/mospi/processed/mospi_airfare_cpi.csv',None,'PUBLISHED')})
EXPORTS=('latest-index','index-history','index-periods','index-coverage','routes','route-history','anomalies','collection-status','source-compliance','backtest-summary','backtest-metrics','production-gates')
VERSIONS={'route':'phase10-v1','index':'phase11-v1','backtest':'phase12-v1','collection':'phase13-v1'}
