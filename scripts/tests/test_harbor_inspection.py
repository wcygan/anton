"""Exercise the real shell against a credential-free HTTP fixture."""
import http.server
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "kubernetes/apps/registries/harbor-config/app"


class HarborInspection(unittest.TestCase):
    def run_script(self, mode, schedule):
        requests = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                path = self.path
                if path == "/system/gc/schedule":
                    body = schedule
                elif path.startswith("/system/gc?"):
                    body = [{"id": 7, "job_status": "Success", "job_parameters": '{"dry_run":true,"delete_untagged":false,"workers":1}'}]
                elif path.startswith("/projects?"):
                    body = [{"project_id": 1}]
                elif path == "/projects/1/metadatas/":
                    body = {"retention_id": "1"}
                elif path == "/retentions/1":
                    body = {"rules": []}
                elif path.startswith("/retentions/1/executions?"):
                    body = [{"id": 2, "status": "Success", "dry_run": False}]
                elif path.startswith("/repositories?"):
                    body = []
                else:
                    self.send_error(404)
                    return
                requests.append(("GET", path, None))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps(body).encode())

            def write(self):
                body = self.rfile.read(int(self.headers.get("content-length", 0)))
                requests.append((self.command, self.path, json.loads(body) if body else None))
                self.send_response(200)
                self.end_headers()
            do_POST = write
            do_PUT = write
            do_DELETE = write

        server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                p = Path(tmp)
                script = p / "reconcile.sh"
                script.write_text((APP / "reconcile.sh").read_text().replace("$$", "$"))
                kubectl = p / "kubectl"
                kubectl.write_text("#!/bin/sh\nprintf '%s' '{\"items\":[]}'\n")
                kubectl.chmod(0o755)
                env = {**os.environ, "PATH": str(p) + ":" + os.environ["PATH"], "MODE": mode,
                       "HARBOR_API_URL": f"http://127.0.0.1:{server.server_port}",
                       "HARBOR_USERNAME": "fixture", "HARBOR_PASSWORD": "never-print-fixture",
                       "HARBOR_RETENTION_CRON": "0 30 1 * * *", "HARBOR_PROTECTED_TAGS": "{in-use-*,rollback}",
                       "HARBOR_IMAGE_HOST": "registry", "HARBOR_GC_CRON": "0 30 5 * * 0"}
                result = subprocess.run(["sh", str(script)], env=env, capture_output=True, text=True, timeout=10)
                self.assertNotIn("never-print-fixture", result.stdout + result.stderr)
                self.assertEqual(result.returncode, 0, result.stderr)
                return result.stdout, requests
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    @staticmethod
    def schedule():
        return {"schedule": {"type": "Custom", "cron": "0 30 5 * * 0", "next_scheduled_time": "ignored"},
                "parameters": {"dry_run": False, "delete_untagged": False, "workers": 1}}

    def test_inspection_never_mutates(self):
        output, requests = self.run_script("inspect", self.schedule())
        self.assertTrue(all(method == "GET" for method, _, _ in requests))
        self.assertTrue(json.loads(output)["gc_executions"][0]["parameters"]["dry_run"])

    def test_gc_parameters_drift_even_when_cron_matches(self):
        for key, value in [("dry_run", True), ("delete_untagged", True), ("workers", 4)]:
            with self.subTest(key=key):
                schedule = self.schedule()
                schedule["parameters"][key] = value
                _, requests = self.run_script("reconcile", schedule)
                self.assertTrue(any(method == "PUT" and path == "/system/gc/schedule" for method, path, _ in requests))

    def test_matching_gc_does_not_write_gc(self):
        _, requests = self.run_script("reconcile", self.schedule())
        self.assertFalse(any(method != "GET" and path == "/system/gc/schedule" for method, path, _ in requests))
