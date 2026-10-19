#!/usr/bin/env python3
"""Run actual S3 Prometheus rules in promtool; local disposable Docker only."""
import importlib.util
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('alerts', ROOT / 'scripts/verify-log-loss-alerts.py')
HELPERS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HELPERS)


def scenarios():
    base = [{'series': 'kube_deployment_spec_replicas{namespace="storage",deployment="seaweedfs-s3"}', 'values': '2+0x20'}]
    for pod in ['s3-a', 's3-b']:
        for name, labels, values in [
            ('up', 'service="seaweedfs-s3",endpoint="s3-metrics"', '1+0x20'),
            ('up', 'container="read-probe",job="storage/seaweedfs-s3-read-probe"', '1+0x20'),
            ('seaweedfs_s3_read_probe_last_completed_timestamp_seconds', '', '1+30x20'),
            ('seaweedfs_s3_read_probe_consecutive_failures', '', '0+0x20'),
            ('SeaweedFS_s3_request_total', 'service="seaweedfs-s3",type="GET",code="503",bucket="fixture"', '0+0x20'),
        ]:
            base.append({'series': name + '{namespace="storage",pod="' + pod + '"' + (',' + labels if labels else '') + '}', 'values': values})
    tests = []
    names = ['SeaweedFSS3Read5xx', 'SeaweedFSS3ReadProbeFailed', 'SeaweedFSS3MonitoringUnavailable']

    def case(name, series, expected, at='6m'):
        tests.append({'name': name, 'interval': '30s', 'input_series': series,
                      'promql_expr_test': [{'expr': 'count(ALERTS{alertname="' + alert + '",alertstate="firing"}) or vector(0)',
                          'eval_time': at, 'exp_samples': [{'labels': '{}', 'value': expected.get(alert, 0)}]} for alert in names]})

    def change(metric, values, match=''):
        return [dict(x, values=values) if x['series'].startswith(metric + '{') and 'pod="s3-a"' in x['series'] and match in x['series'] else dict(x) for x in base]

    case('healthy', base, {})
    case('two-failed-reads', change('seaweedfs_s3_read_probe_consecutive_failures', '0 1 2+0x18'), {'SeaweedFSS3ReadProbeFailed': 1}, '1m')
    case('one-failed-read', change('seaweedfs_s3_read_probe_consecutive_failures', '1+0x20'), {})
    case('probe-recovery', change('seaweedfs_s3_read_probe_consecutive_failures', '2+0x3 0+0x16'), {})
    case('repeated-5xx', change('SeaweedFS_s3_request_total', '0+1x20'), {'SeaweedFSS3Read5xx': 1})
    successful = [dict(x, series=x['series'].replace('code="503"', 'code="200"')) for x in change('SeaweedFS_s3_request_total', '0+1x20')]
    case('successful-GETs-do-not-fire', successful, {})
    writes = [dict(x, series=x['series'].replace('type="GET"', 'type="PUT"')) for x in change('SeaweedFS_s3_request_total', '0+1x20')]
    case('write-5xx-is-not-counted-as-read', writes, {})
    case('5xx-pending', change('SeaweedFS_s3_request_total', '0+1x20'), {}, '1m')
    for labels in ['endpoint="s3-metrics"', 'container="read-probe"']:
        case('target-down-' + labels, change('up', '0+0x20', labels), {'SeaweedFSS3MonitoringUnavailable': 1})
    case('probe-stalled', change('seaweedfs_s3_read_probe_last_completed_timestamp_seconds', '1+0x20'), {'SeaweedFSS3MonitoringUnavailable': 1})
    for metric in ['up', 'seaweedfs_s3_read_probe_last_completed_timestamp_seconds', 'seaweedfs_s3_read_probe_consecutive_failures']:
        case('missing-' + metric, [x for x in base if not (x['series'].startswith(metric + '{') and 'pod="s3-a"' in x['series'])], {'SeaweedFSS3MonitoringUnavailable': 1})
    case('desired-count-absent', base[1:], {'SeaweedFSS3MonitoringUnavailable': 1})
    duplicate = {'series': 'up{namespace="storage",service="seaweedfs-s3",endpoint="s3-metrics",pod="s3-b",instance="duplicate"}', 'values': '1+0x20'}
    case('duplicate-cannot-hide-missing-gateway', [x for x in base if not (x['series'].startswith('up{') and 'pod="s3-a"' in x['series'] and 's3-metrics' in x['series'])] + [duplicate], {'SeaweedFSS3MonitoringUnavailable': 1})
    case('all-telemetry-absent', base[:1], {'SeaweedFSS3MonitoringUnavailable': 1})
    return tests


def main():
    with tempfile.TemporaryDirectory(prefix='anton-s3-alerts-') as directory:
        root = Path(directory)
        rules = HELPERS.document('kubernetes/apps/storage/seaweedfs-config/app/s3-read-alerts.yaml')['spec']
        HELPERS.save(root / 'rules.json', rules)
        tests = scenarios()
        HELPERS.save(root / 'tests.json', {'rule_files': ['/test/rules.json'], 'evaluation_interval': '30s', 'tests': tests})
        for command in [('check', 'rules', '/test/rules.json'), ('test', 'rules', '/test/tests.json')]:
            print(HELPERS.run('docker', 'run', '--rm', '-v', str(root) + ':/test:ro', '--entrypoint', '/bin/promtool', HELPERS.PROM, *command), flush=True)
        print(str(len(tests)) + ' native S3 alert scenarios passed', flush=True)


if __name__ == '__main__':
    main()
