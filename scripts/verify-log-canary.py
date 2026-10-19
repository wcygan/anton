#!/usr/bin/env python3
"""Rehearse canary delivery, overlapping OTel/Loki restarts, and one missing ID.

Requires Docker and yq. Uses the committed collector/canary values. No cluster
access or external notification; all local containers/networks are removed.
"""
from __future__ import annotations
import argparse
import datetime
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import urllib.parse
import uuid

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('durability', ROOT / 'scripts/verify-log-durability.py')
durability = importlib.util.module_from_spec(spec)
spec.loader.exec_module(durability)
run, get, eventually, save = durability.run, durability.get, durability.eventually, durability.save


def metric(text, name):
    return sum(float(line.rsplit(' ', 1)[1]) for line in text.splitlines()
               if line.startswith(name + ' ') or line.startswith(name + '{'))



def canary_document():
    return json.loads(run('yq', '-o=json', 'select(.kind == "DaemonSet")',
                          str(ROOT / 'kubernetes/apps/observability/loki/app/canary.yaml')))


def negative_control(name):
    """Render a Job-owned, bounded probe that withholds exactly its first record."""
    rendered = run('kustomize', 'build', str(ROOT / 'kubernetes/apps/observability/loki/app'))
    result = subprocess.run(['yq', '-o=json', 'select(.kind == "DaemonSet" and .metadata.name == "loki-canary")'],
                            input=rendered, text=True, capture_output=True, check=True)
    template = json.loads(result.stdout)['spec']['template']
    pod = {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': dict(template['metadata'], name=name, namespace='observability'),
           'spec': template['spec']}
    pod['spec'].update(restartPolicy='Never', activeDeadlineSeconds=420)
    pod['spec']['containers'][0].update(command=['/bin/sh', '-ec'], args=[
        "set -o pipefail; python3 -u /canary/canary.py | awk 'NR == 1 {print \"negative-control withheld log=\" $0 > \"/dev/stderr\"; next} {print; fflush()}'"])
    return {'apiVersion': 'batch/v1', 'kind': 'Job',
            'metadata': {'name': name, 'namespace': 'observability'},
            'spec': {'backoffLimit': 0, 'activeDeadlineSeconds': 420, 'ttlSecondsAfterFinished': 300,
                     'template': {'metadata': {'labels': template['metadata']['labels']}, 'spec': pod['spec']}}}


