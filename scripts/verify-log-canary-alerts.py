#!/usr/bin/env python3
"""Exercise the deployed canary rules in real Prometheus; no cluster access."""
import importlib.util
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('alerts', ROOT / 'scripts/verify-log-loss-alerts.py')
helpers = importlib.util.module_from_spec(spec); spec.loader.exec_module(helpers)


def scenarios():
    base = [{'series': 'kube_daemonset_status_desired_number_scheduled{namespace="observability",daemonset="loki-canary"}', 'values': '3+0x80'}]
    for pod in ['canary-0', 'canary-1', 'canary-2']:
        for name, values in [('up','1+0x80'), ('log_canary_written_total','0+1x80'),
                             ('log_canary_oldest_unconfirmed_age_seconds','0+0x80'),
                             ('log_canary_last_emission_timestamp_seconds','0+15x80'),
                             ('log_canary_last_successful_query_timestamp_seconds','0+15x80')]:
            base.append({'series': name + '{namespace="observability",service="loki-canary",pod="' + pod + '"}', 'values': values})
        base.append({'series': 'kube_pod_owner{namespace="observability",pod="' + pod + '",owner_kind="DaemonSet",owner_name="loki-canary"}', 'values': '1+0x80'})
    tests = []
    names = ['LokiCanaryMissingLogs','LokiCanaryDeliveryStalled','LokiCanaryCoverageMissing']
    def case(name, series, at, expected):
        tests.append({'name': name, 'interval': '15s', 'input_series': series,
                      'promql_expr_test': [{'expr': 'count(ALERTS{alertname="'+alert+'",alertstate="firing"}) or vector(0)',
                          'eval_time': at, 'exp_samples': [{'labels': '{}','value': expected.get(alert,0)}]} for alert in names]})
    def change(metric, values):
        return [dict(x,values=values) if x['series'].startswith(metric+'{') and 'pod="canary-0"' in x['series'] else dict(x) for x in base]
    case('healthy',base,'10m',{})
    age='log_canary_oldest_unconfirmed_age_seconds'
    case('missing-id-fires-in-210-seconds',change(age,'0+15x80'),'3m30s',{'LokiCanaryMissingLogs':1})
    case('missing-id-pending-before-deadline',change(age,'0+15x80'),'3m15s',{})
    case('recovered-before-deadline',change(age,'0+15x11 0+0x68'),'4m',{})
    case('already-late-first-scrape',change(age,'200+15x80'),'15s',{'LokiCanaryMissingLogs':1})
    case('late-record-eventually-resolves',change(age,'0+15x16 0+0x63'),'5m',{})
    for metric in ['log_canary_last_emission_timestamp_seconds','log_canary_last_successful_query_timestamp_seconds']:
        case(metric+'-stalled',change(metric,'0+0x80'),'3m30s',{'LokiCanaryDeliveryStalled':1})
        case(metric+'-short-overlap',change(metric,'0+15x7 105+0x3 165+15x68'),'4m45s',{})
    for metric in ['up','log_canary_written_total',age]:
        remaining=[x for x in base if not (x['series'].startswith(metric+'{') and 'pod="canary-0"' in x['series'])]
        case(metric+'-coverage-missing',remaining,'1m15s',{'LokiCanaryCoverageMissing':1})
    case('all-probes-missing',base[:1],'1m15s',{'LokiCanaryCoverageMissing':1})
    case('daemonset-absent',base[1:],'1m15s',{'LokiCanaryCoverageMissing':1})
    orphan=[{'series': x['series'].replace('canary-0','control'), 'values': x['values']} for x in base if 'pod="canary-0"' in x['series'] and not x['series'].startswith('kube_pod_owner')]
    case('unowned-test-probe-cannot-mask-node-gap', [x for x in base if 'pod="canary-0"' not in x['series']]+orphan,'1m15s',{'LokiCanaryCoverageMissing':1})
    duplicate={'series':'up{namespace="observability",service="loki-canary",pod="canary-1",instance="duplicate"}','values':'1+0x80'}
    case('duplicate-scrape-cannot-mask-node-gap',[x for x in base if 'pod="canary-0"' not in x['series']]+[duplicate],'1m15s',{'LokiCanaryCoverageMissing':1})
    return tests


def main():
    with tempfile.TemporaryDirectory(prefix='anton-canary-rules-') as directory:
        root=Path(directory)
        rules=helpers.document('kubernetes/apps/observability/loki/app/canary-prometheusrule.yaml')['spec']
        helpers.save(root/'rules.json',rules)
        tests=scenarios();helpers.save(root/'tests.json',{'rule_files':['/test/rules.json'],'evaluation_interval':'15s','tests':tests})
        for command in [('check','rules','/test/rules.json'),('test','rules','/test/tests.json')]:
            print(helpers.run('docker','run','--rm','-v',str(root)+':/test:ro','--entrypoint','/bin/promtool',helpers.PROM,*command),flush=True)
        print(str(len(tests))+' native canary alert scenarios passed',flush=True)


if __name__=='__main__':main()
