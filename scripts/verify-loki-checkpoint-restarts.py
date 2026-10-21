#!/usr/bin/env python3
"""Exercise only a local, pinned amd64 Loki image with synthetic numbered logs.

Uses a private filesystem fixture, an internal Docker network and a private HTTP client with no published ports.
It. Forces checkpoint/flush overlap, stream recreation, crash recovery and
repeated graceful restarts. Never accesses Kubernetes or production evidence.
"""
import argparse
import collections
import json
import hashlib
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid


def run(*args):
    return subprocess.check_output(args, text=True, stderr=subprocess.STDOUT, timeout=90).strip()


def eventually(fn, seconds=60):
    deadline = time.monotonic() + seconds
    last = None
    while time.monotonic() < deadline:
        try:
            last = fn()
            if last:
                return last
        except (OSError, urllib.error.URLError, subprocess.CalledProcessError):
            pass
        time.sleep(.05)
    raise AssertionError('Timed out: ' + str(last)[:200])


def exercise(image, out, cycles, missing_reference_fixture=None, downgrade_image=None):
    nonce = uuid.uuid4().hex
    name, network = 'anton-checkpoint-' + nonce, 'anton-checkpoint-net-' + nonce
    out.mkdir(parents=True, exist_ok=True, mode=0o700)
    expected = set()
    checks = []
    created = False
    client = None
    client_name = name + "-client"
    with tempfile.TemporaryDirectory(prefix='anton-checkpoint-') as temp:
        root = Path(temp)
        root.chmod(0o755)
        data = root / 'data'
        data.mkdir(mode=0o777)
        data.chmod(0o777)
        if missing_reference_fixture is not None:
            shutil.copytree(missing_reference_fixture, data / "wal")
            (data / "wal").chmod(0o777)
            for path in (data / "wal").rglob("*"):
                path.chmod(0o777 if path.is_dir() else 0o666)
        config = {'auth_enabled': False, 'analytics': {'reporting_enabled': False},
            'server': {'http_listen_port': 3100},
            'common': {'path_prefix': '/data', 'replication_factor': 1,
                'ring': {'kvstore': {'store': 'inmemory'}, 'instance_addr': '127.0.0.1'},
                'storage': {'filesystem': {'chunks_directory': '/data/chunks', 'rules_directory': '/data/rules'}}},
            'schema_config': {'configs': [{'from': '2024-01-01', 'store': 'tsdb',
                'object_store': 'filesystem', 'schema': 'v13', 'index': {'prefix': 'index_', 'period': '24h'}}]},
            'ingester': {'lifecycler': {'min_ready_duration': '0s', 'final_sleep': '0s'},
                'wal': {'enabled': True, 'dir': '/data/wal', 'flush_on_shutdown': True, 'checkpoint_duration': '8s'},
                'flush_check_period': '100ms', 'chunk_idle_period': '1h', 'max_chunk_age': '1h',
                'chunk_retain_period': '0s'},
            'limits_config': {'ingestion_rate_mb': 100, 'ingestion_burst_size_mb': 100,
                'max_global_streams_per_user': 10000}}
        cfg = root / 'loki.json'
        cfg.write_text(json.dumps(config))
        try:
            run('docker', 'network', 'create', '--internal', network)
            def start_loki(target_image):
                return run('docker', 'run', '-d', '--pull', 'never', '--platform', 'linux/amd64',
                '--name', name, '--network', network, '--read-only', '--cap-drop', 'ALL',
                '--security-opt', 'no-new-privileges', '--memory', '2g', '--cpus', '2',
                '--tmpfs', '/tmp:rw,size=128m',
                '-v', f'{data}:/data', '-v', f'{cfg}:/cfg/loki.json:ro', target_image,
                '-config.file=/cfg/loki.json')
            ident = start_loki(image)
            created = True
            client_code = """import sys,json,urllib.request
url='http://'+sys.argv[1]+':3100'
for line in sys.stdin:
 try:
  item=json.loads(line);body=item['body']
  request=urllib.request.Request(url+item['path'],data=None if body is None else body.encode(),headers={'Content-Type':'application/json'})
  with urllib.request.urlopen(request,timeout=15) as response: result={'value':response.read().decode()}
 except Exception as error: result={'error':str(error)}
 print(json.dumps(result),flush=True)
"""
            client = subprocess.Popen(['docker', 'run', '--rm', '-i', '--name', client_name,
                '--network', network, '--read-only', '--cap-drop', 'ALL',
                '--security-opt', 'no-new-privileges', '--memory', '128m',
                'docker.io/library/python:3.14-alpine@sha256:f6a589d43c42b9e7f7dc67a12d37132491f362859a5d750607710cc56da3bc72',
                'python3', '-u', '-c', client_code, name], stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

            def http(path, body=None):
                client.stdin.write(json.dumps({'path': path, 'body': None if body is None else body.decode()}) + '\n')
                client.stdin.flush()
                line = client.stdout.readline()
                if not line:
                    raise RuntimeError('Local HTTP client stopped')
                result = json.loads(line)
                if 'error' in result:
                    raise OSError(result['error'])
                return result['value']

            def metrics():
                text = http('/metrics')
                result = collections.defaultdict(float)
                for line in text.splitlines():
                    if not line or line.startswith('#'):
                        continue
                    key, value = line.rsplit(' ', 1)
                    result[key.split('{')[0]] += float(value)
                return result

            def ready():
                return http('/ready').strip() == 'ready'

            def logs():
                return run('docker', 'logs', name)

            def push(cycle, seq):
                streams = []
                entries = []
                for stream in range(64):
                    body = f'run={nonce} cycle={cycle} stream={stream:02d} seq={seq:02d}'
                    streams.append({'stream': {'test_run': nonce, 'cycle': str(cycle), 'stream': str(stream)},
                        'values': [[str(time.time_ns()), body]]})
                    entries.append(body)
                http('/loki/api/v1/push', json.dumps({'streams': streams}).encode())
                expected.update(entries)

            def verify(stage):
                params = urllib.parse.urlencode({'query': '{test_run=' + json.dumps(nonce) + '}',
                    'since': '1h', 'limit': 5000, 'direction': 'forward'})
                response = json.loads(http('/loki/api/v1/query_range?' + params))
                lines = [value[1] for stream in response['data']['result'] for value in stream['values']]
                actual = set(lines)
                missing = sorted(expected - actual)
                item = {'stage': stage, 'acknowledged': len(expected), 'returned': len(lines),
                    'missing': len(missing), 'unexpected': len(actual - expected),
                    'duplicate_results': len(lines) - len(actual), 'missing_ids': missing,
                    'memory_chunks_matched': response['data']['stats']['ingester']['totalChunksMatched'],
                    'stored_chunks_downloaded': response['data']['stats']['ingester']['store']['totalChunksDownloaded'] + response['data']['stats']['querier']['store']['totalChunksDownloaded'],
                    'metrics': {key: value for key, value in metrics().items() if key in [
                        'loki_ingester_wal_corruptions_total', 'loki_ingester_wal_records_logged_total',
                        'loki_ingester_checkpoint_creations_total', 'loki_ingester_wal_recovered_entries_total']}}
                required = ['loki_ingester_wal_records_logged_total', 'loki_ingester_checkpoint_creations_total',
                            'loki_ingester_wal_recovered_entries_total']
                assert all(key in item['metrics'] for key in required), 'Required WAL metrics absent'
                if stage.startswith('before-crash'):
                    assert item['metrics']['loki_ingester_checkpoint_creations_total'] > 0
                    assert item['metrics']['loki_ingester_wal_records_logged_total'] > 0
                else:
                    recovery = logs().rsplit('recovering from checkpoint', 1)[-1]
                    assert re.search(r'checkpoint recovery finished[^\n]*errors=false', recovery)
                    assert re.search(r'WAL segment recovery finished[^\n]*errors=' + ('true' if missing_reference_fixture else 'false'), recovery)
                checks.append(item)
                (out / 'checks.json').write_text(json.dumps(checks, indent=2))
                assert not missing and actual == expected and len(lines) == len(actual), {key: value for key, value in item.items() if key != 'missing_ids'}
                assert item['metrics'].get('loki_ingester_wal_corruptions_total', 0) == (1 if missing_reference_fixture else 0), item
                print(json.dumps({key: value for key, value in item.items() if key not in ['missing_ids', 'metrics']}), flush=True)

            eventually(ready)
            if missing_reference_fixture is not None:
                push(0, 0)
                verify('missing-reference-negative-control')
                assert re.search(r'err="stream \(999\) not set during WAL replay for user \(fake\)"', logs())
                report = {'image': image, 'negative_control': 'missing-reference',
                          'actual_error_logged': True, 'failure_counter': 1,
                          'acknowledged': len(expected), 'missing': 0, 'checks': checks}
                (out / 'result.json').write_text(json.dumps(report, indent=2))
                return report
            for cycle in range(cycles):
                push(cycle, 0)
                base = logs().count('attempting checkpoint for')
                eventually(lambda: logs().count('attempting checkpoint for') > base, seconds=20)
                checkpoint_start = time.monotonic()
                completed = logs().count('atomic checkpoint finished')
                # Ensure the amortized iterator has captured its stream pointers.
                time.sleep(.15)
                push(cycle, 1)
                http('/flush', b'')
                eventually(lambda: metrics().get('loki_ingester_memory_chunks', -1) == 0, seconds=5)
                push(cycle, 2)
                push(cycle, 3)
                assert logs().count('atomic checkpoint finished') == completed, 'Flush did not overlap checkpoint'
                verify('before-crash-' + str(cycle))
                eventually(lambda: logs().count('atomic checkpoint finished') > completed, seconds=15)
                checks.append({'stage': 'overlap-' + str(cycle), 'seconds': time.monotonic() - checkpoint_start,
                               'flush_removed_all_chunks_before_checkpoint_completed': True})
                run('docker', 'kill', '--signal', 'KILL', name)
                run('docker', 'start', name)
                eventually(ready)
                verify('crash-recovery-' + str(cycle))
                push(cycle, 4)
                run('docker', 'stop', '-t', '30', name)
                run('docker', 'start', name)
                eventually(ready)
                verify('graceful-recovery-' + str(cycle))
                completed = logs().count('atomic checkpoint finished')
                eventually(lambda: logs().count('atomic checkpoint finished') > completed, seconds=20)
                run('docker', 'kill', '--signal', 'KILL', name)
                run('docker', 'start', name)
                eventually(ready)
                verify('second-checkpoint-recovery-' + str(cycle))
            downgrade = None
            if downgrade_image:
                http('/flush', b'')
                eventually(lambda: metrics().get('loki_ingester_memory_chunks', -1) == 0, seconds=10)
                verify('pre-downgrade-drain')
                assert checks[-1]['memory_chunks_matched'] == 0 and checks[-1]['stored_chunks_downloaded'] > 0
                run('docker', 'stop', '-t', '30', name)
                assert run('docker', 'inspect', '--format', '{{.State.ExitCode}}', name) == '0'
                def old_wal_hashes():
                    return {str(p.relative_to(data / 'wal')): hashlib.sha256(p.read_bytes()).hexdigest()
                            for p in sorted((data / 'wal').rglob('*')) if p.is_file()}
                preserved = old_wal_hashes()
                assert preserved
                config['ingester']['wal']['dir'] = '/data/wal-downgrade'
                cfg.write_text(json.dumps(config))
                run('docker', 'rm', name)
                start_loki(downgrade_image)
                eventually(ready)
                verify('downgrade-recovery')
                push(cycles - 1, 5)
                run('docker', 'kill', '--signal', 'KILL', name)
                run('docker', 'start', name)
                eventually(ready)
                verify('downgrade-crash-recovery')
                push(cycles - 1, 6)
                run('docker', 'stop', '-t', '30', name)
                run('docker', 'start', name)
                eventually(ready)
                verify('downgrade-graceful-recovery')
                assert preserved == old_wal_hashes(), 'Original WAL changed during downgrade'
                downgrade = {'image': downgrade_image, 'new_wal_directory': '/data/wal-downgrade',
                             'original_wal_unchanged': True, 'drained_to_object_store': True,
                             'continued_records': 128, 'missing': 0}
            report = {'image': image, 'platform': 'linux/amd64', 'cycles': cycles,
                'restarts': cycles * 3, 'acknowledged': len(expected), 'missing': 0,
                'checks': checks, 'downgrade': downgrade, 'production_accessed': False}
            (out / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
            return report
        finally:
            try:
                if created:
                    result = subprocess.run(['docker', 'logs', name], capture_output=True, text=True, timeout=30)
                    (out / 'loki.log').write_text(result.stdout + result.stderr)
            finally:
                try:
                    subprocess.run(['docker', 'rm', '-f', client_name, name], capture_output=True, timeout=30)
                    if client is not None:
                        client.communicate(timeout=30)
                finally:
                    subprocess.run(['docker', 'network', 'rm', network], capture_output=True, timeout=30)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', required=True, help='Immutable local image config ID or published digest')
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--cycles', type=int, default=2)
    parser.add_argument('--downgrade-image', help='Immutable old image for drained downgrade into a new WAL directory')
    parser.add_argument('--missing-reference-fixture', type=Path, help='Synthetic WAL generated by TestForensicWriteMissingReference')
    args = parser.parse_args()
    if not re.fullmatch(r'(?:sha256:[0-9a-f]{64}|[^\s]+@sha256:[0-9a-f]{64})', args.image):
        parser.error('Use an immutable image ID or digest')
    if args.downgrade_image and not re.fullmatch(r'(?:sha256:[0-9a-f]{64}|[^\s]+@sha256:[0-9a-f]{64})', args.downgrade_image):
        parser.error('Use an immutable downgrade image')
    if not 1 <= args.cycles <= 5:
        parser.error('cycles must be between 1 and 5')
    exercise(args.image, args.output.resolve(), args.cycles, args.missing_reference_fixture, args.downgrade_image)


if __name__ == '__main__':
    main()