def exercise(output):
    values = durability.document(ROOT / 'kubernetes/apps/observability/otel-collector/app/helmrelease.yaml')['spec']['values']
    canary = canary_document()['spec']['template']['spec']['containers'][0]
    nonce = uuid.uuid4().hex[:10]
    network, loki_name = 'canary-' + nonce, 'loki-' + nonce
    containers = []
    relay = None
    reader = None
    ledger = []
    dropped = []
    omit = threading.Event()
    with tempfile.TemporaryDirectory(prefix='anton-canary-') as directory:
        root = Path(directory); root.chmod(0o755)
        for name in ['pods', 'state', 'loki-data']:
            (root / name).mkdir(mode=0o777); (root / name).chmod(0o777)
        pod = root / 'pods' / ('observability_loki-canary-local_' + str(uuid.uuid4())) / 'canary'
        pod.mkdir(parents=True); log = pod / '0.log'; log.touch()
        save(root / 'otel.json', durability.local_config(values, root, loki_name))
        save(root / 'loki.json', {'auth_enabled': False, 'server': {'http_listen_port': 3100},
             'common': {'path_prefix': '/data', 'replication_factor': 1,
                        'ring': {'kvstore': {'store': 'inmemory'}},
                        'storage': {'filesystem': {'chunks_directory': '/data/chunks', 'rules_directory': '/data/rules'}}},
             'schema_config': {'configs': [{'from': '2024-01-01', 'store': 'tsdb', 'object_store': 'filesystem',
                 'schema': 'v13', 'index': {'prefix': 'index_', 'period': '24h'}}]},
             'ingester': {'wal': {'enabled': True, 'dir': '/data/wal', 'flush_on_shutdown': True}},
             'limits_config': {'allow_structured_metadata': True}})
        try:
            run('docker', 'network', 'create', network)
            lid = run('docker', 'run', '-d', '--name', loki_name, '--network', network,
                      '-v', f'{root}:/fixture:ro', '-v', f'{root / "loki-data"}:/data',
                      '-p', '127.0.0.1::3100', durability.LOKI, '-config.file=/fixture/loki.json')
            containers.append(lid)
            def loki_address():
                return 'http://127.0.0.1:' + run('docker', 'port', lid, '3100/tcp').rsplit(':', 1)[1]
            eventually(lambda: get(loki_address() + '/ready'))
            image = values['image']['repository'] + ':' + values['image']['tag']
            def collector():
                ident = run('docker', 'run', '-d', '--network', network, '--user', '0', '--memory', '512m',
                            '-e', 'MY_POD_IP=0.0.0.0', '-v', f'{root}:/fixture:ro', '-v', f'{root / "state"}:/state',
                            '-p', '127.0.0.1::8888', image, '--config=/fixture/otel.json', *values['command']['extraArgs'])
                containers.append(ident)
                port = run('docker', 'port', ident, '8888/tcp').rsplit(':', 1)[1]
                eventually(lambda: get('http://127.0.0.1:' + port + '/metrics'))
                return ident
            cid = collector()
            probe = run('docker', 'run', '-d', '--network', network, '--memory', '64m', '-p', '127.0.0.1::3500',
                        '-v', str(ROOT / 'kubernetes/apps/observability/loki/app/log-canary.py') + ':/canary/canary.py:ro',
                        '-e', 'POD_NAME=loki-canary-local', '-e', 'NODE_NAME=local', '-e', 'LOKI_URL=http://' + loki_name + ':3100',
                        canary['image'], 'python3', '-u', '/canary/canary.py').splitlines()[-1]
            containers.append(probe)
            metrics_url = 'http://127.0.0.1:' + run('docker', 'port', probe, '3500/tcp').rsplit(':', 1)[1] + '/metrics'
            relay = subprocess.Popen(['docker', 'logs', '-f', probe], stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, text=True)
            def forward():
                for line in relay.stdout:
                    try:
                        record = json.loads(line)
                    except ValueError:
                        continue
                    if record.get('message') != 'anton-log-canary':
                        continue
                    ident = record['seq']; ledger.append(record)
                    if omit.is_set():
                        dropped.append(record); omit.clear(); continue
                    stamp = datetime.datetime.now(datetime.timezone.utc).isoformat().replace('+00:00', 'Z')
                    with log.open('a') as stream:
                        stream.write(stamp + ' stdout F ' + line); stream.flush()
            reader = threading.Thread(target=forward, daemon=True); reader.start()
            def received():
                params = urllib.parse.urlencode({'query': '{k8s_namespace_name="observability",k8s_container_name="canary"} | k8s_pod_name="loki-canary-local" |= "anton-log-canary"',
                                                  'since': '1h', 'limit': 1000})
                data = json.loads(get(loki_address() + '/loki/api/v1/query_range?' + params))
                return {json.loads(v[1])['seq'] for s in data['data']['result'] for v in s['values']}
            eventually(lambda: metric(get(metrics_url), 'log_canary_confirmed_total') >= 3, timeout=75)
            print('Healthy canary correlates numeric IDs through the committed OTel pipeline', flush=True)
            run('docker', 'stop', '--time', '30', lid)
            run('docker', 'kill', cid)
            cid = collector(); time.sleep(5)
            run('docker', 'kill', cid)
            cid = collector()
            run('docker', 'start', lid)
            eventually(lambda: get(loki_address() + '/ready'))
            expected = {record['seq'] for record in ledger}
            eventually(lambda: expected <= received(), timeout=90)
            assert metric(get(metrics_url), 'log_canary_oldest_unconfirmed_age_seconds') < 60
            print('Overlapping Loki stop and two collector SIGKILLs recovered every numeric ID', flush=True)
            omit.set(); eventually(lambda: dropped, timeout=20)
            first = dropped[0]['emitted_at']
            eventually(lambda: metric(get(metrics_url), 'log_canary_oldest_unconfirmed_age_seconds') > 180, timeout=240)
            delay = time.time() - first
            assert delay < 240, delay
            expected = {record['seq'] for record in ledger} - {record['seq'] for record in dropped}
            eventually(lambda: expected <= received(), timeout=30)
            assert not {record['seq'] for record in dropped} & received()
            result = {'written_records': len(ledger), 'expected_delivered': len(expected),
                      'queryable_records': len(expected & received()), 'withheld_records': dropped,
                      'oldest_unconfirmed_age_seconds': metric(get(metrics_url), 'log_canary_oldest_unconfirmed_age_seconds'),
                      'missing_detection_seconds': round(delay, 3), 'collector_sigkills': 2,
                      'loki_graceful_restarts': 1, 'unexplained_missing': sorted(expected - received())}
            assert not result['unexplained_missing']
            output.write_text(json.dumps(result, indent=2) + '\n')
            print(json.dumps(result), flush=True)
        finally:
            if relay:
                relay.terminate(); relay.wait(timeout=10)
            if reader:
                reader.join(timeout=5)
            for ident in reversed(containers):
                run('docker', 'rm', '-f', ident)
            run('docker', 'network', 'rm', network)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--render-negative-control', type=Path)
    parser.add_argument('--name', default='loki-canary-missing-test')
    args=parser.parse_args()
    if args.render_negative_control:
        args.render_negative_control.write_text(json.dumps(negative_control(args.name),indent=2)+'\n')
    elif args.output:
        exercise(args.output)
    else:
        parser.error('--output or --render-negative-control is required')
