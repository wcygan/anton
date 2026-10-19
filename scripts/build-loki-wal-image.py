#!/usr/bin/env python3
"""Build the reviewed linux/amd64 Loki candidate and an immutable local OCI archive.

Requires an exact private v3.7.8 checkout with checkpoint-and-counter.patch
already applied. No production data, credentials, registry push or rollout.
"""
import argparse
import hashlib
import json
import os
import uuid
from pathlib import Path
import shutil
import subprocess

SOURCE = '09e6ce2ff1bdc19763a10265b870c86f51c98655'
GO = 'golang@sha256:0d1d3a794be25f809dd2cb3160d8c73276c4056a9f8242a138e908ddeee7b6b6'
FILES = ['pkg/ingester/checkpoint.go', 'pkg/ingester/ingester.go',
         'pkg/ingester/instance.go', 'pkg/ingester/stream.go']
FIXTURES = Path(__file__).resolve().parent / 'fixtures/loki-wal'


def run(*args):
    return subprocess.check_output(args, text=True).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    source = args.source.resolve(strict=True)
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True, mode=0o700)
    assert run('git', '-C', str(source), 'rev-parse', 'HEAD') == SOURCE
    assert set(run('git', '-C', str(source), 'diff', '--name-only').splitlines()) == set(FILES)
    expected = (FIXTURES / 'checkpoint-and-counter.patch').read_bytes()
    actual = subprocess.check_output(['git', '-C', str(source), 'diff', '--unified=0', '--', *FILES])
    assert actual == expected, 'Source diff does not match the reviewed patch'
    untracked = run('git', '-C', str(source), 'ls-files', '--others', '--exclude-standard', '*.go').splitlines()
    assert all(path.endswith('_test.go') for path in untracked), 'Unexpected untracked production Go source'
    patch_sha = hashlib.sha256(expected).hexdigest()
    image = 'localhost/anton/loki:3.7.8-wal-' + patch_sha[:12]
    flags = '-s -w ' + ' '.join('-X github.com/grafana/loki/v3/pkg/util/build.' + field for field in [
        'Version=3.7.8-anton.wal.1', 'Revision=09e6ce2f-' + patch_sha[:12],
        'BuildUser=anton', 'BuildDate=2026-10-19T00:00:00Z'])
    subprocess.run(['docker', 'run', '--rm', '--pull', 'never', '--network', 'none',
        '-v', f'{source}:/src:ro', '-v', f'{out}:/out',
        '-v', 'anton-wal-go-cache:/go', '-v', 'anton-wal-build-cache:/root/.cache/go-build',
        '-w', '/src', '-e', 'CGO_ENABLED=0', '-e', 'GOOS=linux', '-e', 'GOARCH=amd64',
        '-e', 'GOPROXY=off', '-e', 'GOSUMDB=off', '-e', 'GOTOOLCHAIN=local', GO,
        'go', 'build', '-p', '4', '-trimpath', '-buildvcs=false', '-tags', 'netgo',
        '-ldflags', flags, '-o', '/out/loki-linux-amd64', './cmd/loki'], check=True)
    shutil.copyfile(FIXTURES / 'Dockerfile', out / 'Dockerfile')
    (out / '.dockerignore').write_text('*\n!Dockerfile\n!loki-linux-amd64\n')
    os.utime(out / 'loki-linux-amd64', (1792368000, 1792368000))
    builder = 'anton-loki-package-' + uuid.uuid4().hex[:12]
    run('docker', 'buildx', 'create', '--name', builder, '--driver', 'docker-container')
    common = ['docker', 'buildx', 'build', '--builder', builder, '--platform', 'linux/amd64', '--provenance=false',
              '--network', 'none', '--build-arg', 'SOURCE_DATE_EPOCH=1792368000',
              '--build-arg', 'PATCH_SHA256=' + patch_sha, '-t', image]
    archive = out / 'loki-wal-candidate.oci.tar'
    try:
        subprocess.run([*common, '--load', '--output', 'type=oci,dest=' + str(archive), str(out)], check=True)
    finally:
        subprocess.run(['docker', 'buildx', 'rm', builder], check=True)
    # The OCI index identifies its image manifest; the config digest is not a pull digest.
    import tarfile
    with tarfile.open(archive) as tar:
        index = json.load(tar.extractfile('index.json'))
        digest = index['manifests'][0]['digest']
        manifest = json.load(tar.extractfile('blobs/sha256/' + digest.split(':')[1]))
    assert manifest['config']['digest'] == run('docker', 'image', 'inspect', image, '--format', '{{.Id}}'), 'Exported and loaded images differ'
    binary_sha = hashlib.sha256((out / 'loki-linux-amd64').read_bytes()).hexdigest()
    report = {'source_revision': SOURCE, 'patch_sha256': patch_sha, 'toolchain': GO,
              'platform': 'linux/amd64', 'local_tag': image, 'manifest_digest': digest,
              'image_config_digest': run('docker', 'image', 'inspect', image, '--format', '{{.Id}}'),
              'binary_sha256': binary_sha, 'oci_archive': str(archive),
              'published': False, 'production_changed': False}
    (out / 'image.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
