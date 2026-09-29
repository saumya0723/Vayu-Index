"""Independent acceptance verifier for VAYU Phase 12."""
from __future__ import annotations
import csv, hashlib, re, sys
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from src.backtesting import backtest_engine as E
from src.backtesting import rules as R
EXPECTED_HASHES = {'data/official/dgca/processed/dgca_city_pair_passenger_traffic_2024_25.csv': 'c963bcb22f8334d254e668c252cca8ad5f491b60ea9ed801184ff6b363623631',
 'data/official/dgca/processed/dgca_processed_metadata.json': '1130387300cee060d7cc5b91edbabf38ab29ee909e903b08579e291f5badc92f',
 'data/official/dgca/processed/metadata.json': '808c0415400789beddf0ee845cff2aaac9c88037106986759c774b0b6433be21',
 'data/official/dgca/processed/route_basket_metadata.json': '5f8c54637dc57bb961805f617189403e66556ecb026300e83ac4f4bacf3f32cb',
 'data/official/dgca/processed/vayu_route_basket_2024_25.csv': 'dc57e6d470a2ed9061dd82a92c84943749c3c648cef00b85b3f250df2f87c181',
 'data/official/mospi/processed/metadata.json': 'da679637ab3c4740d42e49b15e2fa59ad842be94bd944b658c7a8cb1619df37e',
 'data/official/mospi/processed/mospi_airfare_cpi.csv': 'ff7c7224a0fda4b4d811ec4ba3a9fbad8f93aebd90c929eee07888637b429088',
 'outputs/anomaly_flagged_airfare_observations.csv': '10a2d4014f78136b6ce87b7d964e210d39fccbb4812bfa520ca4524c1b21c237',
 'outputs/canonical_airfare_observations.csv': '1223c7b15e7a2eec4798565f9d5013085e8cb3c64b82c17dca9f5375178c488c',
 'outputs/consolidated_airfare_observations.csv': '792be83e1a36165388e397dcf8b1ee27f82a665276c7b2a1cf167b80cc108e80',
 'outputs/deduplicated_airfare_observations.csv': '6c51ea30d1728d959afdd91c1fea3fc6f2524c8b49875ecfea7791cf79a0a7d9',
 'outputs/dgca_route_exclusions.csv': 'ea62e5664cf10d617a97f16e901f0e8dc83be46776135652a6d6352be6e5df21',
 'outputs/dgca_route_traffic_ranking.csv': '2ba4486b46585d28e6c6cec621752194abed63e509ff5304c795afb0c12c4ad0',
 'outputs/edge_case_audit_report.csv': 'e9e5c6a7d5bba1a0342ca7b8f0ca46fda86a91f7c37f4f2ddefd82e60ba169f8',
 'outputs/normalized_airfare_observations.csv': '6b38396718c64f102a6f670d64d36ac4f4bc8c5f9f9bd679152e59c9de0d0407',
 'outputs/normalized_observation_map.csv': '5e3555fe804be0c52fc1cd93fb3f7479fdbf4d78803ac4e9f02e15a26b285703',
 'outputs/phase10_coverage_report.csv': '1a940b3b80f55a60d6fc7ad0bde329d4746f071eab80da1923e58f5aa0a1a465',
 'outputs/phase10_off_basket_route_class_round_series.csv': '09170b58ff440daebfc43944e7e89a03630eb630fa6b1247faaa9cca8d39b4b9',
 'outputs/phase10_off_basket_route_series.csv': '1d0c891d3248e8fa56efcb6fc1e28a58390afdad06797b290081adabb5f8d4e1',
 'outputs/phase10_route_class_round_series.csv': '29750c4612a8385227cf589fa9156b04d8f2421e745def563b936c8f00c4f25f',
 'outputs/phase10_route_crosswalk.csv': 'caf21437ce0ee8f2c0d391cdc57aac001d40d02b67a93b439aa20b95e38f9cc7',
 'outputs/phase10_route_lineage_map.csv': 'adff7c01570dfc5d13039126b00b488b2b23c23e6ff666f3fd5061aaf114e73e',
 'outputs/phase10_route_series.csv': '877bd3a2d99658362853a48272a267e9c9e60e793c57b220d9c1297b6da005e1',
 'outputs/phase11_index_coverage_report.csv': '3ece58dbbb101338a786ef469ab6f14a421d2c355526d0bdf52e678463d82e2f',
 'outputs/phase11_index_lineage_map.csv': 'f4e6ece8bde8d61706744758b86e2f305f523fc9f74784d41982931e46d9b6f3',
 'outputs/phase11_item_price_relatives.csv': '5511bf34e9fbcef4e7e7c0e9d0dbc46b34c8071b986fef7b433e7dd6a5b6a969',
 'outputs/phase11_period_index.csv': '1b8b758623bf7586475e389fda6cf2979a40ed31975c5ddc3fb03903bd1d2ccd',
 'outputs/phase11_round_index.csv': 'c2096ae3405e456e6f0be6a9c7fccf84e0e825db5706986feab20a051ea18452',
 'outputs/phase11_route_index_components.csv': '1d3d58d34a4e08bc1b0dce979810b7845aa01226db5bbda2823d55d41d4d6ef1',
 'outputs/phase11_unaligned_round_diagnostics.csv': '1063c982f2cb6c4993f171b10cb21c98d7d9024a14ec327b36b2249f014489b2',
 'outputs/phase6_duplicate_audit_report.csv': '86afc9b8378ddd127d10002537669ae263da5f7dca86548aaca84a32f8d14030',
 'outputs/phase7_flight_cell_report.csv': 'fa7569ecd9463c15e41e4ba13db8e14e1198c34ccaf0b8366730115b7f67447f',
 'outputs/phase7_observation_map.csv': 'e4717e8f16d1b68ef8119e7708f1af7f6134ef2b3cf13c5185b74a04a93350c8',
 'outputs/phase8_flight_cell_normalized.csv': '60d81222c425c5d2c40d4bc2e5c64bb77cc13610e4b6b7fb198508ad56ab33fa',
 'outputs/phase8_normalization_report.csv': '3affd800130bd6deb9d19b66445a40919a97c62fad61c1e3c509bf44b53b6722',
 'outputs/phase9_anomaly_report.csv': 'c57dfee87024130af82b70083a51b5ce1e0dddabb39c69e9cbe91fbdb0396314',
 'outputs/phase9_observation_anomaly_map.csv': '3a2dc942d8964fcca1d22c12c420d63700b310964904677791388f30b2127181',
 'outputs/phase9_series_diagnostics.csv': '8bf0d974bf5ab22b6d414c315fb577320a79539432b567083263127a90ca8e85',
 'outputs/phase9_source_reliability_report.csv': 'dce11b19b44fac340a8e50de774315a4d9d8c49a14cfc7d0a72345c82d0a081b',
 'outputs/validated_airfare_observations.csv': 'f1220617f380f645b8cb21dc4e8e93a069d17a5b8333835558df33e0b43cf45b'}

