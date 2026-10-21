#!/usr/bin/env python3
"""Disposable, pinned amd64 SeaweedFS S3 qualification; never contacts Kubernetes."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import datetime
import hashlib
import hmac
import importlib.util
import ipaddress
import json
from pathlib import Path
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import xml.etree.ElementTree as ET

IMAGES = {
    '4.40': 'docker.io/chrislusf/seaweedfs@sha256:5b28dd52da45622d0a1c3a6d65281eb171be3ff7cac40e1a328c074882f7370c',
    '4.48': 'docker.io/chrislusf/seaweedfs@sha256:aba492e2a4e4c90bff795745e8e660affa1f09e7650f5981bd7bccd1a06cd931',
}
PROBE_PATH = Path(__file__).resolve().parents[3] / 'kubernetes/apps/storage/seaweedfs-config/app/s3-read-probe.py'


def docker(*args, check=True):
    result = subprocess.run(['docker', *args], capture_output=True, text=True, timeout=90)
    if check and result.returncode:
        raise RuntimeError(f'docker {args[:3]}: {result.stderr}')
    return result.stdout.strip()


class Lab:
    def __init__(self, directory, version, address, ha=False, ephemeral_masters=False):
        self.directory = directory
        self.version = version
        self.address = address
        self.ha = ha
        self.ephemeral_masters = ephemeral_masters
        self.roles = (['master', 'master-b', 'master-c', 'volume', 'volume-b', 'volume-c',
                       'filer', 'filer-b', 's3', 's3-b'] if ha else ['master', 'volume', 'filer', 's3'])
        self.urls = {}
        self.gateway = 's3'
        self.name = 'anton-sw-qual-' + uuid.uuid4().hex[:10]
        self.active = set()
        self.owns_directory = False
        self.events = []
        self.expected = {}
        self.deleted = set()
        self.extra_objects = {}
        self.versions = {role: version for role in self.roles}
        self.move = 10

    def record(self, event, **values):
        entry = {'time': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'event': event, **values}
        self.events.append(entry)
        print(json.dumps(entry), flush=True)
        (self.directory / 'events.json').write_text(json.dumps(self.events, indent=2) + '\n')

    def start(self):
        self.directory.mkdir(parents=True, exist_ok=False)
        self.owns_directory = True
        for role in self.roles:
            (self.directory / role).mkdir()
        (self.directory / 's3' / 's3.json').write_text(json.dumps({'identities': [{
            'name': 'local-qualification', 'credentials': [{'accessKey': 'qualification', 'secretKey': 'local-test-only'}],
            'actions': ['Admin', 'Read', 'Write', 'List', 'Tagging'],
        }]}))
        docker('network', 'create', '--label', 'anton.qualification=true', self.name)
        net = json.loads(docker('network', 'inspect', self.name))[0]
        self.subnet = ipaddress.ip_network(net['IPAM']['Config'][0]['Subnet'])
        self.record('identity', images=IMAGES, address=self.address, architecture='linux/amd64', network=self.name, roles=self.roles)
        for role in self.roles:
            self.launch(role)
        self.verify_quorum()
        self.wait(lambda: self.request('GET', '/')[0] == 200)
        self.record('started', versions=self.versions.copy())

    def launch(self, role):
        component = role.split('-')[0]
        name = self.name + '-' + role
        command = ['run', '-d', '--platform', 'linux/amd64', '--name', name,
                   '--network', self.name, '--network-alias', role,
                   '--label', 'anton.qualification=true', '--memory', '768m', '--cpus', '2',
                   '-v', f'{self.directory / role}:/data', '--entrypoint', 'weed']
        masters = ','.join(r + ':9333' for r in self.roles if r.startswith('master'))
        if component == 'master':
            command += ['-p', '127.0.0.1::9333', '-e', 'WEED_MASTER_VOLUME_GROWTH_COPY_1=1']
            args = ['master', '-ip=' + role, '-ip.bind=0.0.0.0', '-mdir=/data', '-volumeSizeLimitMB=64', '-defaultReplication=000', '-telemetry=false']
            if self.ha:
                args += ['-peers=' + masters]
        elif component == 'volume':
            address = str(self.subnet.network_address + self.move + [r for r in self.roles if r.startswith('volume')].index(role))
            command += ['--ip', address]
            args = ['volume', '-master=' + masters, '-dir=/data', '-max=20',
                    '-ip=' + (role if self.address == 'dns' else address), '-ip.bind=0.0.0.0', '-port=8080']
        elif component == 'filer':
            args = ['filer', '-master=' + masters, '-ip=' + role, '-ip.bind=0.0.0.0', '-defaultStoreDir=/data']
        else:
            command += ['-p', '127.0.0.1::8333', '-p', '127.0.0.1::9327']
            filer = 'filer-b' if role == 's3-b' else 'filer'
            config = self.directory / role / 's3.json'
            if not config.exists():
                shutil.copyfile(self.directory / 's3' / 's3.json', config)
            args = ['s3', '-filer=' + filer + ':8888', '-ip.bind=0.0.0.0', '-config=/data/s3.json',
                    '-iam=false', '-cacheCapacityMB=0', '-metricsPort=9327', '-metricsIp=0.0.0.0']
        docker(*command, IMAGES[self.versions[role]], *args)
        self.active.add(role)
        info = json.loads(docker('inspect', name))[0]
        assert info['Config']['Image'] == IMAGES[self.versions[role]]
        (self.directory / f'{len(self.events):03d}-{role}-image.json').write_text(json.dumps({
            'configured': info['Config']['Image'], 'imageId': info['Image'], 'startedAt': info['State']['StartedAt'],
        }, indent=2) + '\n')
        if component in ['master', 's3']:
            port = '9333' if component == 'master' else '8333'
            binding = docker('port', name, port + '/tcp').splitlines()[0]
            assert binding.startswith('127.0.0.1:'), 'refuse a non-loopback published endpoint'
            self.urls[role] = 'http://' + binding
            if role in ['master', 's3']:
                setattr(self, role + '_url', 'http://' + binding)

    def stop(self, role, abrupt=False):
        name = self.name + '-' + role
        if role not in self.active:
            return
        docker('kill', '--signal', 'KILL', name) if abrupt else docker('stop', '-t', '20', name)
        # Docker sends component logs to stderr as well as stdout.
        result = subprocess.run(['docker', 'logs', name], capture_output=True, text=True)
        (self.directory / f'{len(self.events):03d}-{role}.log').write_text(result.stdout + result.stderr)
        state = json.loads(docker('inspect', name))[0]['State']
        (self.directory / f'{len(self.events):03d}-{role}-exit.json').write_text(json.dumps({
            'requested': 'SIGKILL' if abrupt else 'SIGTERM with 20s grace',
            'exitCode': state['ExitCode'], 'oomKilled': state['OOMKilled'],
            'startedAt': state['StartedAt'], 'finishedAt': state['FinishedAt'],
        }, indent=2) + '\n')
        docker('rm', name)
        self.active.remove(role)

    def request(self, method, path, data=b'', extra=None, timeout=20):
        url = self.urls[self.gateway] + path
        parsed = urllib.parse.urlsplit(url)
        now = datetime.datetime.now(datetime.timezone.utc)
        stamp, day = now.strftime('%Y%m%dT%H%M%SZ'), now.strftime('%Y%m%d')
        digest = hashlib.sha256(data).hexdigest()
        headers = {'host': parsed.netloc, 'x-amz-date': stamp, 'x-amz-content-sha256': digest}
        names = ';'.join(sorted(headers))
        query = urllib.parse.urlencode(sorted(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)), quote_via=urllib.parse.quote)
        canonical = '\n'.join([method, parsed.path, query,
                               ''.join(k + ':' + headers[k] + '\n' for k in sorted(headers)), names, digest])
        scope = day + '/us-east-1/s3/aws4_request'
        message = 'AWS4-HMAC-SHA256\n' + stamp + '\n' + scope + '\n' + hashlib.sha256(canonical.encode()).hexdigest()
        key = b'AWS4local-test-only'
        for part in [day, 'us-east-1', 's3', 'aws4_request']:
            key = hmac.new(key, part.encode(), hashlib.sha256).digest()
        signature = hmac.new(key, message.encode(), hashlib.sha256).hexdigest()
        headers['authorization'] = f'AWS4-HMAC-SHA256 Credential=qualification/{scope}, SignedHeaders={names}, Signature={signature}'
        headers.update(extra or {})
        req = urllib.request.Request(url, data=data if method in ['PUT', 'POST'] else None, method=method, headers=headers)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(req, timeout=timeout) as response:
                return response.status, response.read(), dict(response.headers)
        except urllib.error.HTTPError as error:
            with error:
                return error.code, error.read(), dict(error.headers)

    def wait(self, predicate, timeout=75):
        deadline = time.monotonic() + timeout
        last = None
        while time.monotonic() < deadline:
            try:
                if predicate():
                    return
            except Exception as error:
                last = repr(error)
            time.sleep(1)
        raise AssertionError(f'recovery exceeded {timeout}s: {last}')

    def put(self, key, body):
        status, response, _ = self.request('PUT', '/qualification/' + key, body)
        assert status == 200, (status, response)
        self.expected[key] = body

    def verify(self):
        self.verify_quorum()
        original = self.gateway
        try:
            for role in self.roles:
                if role.startswith('s3'):
                    self.gateway = role
                    self.wait(self.converged)
                    self.verify_gateway()
        finally:
            self.gateway = original

    def verify_quorum(self):
        if not self.ha:
            return
        states = {}
        masters = [role for role in self.roles if role.startswith('master')]
        def settled():
            for role in masters:
                with urllib.request.urlopen(self.urls[role] + '/cluster/status', timeout=3) as response:
                    states[role] = json.load(response)
                with urllib.request.urlopen(self.urls[role] + '/cluster/healthz', timeout=3) as response:
                    if response.status != 200:
                        return False
            leaders = {state.get('Leader', '').split(':')[0] for state in states.values()}
            return len(leaders) == 1 and next(iter(leaders)) in masters and sum(
                state.get('IsLeader', False) for state in states.values()) == 1 and all(
                {peer.split(':')[0] for peer in state.get('Peers', [])} == set(masters) - {role}
                for role, state in states.items())
        self.wait(settled)
        self.record('master_quorum_verified', states=states)

    def converged(self):
        return all(self.request('GET', '/qualification/' + key)[1] == body for key, body in self.expected.items()) and all(
            self.request('GET', '/qualification/' + key)[0] == 404 for key in self.deleted)

    def verify_gateway(self):
        for path, body in self.extra_objects.items():
            status, actual, _ = self.request('GET', path)
            assert status == 200 and actual == body, (path, 'new-version collection unreadable', status)
        for key, body in self.expected.items():
            status, actual, headers = self.request('GET', '/qualification/' + key)
            assert status == 200 and actual == body, (key, status, len(actual), len(body))
            status, actual, _ = self.request('GET', '/qualification/' + key, extra={'Range': 'bytes=17-1039'})
            assert status == 206 and actual == body[17:1040], (key, 'range', status)
            status, actual, headers = self.request('HEAD', '/qualification/' + key)
            assert status == 200 and not actual and int(headers['Content-Length']) == len(body), (key, 'head', status)
        for key in self.deleted:
            assert self.request('GET', '/qualification/' + key)[0] == 404, (key, 'deleted object resurrected')
        status, listing, _ = self.request('GET', '/qualification?list-type=2')
        assert status == 200, (status, listing)
        root = ET.fromstring(listing)
        keys = {e.text for e in root.iter() if e.tag.endswith('}Key') or e.tag == 'Key'}
        assert keys == set(self.expected), (keys, set(self.expected))
        port = docker('port', self.name + '-' + self.gateway, '9327/tcp').splitlines()[0]
        with urllib.request.urlopen('http://' + port + '/metrics', timeout=5) as response:
            metrics = response.read().decode()
        (self.directory / f'{len(self.events):03d}-{self.gateway}-metrics.txt').write_text(metrics)
        assert any(line.startswith('SeaweedFS_s3_request_total{') and 'type="GET"' in line and 'code="200"' in line
                   for line in metrics.splitlines()), 'S3 GET metric contract changed'
        self.record('verified', gateway=self.gateway, objects=len(self.expected), bytes=sum(map(len, self.expected.values())),
                    manifest={k: hashlib.sha256(v).hexdigest() for k, v in self.expected.items()})

    def verify_production_probe(self):
        spec = importlib.util.spec_from_file_location('qualification_read_probe', PROBE_PATH)
        probe = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(probe)
        assert self.request('PUT', '/s3-read-probe')[0] == 200
        assert self.request('PUT', '/s3-read-probe/fixture-v1', bytes(65536))[0] == 200
        result = probe.verify(self.s3_url + '/s3-read-probe/fixture-v1', 'qualification', 'local-test-only')
        assert result == {'ok': True, 'reason': 'verified'}, result
        self.record('production_probe_verified', code_sha256=hashlib.sha256(PROBE_PATH.read_bytes()).hexdigest())

    def seed(self):
        status, body, _ = self.request('PUT', '/qualification')
        assert status == 200, (status, body)
        # Listing buckets becomes ready before a fresh HA master has writable
        # volume topology. Gate workload start on a real write/read instead.
        ready = b'qualification startup readiness' * 2048
        self.wait(lambda: self.request('PUT', '/qualification/startup-readiness', ready)[0] == 200 and
                  self.request('GET', '/qualification/startup-readiness')[1] == ready)
        assert self.request('DELETE', '/qualification/startup-readiness')[0] == 204
        self.deleted.add('startup-readiness')
        for index in range(12):
            body = hashlib.shake_256(f'object-{index}'.encode()).digest(65536 + index * 8192)
            self.put(f'numbered-{index:03d}', body)
        self.put('numbered-011', hashlib.shake_256(b'overwritten').digest(196608))
        assert self.request('DELETE', '/qualification/numbered-010')[0] == 204
        del self.expected['numbered-010']
        self.deleted.add('numbered-010')
        self.multipart('multipart')
        self.verify()

    def multipart(self, key):
        status, response, _ = self.request('POST', '/qualification/' + key + '?uploads=')
        assert status == 200, (status, response)
        root = ET.fromstring(response)
        upload = next(element.text for element in root.iter() if element.tag.endswith('}UploadId'))
        parts, etags = [], []
        for number, size in enumerate([5 * 1024 * 1024, 131072], 1):
            body = hashlib.shake_256(f'multipart-{number}'.encode()).digest(size)
            path = '/qualification/' + key + '?' + urllib.parse.urlencode({'partNumber': number, 'uploadId': upload})
            status, response, headers = self.request('PUT', path, body)
            assert status == 200, (status, response)
            parts.append(body)
            etags.append(headers['ETag'])
        complete = ('<CompleteMultipartUpload>' + ''.join(
            f'<Part><PartNumber>{number}</PartNumber><ETag>{etag}</ETag></Part>'
            for number, etag in enumerate(etags, 1)) + '</CompleteMultipartUpload>').encode()
        status, response, _ = self.request('POST', '/qualification/' + key + '?' + urllib.parse.urlencode({'uploadId': upload}), complete)
        assert status == 200 and b'<Error>' not in response, (status, response)
        self.expected[key] = b''.join(parts)

    def stale(self):
        # Warm the S3 master-client location cache, then change only the volume address.
        assert self.request('GET', '/qualification/numbered-000')[1] == self.expected['numbered-000']
        self.record('stale_transition_begin', old_ip=str(self.subnet.network_address + self.move))
        self.stop('volume', abrupt=True)
        self.move += 1
        self.launch('volume')
        expected = 'volume:8080' if self.address == 'dns' else str(self.subnet.network_address + self.move) + ':8080'
        def registered():
            with urllib.request.urlopen(self.master_url + '/dir/lookup?volumeId=1', timeout=2) as response:
                return any(location['url'] == expected for location in json.load(response).get('locations', []))
        self.wait(registered)
        start = time.monotonic()
        try:
            status, actual, _ = self.request('GET', '/qualification/numbered-000', timeout=45)
            self.record('stale_first_read', status=status, exact=actual == self.expected['numbered-000'], seconds=time.monotonic()-start)
            assert status == 200 and actual == self.expected['numbered-000']
        except Exception as error:
            self.record('stale_first_read_failed', error=repr(error), seconds=time.monotonic()-start)
            raise
        self.verify()

    def restart_cycles(self, count):
        for cycle in range(count):
            self.put(f'restart-{cycle:03d}', hashlib.shake_256(f'cycle-{cycle}'.encode()).digest(131072))
            self.record('restart_begin', cycle=cycle, abrupt=bool(cycle % 2))
            for role in reversed(self.roles):
                self.stop(role, abrupt=bool(cycle % 2))
            for role in self.roles:
                self.launch(role)
            self.wait(lambda: self.request('GET', '/qualification/numbered-000')[1] == self.expected['numbered-000'])
            self.verify()

    def upgrade_rollback(self):
        for role in reversed(self.roles):
            self.stop(role)
        snapshot = self.directory / 'before-upgrade'
        snapshot.mkdir()
        for role in self.roles:
            if not role.startswith('s3'):
                shutil.copytree(self.directory / role, snapshot / role)
        self.record('offline_snapshot', files={str(path.relative_to(snapshot)): {
            'size': path.stat().st_size, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
            for path in sorted(snapshot.rglob('*')) if path.is_file()})
        for role in self.roles:
            self.launch(role)
        self.wait(lambda: self.request('GET', '/qualification/numbered-000')[1] == self.expected['numbered-000'])
        self.verify()
        for target in ['4.48', '4.40']:
            for role in self.roles:
                self.record('version_transition', role=role, target=target)
                self.stop(role)
                if self.ephemeral_masters and role.startswith('master'):
                    retired = self.directory / 'retired'
                    retired.mkdir(exist_ok=True)
                    (self.directory / role).rename(retired / f'{len(self.events):03d}-{role}')
                    (self.directory / role).mkdir()
                    self.record('master_state_recreated', role=role, target=target)
                self.versions[role] = target
                self.launch(role)
                self.wait(lambda: self.request('GET', '/qualification/numbered-000')[1] == self.expected['numbered-000'])
                self.verify()
                self.put(f'{target}-{role}', hashlib.shake_256(f'{target}-{role}'.encode()).digest(98304))
            self.multipart('multipart-' + target)
            if target == '4.48':
                self.create_candidate_collection()
            self.verify()
            self.record('version_transition_complete', versions=self.versions.copy())

    def create_candidate_collection(self):
        assert self.request('PUT', '/created-on-4-48')[0] == 200
        body = hashlib.shake_256(b'new volume created on 4.48').digest(262144)
        path = '/created-on-4-48/new-format-object'
        assert self.request('PUT', path, body)[0] == 200
        self.extra_objects[path] = body
        assert self.request('GET', path)[1] == body
        self.record('candidate_collection_created', sha256=hashlib.sha256(body).hexdigest(), size=len(body))

    def cleanup(self):
        with ThreadPoolExecutor(max_workers=10) as pool:
            list(pool.map(self.stop, sorted(self.active)))
        docker('network', 'rm', self.name, check=False)
        remaining = docker('ps', '-aq', '--filter', 'name=' + self.name)
        networks = docker('network', 'ls', '-q', '--filter', 'name=' + self.name)
        assert not remaining and not networks, (remaining, networks)
        self.record('cleaned', containers=0, networks=0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--version', choices=IMAGES, required=True)
    parser.add_argument('--address', choices=['ip', 'dns'], default='dns')
    parser.add_argument('--scenario', choices=['stale', 'restarts', 'upgrade'], required=True)
    parser.add_argument('--cycles', type=int, default=6)
    parser.add_argument('--ephemeral-masters', action='store_true', help='recreate master storage on every version transition')
    parser.add_argument('--ha', action='store_true', help='3 masters, 3 volumes, 2 persistent filers, 2 gateways')
    args = parser.parse_args()
    if args.output.exists():
        parser.error('refuse to overwrite an existing evidence path; choose a new --output')
    assert 1 <= args.cycles <= 20
    assert args.scenario != 'upgrade' or args.version == '4.40', 'upgrade must start on baseline'
    assert not args.ha or args.scenario != 'stale', 'use the four-component fixture for deterministic address moves'
    assert not args.ephemeral_masters or (args.ha and args.scenario == 'upgrade')
    lab = Lab(args.output.resolve(), args.version, args.address, args.ha, args.ephemeral_masters)
    try:
        lab.start()
        lab.seed()
        lab.verify_production_probe()
        if args.scenario == 'stale':
            lab.stale()
        elif args.scenario == 'restarts':
            lab.restart_cycles(args.cycles)
        else:
            lab.upgrade_rollback()
        lab.record('passed', scenario=args.scenario)
    except Exception as error:
        if lab.owns_directory:
            lab.record('failed', error=repr(error))
        raise
    finally:
        if lab.owns_directory:
            lab.cleanup()


if __name__ == '__main__':
    main()
