"""Fail-closed maintenance gates and uncertain compaction outcomes."""
import datetime as dt
import json
import os
from pathlib import Path
import copy
import subprocess
import tempfile
import unittest

APP = Path(__file__).resolve().parents[2] / "kubernetes/apps/registries/harbor-config/app"
GIB = 2**30
NOW = int(dt.datetime(2026, 10, 18, 8, tzinfo=dt.timezone.utc).timestamp())


def fixture():
    data = {
        "harbor": {
            "health": {"components": [{"name": "core", "status": "healthy"}]},
            "gc": {"schedule": {"type": "Custom", "cron": "0 30 5 * * 0"},
                   "parameters": {"dry_run": False, "delete_untagged": False, "workers": 1}},
            "gc_executions": [{"id": 8, "job_status": "Success", "job_kind": "SCHEDULE",
                               "creation_time": "2026-10-18T05:30:01Z", "update_time": "2026-10-18T05:45:00Z",
                               "parameters": {"dry_run": False, "delete_untagged": False, "workers": 1}}],
            "projects": [{"executions": [{"id": 7, "status": "Success", "dry_run": False,
                                          "start_time": "2026-10-18T01:30:01Z", "end_time": "2026-10-18T01:30:02Z"}]}]},
        "nodes": {"items": [{"status": {"conditions": [{"type": "Ready", "status": "True"}]}} for _ in range(3)]},
        "longhorn_volumes": {"items": [{"metadata": {"name": f"v{i}"}, "status": {"robustness": "healthy", "state": "attached"}} for i in range(3)]},
        "seaweed": [{"pod": f"seaweedfs-volume-{i}", "longhorn_volume": f"v{i}", "status": {
            "Version": "30GB 4.40 875cd1", "DiskStatuses": [{"dir": "/data0", "free": 20*GIB}],
            "Volumes": [{"Id": 20+i, "Size": 2*GIB, "DeletedByteCount": GIB//2,
                         "Collection": "harbor", "ReadOnly": False, "CompactRevision": 1}]}}
                    for i in range(3)]}
    policy={"algorithm":"or","trigger":{"kind":""},"rules":[
        {"params":{"latestPushedK":2}},
        {"template":"always","tag_selectors":[{"pattern":"{in-use-*,rollback}"}]},
        {"template":"always","tag_selectors":[{"pattern":"","extras":'{"untagged":true}'}]}]}
    project=data["harbor"]["projects"][0];project["policy"]=policy
    project["executions"][0]["policy_id"]=1
    data["filers"]=[{"pvc_uid":f"uid-{i}","longhorn_volume":f"filer-{i}"} for i in range(2)]
    data["images"]={"inventory_sha256":"a"*64}
    data["retention_evidence"]={"schema":1,"state":"Success","dry_run":False,
        "completed_at":int(dt.datetime(2026,10,18,1,31,tzinfo=dt.timezone.utc).timestamp()),
        "inventory_sha256":"a"*64,"filers":copy.deepcopy(data["filers"]),
        "executions":copy.deepcopy(project["executions"])}
    return data


