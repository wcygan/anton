"""Exercise real HTTP bodies and the probe's whole-request deadline."""
import contextlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

PATH = Path(__file__).resolve().parents[2] / 'kubernetes/apps/storage/seaweedfs-config/app/s3-read-probe.py'
SPEC = importlib.util.spec_from_file_location('s3_probe', PATH)
PROBE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROBE)


@contextlib.contextmanager
def endpoint(body=bytes(65536), status=200, delay=0, redirect=False):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(dict(self.headers))
            self.send_response(status)
            if redirect:
                self.send_header('Location', '/different-object')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            try:
                if delay:
                    for byte in body[:10]:
                        self.wfile.write(bytes([byte]))
                        self.wfile.flush()
                        time.sleep(delay)
                else:
                    self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}/s3-read-probe/fixture-v1', requests
    finally:
        server.shutdown()
        server.server_close()


class ProbeTests(unittest.TestCase):
    def test_signed_complete_read(self):
        with endpoint() as (url, requests):
            self.assertEqual(PROBE.verify(url, 'fixture-access', 'fixture-secret'),
                             {'ok': True, 'reason': 'verified'})
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0]['Cache-Control'], 'no-cache')
        self.assertIn('Credential=fixture-access/', requests[0]['Authorization'])
        self.assertIn('SignedHeaders=host;x-amz-content-sha256;x-amz-date', requests[0]['Authorization'])

    def test_truncated_success_is_failure(self):
        with endpoint(body=bytes(32)) as (url, _):
            self.assertEqual(PROBE.verify(url, 'a', 's'), {'ok': False, 'reason': 'status_or_length'})

    def test_same_length_wrong_payload_is_failure(self):
        with endpoint(body=b'x' * 65536) as (url, _):
            self.assertEqual(PROBE.verify(url, 'a', 's'), {'ok': False, 'reason': 'checksum'})

    def test_extra_payload_is_failure(self):
        with endpoint(body=bytes(65537)) as (url, _):
            self.assertEqual(PROBE.verify(url, 'a', 's'), {'ok': False, 'reason': 'status_or_length'})

    def test_http_error_is_failure(self):
        with endpoint(status=503) as (url, _):
            self.assertEqual(PROBE.verify(url, 'a', 's'), {'ok': False, 'reason': 'read_error'})

    def test_redirect_does_not_pass_or_forward_credentials(self):
        with endpoint(status=302, redirect=True) as (url, requests):
            self.assertEqual(PROBE.verify(url, 'a', 's'), {'ok': False, 'reason': 'read_error'})
        self.assertEqual(len(requests), 1)

    def test_trickling_body_has_whole_request_deadline(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, 'access-key').write_text('fixture-access')
            Path(directory, 'secret-key').write_text('fixture-secret')
            with patch.dict(os.environ, {'CREDENTIALS_DIRECTORY': directory}):
                with endpoint(delay=.1) as (url, _):
                    self.assertEqual(PROBE.check(url, timeout=.3), {'ok': False, 'reason': 'deadline'})
                with endpoint() as (url, _):
                    self.assertEqual(PROBE.check(url), {'ok': True, 'reason': 'verified'})

    def test_check_success_and_missing_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {'CREDENTIALS_DIRECTORY': directory}):
                self.assertEqual(PROBE.check(), {'ok': False, 'reason': 'credentials_unavailable'})
                Path(directory, 'access-key').write_text('fixture-access')
                Path(directory, 'secret-key').write_text('fixture-secret')
                with endpoint() as (url, _):
                    self.assertEqual(PROBE.check(url), {'ok': True, 'reason': 'verified'})

    def test_failure_streak_and_recovery_are_exported(self):
        ledger = PROBE.Ledger()
        ledger.record({'ok': False}, 100)
        ledger.record({'ok': False}, 160)
        self.assertEqual(ledger.metrics(), 'seaweedfs_s3_read_probe_last_completed_timestamp_seconds 160\n'
                         'seaweedfs_s3_read_probe_success 0\nseaweedfs_s3_read_probe_consecutive_failures 2\n')
        ledger.record({'ok': True}, 220)
        self.assertEqual(ledger.metrics(), 'seaweedfs_s3_read_probe_last_completed_timestamp_seconds 220\n'
                         'seaweedfs_s3_read_probe_success 1\nseaweedfs_s3_read_probe_consecutive_failures 0\n')

class ProbeManifestTests(unittest.TestCase):
    def test_rendered_sidecar_references_the_generated_code(self):
        import json
        import subprocess
        app = PATH.parent
        rendered = subprocess.check_output(['kustomize', 'build', str(app)], text=True)
        documents = [json.loads(line) for line in subprocess.check_output(
            ['yq', '-o=json', '-I=0', 'select(.kind == "Seaweed" or .kind == "ConfigMap")'],
            input=rendered, text=True).splitlines()]
        configmaps = {item['metadata']['name']: item for item in documents if item['kind'] == 'ConfigMap'}
        seaweed = next(item for item in documents if item['kind'] == 'Seaweed')
        volume = next(v for v in seaweed['spec']['s3']['volumes'] if v['name'] == 'read-probe-code')
        self.assertEqual(configmaps[volume['configMap']['name']]['data']['s3-read-probe.py'], PATH.read_text())
