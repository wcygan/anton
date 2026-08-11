"""Behavior tests for the shared SeaweedFS bucket provisioner."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
APP = REPO / "kubernetes" / "apps" / "storage" / "seaweedfs-config" / "app"

FAKE_AWS = textwrap.dedent(
    r"""
    #!/usr/bin/env python3
    import json
    import os
    import re
    import sys
    from pathlib import Path

    state_path = Path(os.environ["FAKE_AWS_STATE"])
    state = json.loads(state_path.read_text())
    args = sys.argv[1:]
    service_index = next(i for i, value in enumerate(args) if value in {"s3api", "s3", "s3tables"})
    service, operation = args[service_index], args[service_index + 1]

    def option(name):
        index = args.index(name)
        return args[index + 1]

    def save():
        state_path.write_text(json.dumps(state))

    if service == "s3api" and operation == "list-buckets":
        print(json.dumps({"Buckets": [{"Name": name} for name in state["ordinary"]]}))
    elif service == "s3api" and operation == "head-bucket":
        raise SystemExit(0 if option("--bucket") in state["ordinary"] else 1)
    elif service == "s3" and operation == "mb":
        name = args[-1].removeprefix("s3://")
        if name not in state["ordinary"]:
            state["ordinary"].append(name)
            save()
    elif service == "s3tables" and operation == "list-table-buckets":
        if "--query" not in args:
            print(json.dumps({"tableBuckets": state["tables"]}))
        else:
            match = re.search(r"name=='([^']+)'", option("--query"))
            name = match.group(1) if match else ""
            print(f"arn:aws:s3tables:us-east-1:000000000000:bucket/{name}" if name in state["tables"] else "None")
    elif service == "s3tables" and operation == "create-table-bucket":
        name = option("--name")
        if name not in state["tables"]:
            state["tables"].append(name)
            save()
    elif service == "s3tables" and operation == "get-table-bucket":
        name = option("--table-bucket-arn").rsplit("/", 1)[-1]
        raise SystemExit(0 if name in state["tables"] else 1)
    else:
        print(f"unsupported fake aws call: {args}", file=sys.stderr)
        raise SystemExit(2)
    """
).lstrip()


class SeaweedFSBucketProvisionerTests(unittest.TestCase):
    @staticmethod
    def strict_flux_substitution(manifest: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["flux", "envsubst", "--strict"],
            input=manifest,
            capture_output=True,
            text=True,
            env={"PATH": os.environ["PATH"]},
            timeout=10,
        )

    @classmethod
    def setUpClass(cls) -> None:
        rendered = subprocess.run(
            ["kustomize", "build", str(APP)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if rendered.returncode != 0:
            raise RuntimeError(rendered.stderr)

        provisioner = subprocess.run(
            [
                "yq",
                'select(.kind == "ConfigMap" and .metadata.name == "seaweedfs-bucket-provisioner")',
                "-",
            ],
            input=rendered.stdout,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if provisioner.returncode != 0:
            raise RuntimeError(provisioner.stderr)

        strict = cls.strict_flux_substitution(provisioner.stdout)
        if strict.returncode != 0:
            raise RuntimeError(strict.stderr)

        script = subprocess.run(
            ["yq", "-r", '.data["provision-buckets.sh"]', "-"],
            input=strict.stdout,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if script.returncode != 0:
            raise RuntimeError(script.stderr)
        cls.rendered_provisioner = script.stdout

    def run_provisioner(
        self,
        state: dict[str, list[str]],
        *,
        ordinary: str = "harbor loki iceberg-raw",
        tables: str = "iceberg-warehouse",
    ) -> tuple[subprocess.CompletedProcess[str], dict]:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake = root / "aws"
            fake.write_text(FAKE_AWS, encoding="utf-8")
            fake.chmod(0o755)
            state_path = root / "state.json"
            state_path.write_text(json.dumps(state), encoding="utf-8")
            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{root}:{env['PATH']}",
                    "FAKE_AWS_STATE": str(state_path),
                    "S3_ENDPOINT": "http://example.invalid:8333",
                    "ORDINARY_BUCKETS": ordinary,
                    "TABLE_BUCKETS": tables,
                }
            )
            result = subprocess.run(
                ["/bin/sh", "-s"],
                input=self.rendered_provisioner,
                capture_output=True,
                text=True,
                env=env,
                timeout=10,
            )
            return result, json.loads(state_path.read_text(encoding="utf-8"))

    def test_flux_strict_substitution_rejects_unescaped_shell_expansion(self) -> None:
        result = self.strict_flux_substitution(
            "apiVersion: v1\n"
            "kind: ConfigMap\n"
            "data:\n"
            "  provision-buckets.sh: |-\n"
            '    length="${#bucket}"\n'
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('variable not set (strict mode): "bucket"', result.stderr)

    def test_flux_strict_substitution_preserves_escaped_shell_expansion(self) -> None:
        result = self.strict_flux_substitution(
            "apiVersion: v1\n"
            "kind: ConfigMap\n"
            "data:\n"
            "  provision-buckets.sh: |-\n"
            '    length="$${#bucket}"\n'
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('length="${#bucket}"', result.stdout)

    def test_create_then_idempotent_recheck(self) -> None:
        first, state = self.run_provisioner({"ordinary": [], "tables": []})
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertIn("created=4 present=0", first.stdout)
        self.assertEqual(sorted(state["ordinary"]), ["harbor", "iceberg-raw", "loki"])
        self.assertEqual(state["tables"], ["iceberg-warehouse"])

        second, unchanged = self.run_provisioner(state)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn("created=0 present=4", second.stdout)
        self.assertEqual(unchanged, state)

    def test_refuses_ordinary_bucket_at_table_intent(self) -> None:
        initial = {"ordinary": ["iceberg-warehouse"], "tables": []}
        result, state = self.run_provisioner(initial)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("bucket kind collision", result.stderr)
        self.assertEqual(state, initial)

    def test_rejects_invalid_or_dual_kind_intent_before_writes(self) -> None:
        initial = {"ordinary": [], "tables": []}
        invalid, invalid_state = self.run_provisioner(initial, ordinary="bad_name")
        self.assertNotEqual(invalid.returncode, 0)
        self.assertIn("invalid bucket intent", invalid.stderr)
        self.assertEqual(invalid_state, initial)

        duplicate, duplicate_state = self.run_provisioner(
            initial, ordinary="harbor shared-bucket", tables="shared-bucket"
        )
        self.assertNotEqual(duplicate.returncode, 0)
        self.assertIn("two kinds", duplicate.stderr)
        self.assertEqual(duplicate_state, initial)


if __name__ == "__main__":
    unittest.main()