class HarborReclamation(unittest.TestCase):
    def gate(self, data, now=NOW):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "gates.jq"
            script.write_text((APP / "reclamation-gates.jq").read_text().replace("$$", "$"))
            return subprocess.run(["jq", "--argjson", "now", str(now), "-f", str(script)],
                                  input=json.dumps(data), text=True, capture_output=True)

    def test_success_and_small_garbage_skip(self):
        data = fixture()
        self.assertEqual(len(json.loads(self.gate(data).stdout)["candidates"]), 3)
        data["seaweed"][0]["status"]["Volumes"][0]["DeletedByteCount"] = 255*2**20
        self.assertEqual(len(json.loads(self.gate(data).stdout)["candidates"]), 2)

    def test_reject_gc_dryrun_manual_failed_recent_or_previous_week(self):
        for key, value in [("parameters", {"dry_run": True, "delete_untagged": False, "workers": 1}),
                           ("job_kind", "MANUAL"), ("job_status", "Error"),
                           ("update_time", "2026-10-18T07:30:00Z"),
                           ("creation_time", "2026-10-11T05:30:01Z")]:
            with self.subTest(key=key):
                data = fixture()
                data["harbor"]["gc_executions"][0][key] = value
                self.assertNotEqual(self.gate(data).returncode, 0)

    def test_failed_or_after_gc_retention(self):
        for key, value in [("status", "Error"), ("dry_run", True), ("end_time", "2026-10-18T06:30:00Z")]:
            data = fixture()
            data["harbor"]["projects"][0]["executions"][0][key] = value
            self.assertNotEqual(self.gate(data).returncode, 0)

    def test_space_unhealthy_mapping_and_duplicate_ids(self):
        variants = []
        data = fixture(); data["seaweed"][0]["status"]["DiskStatuses"][0]["free"] = 4*GIB; variants.append(data)
        data = fixture(); data["longhorn_volumes"]["items"][0]["status"]["robustness"] = "degraded"; variants.append(data)
        data = fixture(); data["seaweed"][0]["longhorn_volume"] = "unknown"; variants.append(data)
        data = fixture(); data["seaweed"][1]["status"]["Volumes"][0]["Id"] = 20; variants.append(data)
        data = fixture(); data["nodes"]["items"][0]["status"]["conditions"][0]["status"] = "False"; variants.append(data)
        for data in variants:
            self.assertNotEqual(self.gate(data).returncode, 0)

    def script(self, mode="inspect-reclamation", volume_id=None, uncertain=False, missing_images=False):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp); data = fixture()
            (p / "data.json").write_text(json.dumps(data))
            (p / "reclamation-gates.jq").write_text((APP / "reclamation-gates.jq").read_text().replace("$$", "$"))
            script = (APP / "reclamation.sh").read_text().replace("$$", "$" ).replace("/tmp/", str(p)+"/")
            (p / "reclamation.sh").write_text(script)
            (p / "reconcile.sh").write_text("#!/bin/sh\nif [ \"$MODE\" = verify-images ] && [ \"${MISSING_IMAGES:-0}\" = 1 ]; then exit 1; fi\ncase \"$MODE\" in inspect) key=harbor ;; verify-images) key=images ;; verify-filers) key=filers ;; *) exit 1 ;; esac\njq \".$key\" \"$FIXTURE/data.json\"\n")
            (p / "date").write_text(f"#!/bin/sh\necho {NOW}\n"); (p / "date").chmod(0o755)
            kubectl = p / "kubectl"
            kubectl.write_text('''#!/usr/bin/env python3
import sys,json,os,pathlib,re
p=pathlib.Path(os.environ['FIXTURE']);d=json.loads((p/'data.json').read_text());a=sys.argv[1:]
if 'exec' in a:
 command=sys.stdin.read();i=int(re.search(r'-volumeId=(\\d+)',command).group(1))
 with (p/'actions').open('a') as f:f.write(str(i)+'\\n')
 if os.environ.get('UNCERTAIN')=='1':print('ERROR: lost acknowledgement');sys.exit(0)
 for s in d['seaweed']:
  for v in s['status']['Volumes']:
   if v['Id']==i:v['CompactRevision']+=1;v['Size']-=v['DeletedByteCount'];v['DeletedByteCount']=0
 (p/'data.json').write_text(json.dumps(d));print('completed');sys.exit(0)
if '--raw' in a:
 name=a[-1].split('/pods/')[1].split(':')[0];print(json.dumps(next(s['status'] for s in d['seaweed'] if s['pod']==name)))
elif 'configmap' in a:print(json.dumps({'data':{'evidence':json.dumps(d['retention_evidence'])}}))
elif 'node' in a:print(json.dumps(d['nodes']['items'][0]))
elif 'volumes.longhorn.io' in a:print(json.dumps(d['longhorn_volumes']))
elif 'pod' in a:
 i=a[a.index('pod')+1][-1];print(json.dumps({'spec':{'volumes':[{'persistentVolumeClaim':{'claimName':'claim'+i}}]}}))
elif 'pvc' in a:print('v'+a[a.index('pvc')+1][-1])
else:sys.exit(1)
'''); kubectl.chmod(0o755)
            env = {**os.environ, "PATH": str(p)+":"+os.environ["PATH"], "FIXTURE": str(p),
                   "RECLAMATION_HOME": str(p), "MODE": mode, "UNCERTAIN": "1" if uncertain else "0",
                   "MISSING_IMAGES": "1" if missing_images else "0"}
            if volume_id is not None:env["VOLUME_ID"] = str(volume_id)
            result = subprocess.run(["sh", str(p / "reclamation.sh")], env=env, capture_output=True, text=True, timeout=20)
            actions = (p / "actions").read_text().splitlines() if (p / "actions").exists() else []
            return result, actions

    def test_inspection_does_not_exec_and_unknown_id_stops(self):
        result, actions = self.script(); self.assertEqual(result.returncode, 0, result.stderr); self.assertEqual(actions, [])
        result, actions = self.script("apply-reclamation", 999); self.assertNotEqual(result.returncode, 0); self.assertEqual(actions, [])

    def test_apply_is_serial_and_checks_completion(self):
        result, actions = self.script("apply-reclamation")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(actions, ["20", "21", "22"])

    def test_uncertain_first_mutation_stops_without_retry_or_second_volume(self):
        result, actions = self.script("apply-reclamation", uncertain=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(actions, ["20"])

    def test_missing_retained_images_block_compaction(self):
        result, actions = self.script("apply-reclamation", missing_images=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(actions, [])

    def test_missing_stale_or_changed_protection_proof_blocks(self):
        for key,value in [("state","running"),("dry_run",True),("completed_at",0),
                          ("inventory_sha256","b"*64),("executions",[])]:
            data=fixture();data["retention_evidence"][key]=value
            self.assertNotEqual(self.gate(data).returncode,0,key)
        data=fixture();data.pop("retention_evidence")
        self.assertNotEqual(self.gate(data).returncode,0)
        data=fixture();data["filers"][0]["pvc_uid"]="replaced"
        self.assertNotEqual(self.gate(data).returncode,0)
        data=fixture();data["retention_evidence"]["executions"][0]["id"]=999
        self.assertNotEqual(self.gate(data).returncode,0)

    def test_independent_schedule_or_untagged_deletion_blocks(self):
        data=fixture();data["harbor"]["projects"][0]["policy"]["trigger"]["kind"]="Schedule"
        self.assertNotEqual(self.gate(data).returncode,0)
        data=fixture();data["harbor"]["projects"][0]["policy"]["rules"][2]["tag_selectors"][0]["extras"]='{"untagged":false}'
        self.assertNotEqual(self.gate(data).returncode,0)

    def test_automation_is_not_rendered_before_pilot(self):
        manifest = subprocess.check_output(["kustomize", "build", str(APP)], text=True)
        self.assertNotIn("name: harbor-physical-reclamation", manifest)
        self.assertNotIn("name: harbor-reclamation-node-reader", manifest)
