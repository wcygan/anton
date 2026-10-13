"""Exercise destructive retention boundaries and Harbor fail-closed behavior."""

import json, os, subprocess, tempfile, pathlib, textwrap, threading, http.server, urllib.parse
import unittest
R = pathlib.Path(__file__).resolve().parents[2]

class StorageRetentionTests(unittest.TestCase):

    def test_log_rotation_boundaries(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = pathlib.Path(tmp)
            bindir = p / 'bin'
            bindir.mkdir()
            date = bindir / 'date'
            date.write_text("#!/usr/bin/env python3\nimport sys,datetime\nu=datetime.timezone.utc\nif '-d' in sys.argv:\n print(int(datetime.datetime.strptime(sys.argv[sys.argv.index('-d')+1],'%Y-%m-%d %H:%M:%S').replace(tzinfo=u).timestamp()))\nelif '+%F' in sys.argv: print('2026-10-13')\nelse: print(int(datetime.datetime(2026,10,13,3,17,tzinfo=u).timestamp()))\n\n")
            date.chmod(493)
            deleted = ['talos-routine-2026-10-11.log', 'talos-warning-2026-09-28.log', 'talos-error-2026-09-12.log', 'talos-sink-2026-09-12.log']
            kept = ['talos-routine-2026-10-12.log', 'talos-routine-2026-10-13.log', 'talos-warning-2026-09-29.log', 'talos-diagnostic-2026-09-29.log', 'talos-error-2026-09-13.log', 'talos-sink-2026-10-03.log', 'unrelated.log', 'talos-other-2020-01-01.log']
            for n in deleted + kept:
                (p / n).touch()
            s = (R / 'kubernetes/apps/observability/talos-log-sink/app/cronjob.yaml').read_text().split('                  set -eu\n', 1)[1].split('              resources:', 1)[0]
            s = 'set -eu\n' + textwrap.dedent(s).replace('/vector-data-dir', str(p)).replace('$${', '${')
            subprocess.run(['sh', '-c', s], env={**os.environ, 'PATH': str(bindir) + ':' + os.environ['PATH']}, check=True)
            assert all((not (p / x).exists() for x in deleted))
            assert all(((p / x).exists() for x in kept))
            print('Rotation boundary/current-file/legacy preservation: PASS')

    def test_harbor_policy_and_inventory_failure(self):
        requests = []

        class Handler(http.server.BaseHTTPRequestHandler):

            def log_message(self, *a):
                pass

            def do_GET(self):
                path = self.path
                if '/projects/library/repositories/demo/artifacts/sha256:' in path:
                    body = {'digest': 'sha256:' + 'a' * 64, 'tags': [{'name': 'v1'}]}
                elif path.startswith('/projects?'):
                    body = [{'project_id': 1}]
                elif path == '/projects/1/metadatas/':
                    body = {'retention_id': '1'}
                elif path == '/retentions/1':
                    body = {'rules': []}
                elif path.startswith('/repositories?'):
                    body = [{'name': 'library/demo'}]
                elif '/artifacts?' in path:
                    body = [{'digest': 'sha256:' + 'b' * 64, 'tags': [{'name': 'in-use-' + 'b' * 64}]}]
                elif path == '/system/gc/schedule':
                    body = {'schedule': {'cron': ''}}
                else:
                    raise AssertionError(path)
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps(body).encode())

            def mutate(self):
                body = self.rfile.read(int(self.headers.get('content-length', 0))).decode()
                requests.append((self.command, self.path, json.loads(body) if body else None))
                self.send_response(200)
                self.end_headers()
            do_POST = mutate
            do_PUT = mutate
            do_DELETE = mutate
        server = http.server.HTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        with tempfile.TemporaryDirectory() as tmp:
            p = pathlib.Path(tmp)
            kub = p / 'kubectl'
            kub.write_text('#!/bin/sh\nprintf \'%s\' \'{"items":[{"spec":{"containers":[{"image":"registry/library/demo:v1@sha256:' + 'a' * 64 + '"}]}}]}\'\n')
            kub.chmod(493)
            s = (R / 'kubernetes/apps/registries/harbor-config/app/reconcile.sh').read_text().replace('$$', '$')
            (p / 'script').write_text(s)
            env = {**os.environ, 'PATH': str(p) + ':' + os.environ['PATH'], 'HARBOR_API_URL': f'http://127.0.0.1:{server.server_port}', 'HARBOR_USERNAME': 'fixture', 'HARBOR_PASSWORD': 'fixture', 'HARBOR_RETENTION_CRON': '0 30 1 * * *', 'HARBOR_PROTECTED_TAGS': '{in-use-*,rollback}', 'HARBOR_IMAGE_HOST': 'registry', 'HARBOR_GC_CRON': '0 30 5 * * 0'}
            subprocess.run(['sh', str(p / 'script')], env=env, check=True)
            assert any((m == 'POST' and b.get('name', '') == 'in-use-' + 'a' * 64 for m, u, b in requests if b))
            policy = next((b for m, u, b in requests if u == '/retentions/1'))
            assert policy['rules'][0]['params']['latestPushedK'] == 2
            assert any((m == 'DELETE' and 'in-use-' + 'b' * 64 in u for m, u, b in requests))
            assert any((u == '/system/gc/schedule' and b['parameters']['delete_untagged'] == False for m, u, b in requests if b))
            requests.clear()
            kub.write_text('#!/bin/sh\nexit 1\n')
            r = subprocess.run(['sh', str(p / 'script')], env=env)
            assert r.returncode != 0
            assert not requests
            print('Harbor latest-two/protected-digest/stale-tag/GC/fail-closed inventory: PASS')
        server.shutdown()
        server.server_close()
