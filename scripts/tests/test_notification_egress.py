"""Keep the public webhook's outbound permissions narrow and wired into Flux."""
import json
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / 'kubernetes/apps/flux-system/flux-instance/app'


def read(path):
    return json.loads(subprocess.check_output(['yq', '-o=json', '.', str(path)], text=True))


class NotificationEgressTests(unittest.TestCase):
    def test_only_controller_component_is_selected(self):
        policy = read(APP / 'notification-egress.yaml')
        self.assertEqual(policy['kind'], 'CiliumNetworkPolicy')
        self.assertEqual(policy['metadata'], {'name': 'notification-controller-egress'})
        selector = policy['spec']['endpointSelector']['matchLabels']
        self.assertEqual(selector, {'app.kubernetes.io/component': 'notification-controller', 'app.kubernetes.io/part-of': 'flux'})
        for component in ['source-controller', 'kustomize-controller', 'helm-controller', 'image-automation-controller']:
            self.assertNotEqual(selector['app.kubernetes.io/component'], component)

    def test_only_dns_and_api_are_allowed(self):
        policy = read(APP / 'notification-egress.yaml')
        self.assertEqual(set(policy['spec']), {'endpointSelector', 'egress'})
        self.assertEqual(policy['spec']['egress'], [
            {'toEndpoints': [{'matchLabels': {'k8s:io.kubernetes.pod.namespace': 'kube-system', 'k8s:k8s-app': 'kube-dns'}}],
             'toPorts': [{'ports': [{'port': '53', 'protocol': 'UDP'}, {'port': '53', 'protocol': 'TCP'}]}]},
            {'toEntities': ['kube-apiserver'], 'toPorts': [{'ports': [{'port': '6443', 'protocol': 'TCP'}]}]},
        ])

    def test_existing_ingress_is_preserved(self):
        policy = read(APP / 'networkpolicy.yaml')
        self.assertEqual(policy['spec']['policyTypes'], ['Ingress'])
        self.assertEqual([r['ports'] for r in policy['spec']['ingress']], [
            [{'port': 9292, 'protocol': 'TCP'}], [{'port': 8080, 'protocol': 'TCP'}], [{'port': 9090, 'protocol': 'TCP'}]])

    def test_flux_wiring_and_crd_dependency(self):
        self.assertIn('./notification-egress.yaml', read(APP / 'kustomization.yaml')['resources'])
        self.assertIn({'name': 'cilium', 'namespace': 'kube-system'}, read(APP.parent / 'ks.yaml')['spec']['dependsOn'])

    def test_probe_does_not_join_webhook_service(self):
        probe = read(ROOT / 'scripts/tests/notification_egress/probe-pod.yaml')
        labels = probe['metadata']['labels']
        self.assertNotEqual(labels['app'], 'notification-controller')
        selector = read(APP / 'notification-egress.yaml')['spec']['endpointSelector']['matchLabels']
        self.assertTrue(all(labels.get(k) == v for k, v in selector.items()))
        self.assertFalse(probe['spec']['automountServiceAccountToken'])


if __name__ == '__main__':
    unittest.main()
