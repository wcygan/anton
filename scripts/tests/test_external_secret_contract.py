"""Tests for the ExternalSecret traffic and reference contract."""

from __future__ import annotations

import copy
import json
import tempfile
from pathlib import Path

import unittest

from scripts.lib.external_secret_contract import load_external_secrets, validate_admission_guard, validate_contract


PATH = "kubernetes/apps/example/app/externalsecret.yaml"


def manifest() -> dict:
    return {
        "apiVersion": "external-secrets.io/v1",
        "kind": "ExternalSecret",
        "metadata": {
            "name": "example-credentials",
            "annotations": {"anton.wcygan.net/secret-refresh-class": "stable"},
        },
        "spec": {
            "refreshPolicy": "Periodic",
            "refreshInterval": "24h",
            "secretStoreRef": {
                "kind": "ClusterSecretStore",
                "name": "onepassword-connect",
            },
            "target": {
                "name": "example-credentials",
                "creationPolicy": "Owner",
            },
            "data": [
                {
                    "secretKey": "username",
                    "remoteRef": {"key": "example/username"},
                }
            ],
        },
    }


def inventory() -> dict:
    return {
        "dailyOperationLimit": 250,
        "manifests": {
            PATH: {
                "name": "example-credentials",
                "targetName": "example-credentials",
                "targetKeys": ["username"],
                "refreshClass": "stable",
                "remoteRefs": ["example/username"],
                "extractItems": [],
            }
        },
    }


class AdmissionPolicyContractTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).resolve().parents[1] / "data/external-secret-admission-contract.json"
        self.documents = [
            {"kind": kind, "metadata": {"name": "external-secret-onepassword-guard"}, "spec": spec}
            for kind, spec in json.loads(path.read_text()).items()
        ]

    def test_accepts_reviewed_spec(self):
        self.assertEqual(validate_admission_guard(self.documents), ())

    def test_rejects_permissive_expression_with_original_tokens(self):
        for index in range(len(self.documents[0]["spec"]["validations"])):
            documents = copy.deepcopy(self.documents)
            validation = documents[0]["spec"]["validations"][index]
            validation["expression"] = "true || (" + validation["expression"] + ")"
            self.assertTrue(validate_admission_guard(documents))

    def test_rejects_selectors_that_skip_validation(self):
        for index in (0, 1):
            documents = copy.deepcopy(self.documents)
            documents[index]["spec"].setdefault("matchResources" if index else "matchConstraints", {})["namespaceSelector"] = {"matchLabels": {"skip": "yes"}}
            self.assertTrue(validate_admission_guard(documents))


