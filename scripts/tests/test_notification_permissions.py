"""Exercise the webhook permission boundary, including accidental broadening."""

import copy
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch
import json

REPO = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('notification_permissions', REPO / 'scripts/check-notification-permissions.py')
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class NotificationPermissionsTests(unittest.TestCase):
    def setUp(self):
        self.objects = MODULE.documents(MODULE.APP / 'notification-rbac.yaml')
        self.role = next(x for x in self.objects if x['kind'] == 'Role')

    def test_required_and_forbidden_requests(self):
        self.assertGreaterEqual(MODULE.validate_policy(self.objects), 100)

    def test_unrelated_secrets_cannot_be_read(self):
        rule = next(r for r in self.role['rules'] if r['resources'] == ['secrets'])
        rule.pop('resourceNames')
        with self.assertRaises(AssertionError):
            MODULE.validate_policy(self.objects)

    def test_secret_list_watch_cannot_be_added(self):
        self.role['rules'].append({'apiGroups': [''], 'resources': ['secrets'], 'verbs': ['list', 'watch']})
        with self.assertRaises(AssertionError):
            MODULE.validate_policy(self.objects)

    def test_webhook_target_writes_cannot_be_broadened(self):
        rule = next(r for r in self.role['rules'] if r['apiGroups'] == [MODULE.SOURCE] and r['verbs'] == ['patch'])
        rule.pop('resourceNames')
        with self.assertRaises(AssertionError):
            MODULE.validate_policy(self.objects)

    def test_cache_reads_are_required_for_delivery(self):
        self.role['rules'] = [r for r in self.role['rules'] if not (r['apiGroups'] == [MODULE.SOURCE] and 'watch' in r['verbs'])]
        with self.assertRaises(AssertionError):
            MODULE.validate_policy(self.objects)

    def test_wildcard_permissions_are_rejected(self):
        self.role['rules'].append({'apiGroups': ['*'], 'resources': ['*'], 'verbs': ['*']})
        with self.assertRaises(AssertionError):
            MODULE.validate_policy(self.objects)

    def test_binding_cannot_reuse_broad_cluster_role(self):
        binding = next(x for x in self.objects if x['kind'] == 'RoleBinding')
        binding['roleRef']['kind'] = 'ClusterRole'
        binding['roleRef']['name'] = 'crd-controller-flux-system'
        with self.assertRaises(AssertionError):
            MODULE.validate_policy(self.objects)

    def test_cross_namespace_subject_is_rejected(self):
        binding = next(x for x in self.objects if x['kind'] == 'RoleBinding')
        binding['subjects'][0]['namespace'] = 'default'
        with self.assertRaises(AssertionError):
            MODULE.validate_policy(self.objects)

    def test_authorizer_distinguishes_name_and_subresource(self):
        rules = copy.deepcopy(self.role['rules'])
        self.assertTrue(MODULE.allowed(rules, 'patch', MODULE.SOURCE, 'gitrepositories', name='flux-system'))
        self.assertFalse(MODULE.allowed(rules, 'patch', MODULE.SOURCE, 'gitrepositories/status', name='flux-system'))
        self.assertFalse(MODULE.allowed(rules, 'patch', MODULE.SOURCE, 'gitrepositories', name='auxiliary'))
        self.assertFalse(MODULE.allowed(rules, 'patch', MODULE.SOURCE, 'gitrepositories', namespace='default', name='flux-system'))

    def test_live_review_uses_explicit_subject_instead_of_proxy_impersonation(self):
        requests = []

        def respond(argv, **kwargs):
            if argv[1:3] == ['config', 'current-context']:
                return 'tailscale-operator.example.ts.net\n'
            self.assertNotIn('--as', argv)
            request = json.loads(kwargs['input'])
            requests.append(request)
            return json.dumps({**request, 'status': {'allowed': False}})

        case = (False, 'patch', MODULE.SOURCE, 'gitrepositories/status', MODULE.NS, 'flux-system')
        with patch.object(MODULE, 'permission_cases', return_value=[case]), \
                patch.object(MODULE.subprocess, 'check_output', side_effect=respond):
            self.assertTrue(MODULE.check_live_permissions()['passed'])
        self.assertEqual(requests[0]['spec']['user'], 'system:serviceaccount:flux-system:notification-controller-restricted')
        self.assertEqual(requests[0]['spec']['groups'], ['system:serviceaccounts', 'system:serviceaccounts:flux-system', 'system:authenticated'])
        self.assertEqual(requests[0]['spec']['resourceAttributes'], {
            'verb': 'patch', 'group': MODULE.SOURCE, 'resource': 'gitrepositories',
            'subresource': 'status', 'namespace': MODULE.NS, 'name': 'flux-system'})

    def test_live_review_fails_closed_on_unexpected_context(self):
        with patch.object(MODULE.subprocess, 'check_output', return_value='wrong-cluster\n') as query:
            with self.assertRaises(AssertionError):
                MODULE.check_live_permissions()
        self.assertEqual(query.call_count, 1)


if __name__ == '__main__':
    unittest.main()