class Checker:
    def __init__(self): self.passed=0; self.failed=0
    def check(self, condition, label):
        if condition:
            self.passed += 1; print('PASS',label)
        else:
            self.failed += 1; print('FAIL',label)

def read(name): return E.read_csv(ROOT/'outputs'/name)
def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    c=Checker()
    for relative,expected in sorted(EXPECTED_HASHES.items()):
        c.check(digest(ROOT/relative)==expected,'protected hash '+relative)
    for name,columns in R.OUTPUT_SCHEMAS.items():
        path=ROOT/'outputs'/name
        c.check(path.exists(),'output exists '+name)
        with path.open('r',encoding='utf-8',newline='') as handle: header=tuple(next(csv.reader(handle)))
        c.check(header==tuple(columns),'schema '+name)
    summary=read('phase12_backtest_summary.csv')
    c.check(len(summary)==1,'summary row count')
    s=summary[0]
    c.check(s['backtest_status']=='PROTOTYPE_BACKTEST','prototype status')
    c.check(s['production_status']=='PRODUCTION_BACKTEST_REQUIRED','production required')
    c.check(s['vayu_complete_month_count']=='0','zero complete VAYU months')
    c.check(s['reference_period_count']=='19','nineteen MoSPI months')
    c.check(s['overlapping_level_count']=='0','zero overlap')
    c.check(s['overall_evaluation_status']=='NO_OVERLAPPING_COMPLETE_PERIODS','no-overlap status')
    comparisons=read('phase12_period_comparison.csv')
    c.check(len(comparisons)==20,'period union row count')
    september=[x for x in comparisons if x['period_id']=='2026-09'][0]
    c.check(september['vayu_round_count']=='9' and september['vayu_expected_round_count']=='90','September 9/90')
    c.check(september['period_exclusion_reason']=='PARTIAL_MONTH_EXCLUDED_FROM_REFERENCE_COMPARISON','partial month excluded')
    c.check(september['reference_original_level']=='','no nearest reference value')
    c.check(not any(x['period_id']=='2026-08' for x in comparisons),'no interpolation')
    metrics=read('phase12_metric_report.csv')
    c.check(len(metrics)==17,'metric row count')
    c.check(all(x['metric_status']=='INSUFFICIENT_SAMPLE' for x in metrics),'all metrics insufficient')
    c.check(all(x['metric_value']=='' for x in metrics),'blocked metric values blank')
    c.check(all(x['insufficient_sample_reason']=='NOT_APPLICABLE_NO_OVERLAP' for x in metrics if x['metric_id'].startswith('MET-LAG')),'lead lag not applicable')
    refs=read('phase12_reference_metadata.csv')
    c.check(len(refs)==2,'reference metadata row count')
    c.check(sum(x['valid_comparison_target']=='True' for x in refs)==1,'one valid price target')
    dgca=[x for x in refs if x['reference_series_id']==R.REFERENCE_DGCA][0]
    c.check(dgca['invalid_use_codes']=='INVALID_REFERENCE_TYPE_TRAFFIC_NOT_PRICE','DGCA rejected as price')
    mospi=E.read_csv(ROOT/'data/official/mospi/processed/mospi_airfare_cpi.csv')
    levels={x['period'][:7]:Decimal(x['cpi_index']) for x in mospi}
    inflation_ok=True; inflation_count=0
    for x in mospi:
        if x['inflation']:
            prior=f"{int(x['period'][:4])-1:04d}"+x['period'][4:7]
            expected=(Decimal('100')*(Decimal(x['cpi_index'])/levels[prior]-Decimal('1'))).quantize(Decimal('0.01'),rounding=ROUND_HALF_UP)
            inflation_ok=inflation_ok and abs(expected-Decimal(x['inflation']))<=Decimal('0.01'); inflation_count += 1
    c.check(inflation_ok and inflation_count==7,'MoSPI inflation consistency')
    sensitivities=read('phase12_sensitivity_report.csv')
    c.check(len(sensitivities)==45,'sensitivity row count')
    for policy in ('SENS-COV-01','SENS-COV-02','SENS-COV-03','SENS-COV-04'):
        subset=[x for x in sensitivities if x['alternative_method_id']==policy]
        c.check(len(subset)==9,'nine rounds '+policy)
        c.check(all(x['diagnostic_only']=='True' for x in subset),'diagnostic only '+policy)
    logrows=[x for x in sensitivities if x['alternative_method_id']=='SENS-COV-03']
    c.check(all(x['alternative_index_level']=='' for x in logrows),'no counterfactual full-basket index')
    low=[x for x in sensitivities if x['alternative_method_id']=='SENS-COV-04']
    c.check(all(x['sensitivity_status']=='EXCLUDED_LOW_COVERAGE' for x in low),'80 percent gate excludes all')
    anomaly=[x for x in sensitivities if x['sensitivity_type']=='ANOMALY']
    c.check(len(anomaly)==9 and all(x['level_difference']=='0.000000' for x in anomaly),'anomaly sensitivity equality')
    c.check(all('UNALIGNED' in x['corpus_disclosure'] for x in anomaly),'anomaly corpus artefact disclosed')
    coverage=read('phase12_coverage_report.csv')
    c.check(len(coverage)==540,'coverage row count')
    c.check(len({x['route_id'] for x in coverage})==15,'locked fifteen routes')
    c.check({x['basket_routes_observed'] for x in coverage}=={'2'},'two observed routes')
    c.check({x['basket_weight_represented'] for x in coverage}=={'0.273706'},'represented weight')
    c.check({x['basket_weight_missing'] for x in coverage}=={'0.726294'},'missing weight')
    lineage=read('phase12_backtest_lineage.csv')
    c.check(len(lineage)==385,'lineage row count')
    metric_ids={x['metric_record_id'] for x in lineage}
    c.check(all(x['metric_record_id'] in metric_ids for x in metrics),'blocked metric lineage')
    c.check(all(sum(1 for y in lineage if y['metric_record_id']==x['metric_record_id'] and y['input_role']=='REFERENCE_UNPAIRED_ROW')==19 for x in metrics),'all unpaired references traced')
    sensitivity_ids={x['sensitivity_record_id'] for x in lineage}
    c.check(all(x['sensitivity_record_id'] in sensitivity_ids for x in sensitivities),'sensitivity lineage')
    c.check(any(x['period_id']=='2026-09' and x['input_role']=='VAYU_BLOCKED_PARTIAL_MONTH' for x in lineage),'partial month lineage')
    gate=read('phase12_thirty_day_gate.csv')
    c.check(len(gate)==10,'ten production gates')
    c.check(any(x['gate_status']=='FAIL' for x in gate),'production gate failed')
    c.check([x for x in gate if x['gate_id']=='GATE-10'][0]['failure_reason']=='SYNTHETIC_CORPUS','real data gate')
    phase12_source='\n'.join((ROOT/p).read_text(encoding='utf-8') for p in ('src/backtesting/rules.py','src/backtesting/backtest_engine.py','scripts/run_backtesting.py'))
    lower=phase12_source.lower()
    for token in ('sklearn','tensorflow','import random','numpy.random','index_eligible','from src.index_engine','from src.route_aggregation'):
        c.check(token not in lower,'banned token '+token)
    c.check(('float'+'(') not in phase12_source,'no binary float constructor')
    c.check(re.search(r'\brow\.[A-Za-z_]',phase12_source) is None,'no row attribute access')
    before={name:digest(ROOT/'outputs'/name) for name in R.OUTPUT_SCHEMAS}
    protected_before=E.protected_hashes(ROOT)
    E.run_backtest(ROOT)
    after={name:digest(ROOT/'outputs'/name) for name in R.OUTPUT_SCHEMAS}
    c.check(before==after,'deterministic byte-stable outputs')
    c.check(protected_before==E.protected_hashes(ROOT),'runtime upstream immutability')
    print(f'PHASE12_VERIFIER passed={c.passed} failed={c.failed}')
    return 0 if c.failed==0 else 1
if __name__=='__main__': raise SystemExit(main())