class ExternalSecretDiscoveryTests(unittest.TestCase):
    def test_discovers_quoted_kind_flow_yaml_and_yml(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            root = repo / "kubernetes/apps/example"
            root.mkdir(parents=True)
            for filename, content in (
                ("quoted.yaml", '\"kind\": ExternalSecret\nmetadata: {name: quoted}\n'),
                ("flow.yml", json.dumps(manifest())),
            ):
                (root / filename).write_text(content)
            documents = load_external_secrets(repo)
            self.assertEqual(len(documents), 2)
            self.assertTrue(all(item["kind"] == "ExternalSecret" for item in documents.values()))
            self.assertTrue(any("not approved" in failure for failure in validate_contract(documents, inventory()).failures))

    def test_keeps_multiple_documents_distinct(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            root = repo / "kubernetes/apps/example"
            root.mkdir(parents=True)
            (root / "multiple.yaml").write_text("\n---\n".join(json.dumps(manifest()) for _ in range(2)))
            documents = load_external_secrets(repo)
            self.assertEqual(len(documents), 2)
            self.assertTrue(any("not approved" in failure for failure in validate_contract(documents, inventory()).failures))


class ExternalSecretContractTests(unittest.TestCase):
    def test_accepts_approved_stable_reference(self) -> None:
        report = validate_contract({PATH: manifest()}, inventory())

        self.assertEqual(report.failures, ())
        self.assertEqual(report.scheduled_operations, 1)

    def test_rejects_malformed_combined_key(self) -> None:
        candidate = manifest()
        candidate["spec"]["data"][0]["remoteRef"]["key"] = "example"

        report = validate_contract({PATH: candidate}, inventory())

        self.assertTrue(any("combined key" in failure for failure in report.failures))

    def test_rejects_unapproved_reference(self) -> None:
        candidate = manifest()
        candidate["spec"]["data"][0]["remoteRef"]["key"] = "example/password"

        report = validate_contract({PATH: candidate}, inventory())

        self.assertTrue(any("approved references" in failure for failure in report.failures))

    def test_rejects_property_with_sdk_provider(self) -> None:
        candidate = manifest()
        candidate["spec"]["data"][0]["remoteRef"]["property"] = "username"

        report = validate_contract({PATH: candidate}, inventory())

        self.assertTrue(any("remoteRef.property" in failure for failure in report.failures))

    def test_rejects_secret_contract_drift(self) -> None:
        candidate = manifest()
        candidate["spec"]["target"]["name"] = "renamed-credentials"
        candidate["spec"]["data"][0]["secretKey"] = "renamed-key"

        report = validate_contract({PATH: candidate}, inventory())

        self.assertTrue(any("target name" in failure for failure in report.failures))
        self.assertTrue(any("target keys" in failure for failure in report.failures))

    def test_rejects_unclassified_refresh_policy(self) -> None:
        candidate = manifest()
        del candidate["metadata"]["annotations"]

        report = validate_contract({PATH: candidate}, inventory())

        self.assertTrue(any("refresh class" in failure for failure in report.failures))

    def test_rejects_fast_stable_refresh(self) -> None:
        candidate = manifest()
        candidate["spec"]["refreshInterval"] = "1h"

        report = validate_contract({PATH: candidate}, inventory())

        self.assertTrue(any("at least 24h" in failure for failure in report.failures))

    def test_on_change_has_no_scheduled_operations(self) -> None:
        candidate = manifest()
        candidate["metadata"]["annotations"][
            "anton.wcygan.net/secret-refresh-class"
        ] = "development"
        candidate["spec"]["refreshPolicy"] = "OnChange"
        del candidate["spec"]["refreshInterval"]
        approved = inventory()
        approved["manifests"][PATH]["refreshClass"] = "development"

        report = validate_contract({PATH: candidate}, approved)

        self.assertEqual(report.failures, ())
        self.assertEqual(report.scheduled_operations, 0)

    def test_rejects_traffic_above_daily_limit(self) -> None:
        candidate = manifest()
        refs = []
        data = []
        keys = []
        for index in range(251):
            secret_key = f"key-{index}"
            remote_ref = f"example/field-{index}"
            keys.append(secret_key)
            refs.append(remote_ref)
            data.append({"secretKey": secret_key, "remoteRef": {"key": remote_ref}})
        candidate["spec"]["data"] = data
        approved = inventory()
        approved["manifests"][PATH]["targetKeys"] = keys
        approved["manifests"][PATH]["remoteRefs"] = refs

        report = validate_contract({PATH: candidate}, approved)

        self.assertTrue(any("daily operation limit" in failure for failure in report.failures))

    def test_rejects_find_and_unknown_manifests(self) -> None:
        candidate = manifest()
        candidate["spec"]["dataFrom"] = [{"find": {"name": {"regexp": ".*"}}}]
        documents = {PATH: candidate, "kubernetes/apps/extra/externalsecret.yaml": manifest()}

        report = validate_contract(documents, inventory())

        self.assertTrue(any("dataFrom.find" in failure for failure in report.failures))
        self.assertTrue(any("not approved" in failure for failure in report.failures))

    def test_admission_guard_requires_deny_binding(self) -> None:
        policy = {
            "kind": "ValidatingAdmissionPolicy",
            "metadata": {"name": "external-secret-onepassword-guard"},
            "spec": {
                "failurePolicy": "Fail",
                "matchConstraints": {
                    "resourceRules": [
                        {
                            "apiGroups": ["external-secrets.io"],
                            "apiVersions": ["v1"],
                            "operations": ["CREATE", "UPDATE"],
                            "resources": ["externalsecrets"],
                        }
                    ]
                },
                "validations": [
                    {
                        "expression": " ".join(
                            (
                                "onepassword-connect",
                                "anton.wcygan.net/secret-refresh-class",
                                "duration('24h')",
                                "remoteRef.key.matches",
                                "!has(entry.remoteRef.property)",
                                "dataFrom",
                            )
                        )
                    }
                ],
            },
        }
        binding = {
            "kind": "ValidatingAdmissionPolicyBinding",
            "spec": {
                "policyName": "external-secret-onepassword-guard",
                "validationActions": ["Warn"],
            },
        }

        failures = validate_admission_guard([policy, binding])

        self.assertIn("admission guard binding must use Deny", failures)


if __name__ == "__main__":
    unittest.main()
