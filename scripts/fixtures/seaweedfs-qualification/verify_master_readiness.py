#!/usr/bin/env python3
"""Prove the pinned master status endpoint can be healthy without a leader."""
import json
import subprocess
import time
import uuid
from pathlib import Path

from run import IMAGES


def docker(*args, check=True):
    return subprocess.run(['docker', *args], capture_output=True, text=True,
                          timeout=30, check=check)


name = 'anton-sw-readiness-' + uuid.uuid4().hex[:10]
manifest_path = Path(__file__).resolve().parents[3] / 'kubernetes/apps/storage/seaweedfs-config/app/seaweed.yaml'
manifest = json.loads(subprocess.check_output(
    ['mise', 'exec', '--', 'yq', '-o=json', '.', str(manifest_path)], text=True))
sidecar = next(sidecar for sidecar in manifest['spec']['master']['sidecars']
               if sidecar['name'] == 'raft-readiness')
gate = sidecar['readinessProbe']['httpGet']
try:
    docker('run', '-d', '--platform', 'linux/amd64', '--name', name + '-gate',
           '--network', 'none', '--read-only', '--user', '65534:65534',
           '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
           '--memory', '32m', '--entrypoint', sidecar['command'][0],
           sidecar['image'], *sidecar['command'][1:])
    time.sleep(0.2)
    assert json.loads(docker('inspect', name + '-gate').stdout)[0]['State']['Running']
    docker('run', '-d', '--platform', 'linux/amd64', '--name', name,
           '--network', 'none', '--read-only', '--tmpfs', '/tmp:rw,mode=1777',
           '--label', 'anton.qualification=true', '--memory', '256m', '--cpus', '1',
           '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
           '--entrypoint', 'weed', IMAGES['4.48'], 'master', '-mdir=/tmp',
           '-ip=peer-z', '-ip.bind=0.0.0.0', '-telemetry=false',
           '-peers=peer-a:9333,peer-b:9333,peer-z:9333')
    deadline = time.monotonic() + 20
    while True:
        status = docker('exec', name, 'wget', '-T', '2', '-qO-',
                        'http://127.0.0.1:9333/cluster/status', check=False)
        if status.returncode == 0:
            break
        if time.monotonic() >= deadline:
            raise AssertionError('isolated master did not start its HTTP listener')
        time.sleep(0.1)
    data = json.loads(status.stdout)
    assert not data.get('Leader'), data
    health = docker('exec', name, 'wget', '-T', '2', '-SO-',
                    f'http://127.0.0.1:{gate["port"]}{gate["path"]}', check=False)
    assert health.returncode != 0 and '503' in health.stderr, health
    print(json.dumps({'image': IMAGES['4.48'], 'status_http_200_without_leader': True,
                      'raft_health_http_503_without_leader': True,
                      'declared_readiness_sidecar_stays_running': True}))
finally:
    docker('rm', '-f', name, check=False)
    docker('rm', '-f', name + '-gate', check=False)
