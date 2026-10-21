"""Exercise the real shell against a credential-free HTTP fixture."""
import http.server
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from harbor_fixture import write_kubectl, copy_scripts

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "kubernetes/apps/registries/harbor-config/app"


class HarborInspection(unittest.TestCase):
    def run_script(self, mode, schedule, expect_success=True, workload=None, missing_blob=False, missing_manifest=False, execution_status="Success", ambiguous_execution=False, empty_schedule=False, prior_evidence=None, fail_second_project=False):
        requests = []
        submitted = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                path = self.path
                if path == "/health":
                    body = {"components": [{"name": "core", "status": "healthy"}]}
                elif path.startswith("/service/token?"):
                    body = {"token": "never-print-token"}
                elif path.startswith("/projects/library/repositories/demo/artifacts/"):
                    body = {"digest": "sha256:" + "a"*64}
                elif path.startswith("/v2/library/demo/manifests/"):
                    if missing_manifest:
                        self.send_error(404)
                        return
                    body = {"schemaVersion": 2, "config": {"digest": "sha256:"+"b"*64}, "layers": []}
                elif path == "/system/gc/schedule":
                    if empty_schedule:
                        requests.append(("GET", path, None))
                        self.send_response(200); self.end_headers(); return
                    body = schedule
                elif path.startswith("/system/gc?"):
                    body = [{"id": 7, "job_status": "Success", "job_parameters": '{"dry_run":true,"delete_untagged":false,"workers":1}'}]
                elif path.startswith("/projects?"):
                    body = [{"project_id": 1}, {"project_id": 2}] if fail_second_project else [{"project_id": 1}]
                elif path in ["/projects/1/metadatas/", "/projects/2/metadatas/"]:
                    body = {"retention_id": "2" if "/projects/2/" in path else "1"}
                elif path in ["/retentions/1", "/retentions/2"]:
                    body = {"rules": []}
                elif path.startswith("/retentions/2/executions?"):
                    body = [{"id": 3, "policy_id": 2, "status": "Error"}] if len(submitted)>1 else []
                elif path.startswith("/retentions/1/executions?"):
                    body = [{"id": 2, "policy_id": 1, "start_time":"2026-10-13T22:00:00Z", "end_time":"2026-10-13T22:00:01Z",
                             "status": execution_status, "dry_run": submitted[-1]["dry_run"]}] if submitted else []
                    if submitted and ambiguous_execution: body.append({**body[0],"id":3})
                elif path.startswith("/repositories?"):
                    body = []
                else:
                    self.send_error(404)
                    return
                requests.append(("GET", path, None))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps(body).encode())

            def do_HEAD(self):
                requests.append(("HEAD", self.path, None))
                self.send_response(404 if missing_blob else 200)
                self.end_headers()

            def write(self):
                body = self.rfile.read(int(self.headers.get("content-length", 0)))
                requests.append((self.command, self.path, json.loads(body) if body else None))
                if self.command=="POST" and self.path in ["/retentions/1/executions", "/retentions/2/executions"]: submitted.append(json.loads(body))
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
                copy_scripts(p, APP)
                write_kubectl(p, workload if workload is not None else {"items": []}, prior_evidence)
                env = {**os.environ, "PATH": str(p) + ":" + os.environ["PATH"], "MODE": mode,
                       "HARBOR_SCRATCH_DIR": str(p),
                       "HARBOR_API_URL": f"http://127.0.0.1:{server.server_port}",
                       "HARBOR_USERNAME": "fixture", "HARBOR_PASSWORD": "never-print-fixture",
                       "HARBOR_RETENTION_CRON": "0 30 1 * * *", "HARBOR_PROTECTED_TAGS": "{in-use-*,rollback}",
                       "HARBOR_IMAGE_HOST": "registry", "HARBOR_GC_CRON": "0 30 5 * * 0",
                       "HARBOR_REGISTRY_URL": f"http://127.0.0.1:{server.server_port}",
                       "HARBOR_TOKEN_URL": f"http://127.0.0.1:{server.server_port}/service/token"}
                result = subprocess.run(["sh", str(script)], env=env, capture_output=True, text=True, timeout=10)
                self.assertNotIn("never-print-fixture", result.stdout + result.stderr)
                self.assertNotIn("never-print-token", result.stdout + result.stderr)
                if expect_success:
                    self.assertEqual(result.returncode, 0, result.stderr)
                else:
                    self.assertNotEqual(result.returncode, 0)
                self.kube_actions = [json.loads(line) for line in (p / "kube-actions").read_text().splitlines()] if (p / "kube-actions").exists() else []
                self.saved_evidence = json.loads((p / "evidence.json").read_text())["data"]
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

    def test_harbor_215_history_shaped_schedule(self):
        schedule = self.schedule()
        schedule["job_parameters"] = json.dumps(schedule.pop("parameters"))
        _, requests = self.run_script("reconcile", schedule)
        self.assertFalse(any(method != "GET" and path == "/system/gc/schedule" for method, path, _ in requests))
        output, requests = self.run_script("inspect", schedule)
        self.assertEqual(json.loads(output)["gc"]["parameters"]["workers"], 1)

    def test_omitted_false_dryrun_is_not_policy_drift(self):
        schedule = self.schedule()
        parameters = schedule.pop("parameters")
        parameters.pop("dry_run")
        schedule["job_parameters"] = json.dumps(parameters)
        _, requests = self.run_script("reconcile", schedule)
        self.assertFalse(any(method != "GET" and path == "/system/gc/schedule" for method, path, _ in requests))
        output, _ = self.run_script("inspect", schedule)
        self.assertFalse(json.loads(output)["gc"]["parameters"]["dry_run"])

    def test_malformed_parameters_do_not_reset_gc_schedule(self):
        schedule = self.schedule()
        schedule.pop("parameters")
        schedule["job_parameters"] = "not-json"
        _, requests = self.run_script("reconcile", schedule, expect_success=False)
        self.assertFalse(any(method != "GET" and path == "/system/gc/schedule" for method, path, _ in requests))

    def test_registry_manifest_and_blob_verification_is_read_only(self):
        workload = {"items": [{"spec": {"containers": [{"image": "registry/library/demo:v1"}]}}]}
        output, requests = self.run_script("verify-images", self.schedule(), workload=workload)
        result=json.loads(output)
        self.assertEqual(result["verified_artifacts"],1)
        self.assertEqual(result["readable_blobs"],1)
        self.assertEqual(len(result["inventory_sha256"]),64)
        self.assertTrue(all(method in {"GET", "HEAD"} for method, _, _ in requests))

    def test_missing_retained_blob_fails_verification(self):
        workload = {"items": [{"spec": {"containers": [{"image": "registry/library/demo:v1"}]}}]}
        _, requests = self.run_script("verify-images", self.schedule(), workload=workload,
                                      missing_blob=True, expect_success=False)
        self.assertTrue(any(method == "HEAD" for method, _, _ in requests))

    def test_missing_manifest_stops_before_blob_checks(self):
        workload = {"items": [{"spec": {"containers": [{"image": "registry/library/demo:v1"}]}}]}
        _, requests = self.run_script("verify-images", self.schedule(), workload=workload,
                                      missing_manifest=True, expect_success=False)
        self.assertFalse(any(method == "HEAD" for method, _, _ in requests))

    def test_real_retention_waits_for_success_and_publishes_proof(self):
        output, requests = self.run_script("retention", self.schedule())
        proof=json.loads(output.splitlines()[-1])
        self.assertFalse(proof["dry_run"])
        self.assertEqual(proof["executions"][0]["status"],"Success")
        self.assertEqual(len(self.kube_actions),2)
        saved=json.loads(json.loads(self.kube_actions[-1][-1])["data"]["evidence"])
        self.assertEqual(saved["state"],"Success")
        self.assertEqual(saved["executions"][0]["id"],2)

    def test_dryrun_never_publishes_real_success(self):
        output,_=self.run_script("retention-dry-run",self.schedule())
        self.assertTrue(json.loads(output.splitlines()[-1])["dry_run"])
        self.assertEqual(json.loads(self.saved_evidence["last_dry_run"])["state"], "Success")
        self.assertNotIn("evidence", self.saved_evidence)

    def test_failed_or_ambiguous_retention_leaves_invalid_proof(self):
        for arguments in [{"execution_status":"Error"},{"ambiguous_execution":True}]:
            self.run_script("retention",self.schedule(),expect_success=False,**arguments)
            failed=json.loads(self.saved_evidence["evidence"])
            self.assertEqual(failed["state"], "Failed")
            self.assertEqual(failed["phase"], "execute-retention")
            self.assertNotEqual(failed["exit_code"], 0)

    def test_failed_inventory_or_content_blocks_all_writes(self):
        for arguments in [{"workload":{}},{"workload":{"items":[{"spec":{"containers":[{"image":"registry/library/demo:v1"}]}}]},"missing_manifest":True}]:
            _,requests=self.run_script("retention",self.schedule(),expect_success=False,**arguments)
            self.assertTrue(all(method in {"GET","HEAD"} for method,_,_ in requests))
            failed=json.loads(self.saved_evidence["evidence"])
            self.assertEqual(failed["state"], "Failed")
            self.assertIn(failed["phase"], ["inventory", "verify-images"])
            self.assertEqual(failed["executions"], [])

    def test_preflight_failure_preserves_last_success(self):
        prior={"schema":1,"state":"Success","dry_run":False,"completed_at":123,"inventory_sha256":"a"*64}
        self.run_script("retention",self.schedule(),workload={},expect_success=False,
                        prior_evidence={"evidence":json.dumps(prior)})
        self.assertEqual(json.loads(self.saved_evidence["last_success"]),prior)
        failed=json.loads(self.saved_evidence["last_attempt"])
        self.assertEqual(failed["state"],"Failed")
        self.assertEqual(failed["phase"],"inventory")
        self.assertEqual(failed["executions"],[])
        self.assertNotEqual(failed["exit_code"],0)

    def test_partial_execution_failure_records_completed_project(self):
        self.run_script("retention",self.schedule(),expect_success=False,fail_second_project=True)
        failed=json.loads(self.saved_evidence["evidence"])
        self.assertEqual(failed["state"],"Failed")
        self.assertEqual(failed["phase"],"execute-retention")
        self.assertEqual(failed["project_id"],"2")
        self.assertEqual(failed["policy_id"],"2")
        self.assertEqual([(e["id"],e["policy_id"],e["status"]) for e in failed["executions"]],
                         [(2,1,"Success")])

    def test_dryrun_failure_and_success_preserve_real_proof(self):
        prior={"schema":1,"state":"Success","dry_run":False,"completed_at":123}
        for status in ["Success","Error"]:
            with self.subTest(status=status):
                self.run_script("retention-dry-run",self.schedule(),execution_status=status,
                                expect_success=status=="Success",prior_evidence={"evidence":json.dumps(prior)})
                self.assertEqual(json.loads(self.saved_evidence["evidence"]),prior)
                evidence=json.loads(self.saved_evidence["last_dry_run"])
                self.assertEqual(evidence["state"],"Success" if status=="Success" else "Failed")
                self.assertTrue(evidence["dry_run"])

    def test_large_inventory_stays_out_of_process_arguments(self):
        workload={"items":[{"metadata":{"annotations":{"large":"x"*300000}},"spec":{"containers":[{"image":"registry/library/demo:v1"}]}}]}
        output,_=self.run_script("verify-images",self.schedule(),workload=workload)
        self.assertEqual(json.loads(output)["verified_artifacts"],1)

    def test_disabled_gc_empty_body_is_inspectable_without_writes(self):
        output,requests=self.run_script("inspect",self.schedule(),empty_schedule=True)
        self.assertEqual(json.loads(output)["gc"],{"schedule":{"type":"None","cron":None},"parameters":None})
        self.assertTrue(all(method=="GET" for method,_,_ in requests))
