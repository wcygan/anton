"""Approved live test only: run inside a temporary pod as the restricted account.

All target PATCH requests use dryRun=All. Never prints the projected token.
"""
import datetime
import json
import os
from pathlib import Path
import ssl
import urllib.error
import urllib.request

IDENTITY = 'system:serviceaccount:flux-system:notification-controller-restricted'
POLICY = 'notification-controller-reconcile-only'
ANNOTATION = 'reconcile.fluxcd.io/requestedAt'


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


def main():
    mounted = Path('/var/run/secrets/kubernetes.io/serviceaccount')
    host = os.environ['KUBERNETES_SERVICE_HOST']
    if ':' in host:
        host = '[' + host + ']'
    base = 'https://' + host + ':' + os.environ.get('KUBERNETES_SERVICE_PORT_HTTPS', '443')
    token = mounted.joinpath('token').read_text().strip()
    opener = urllib.request.build_opener(
        NoRedirect(), urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=str(mounted / 'ca.crt'))))

    def api(path, method='GET', body=None, patch=False):
        request = urllib.request.Request(base + path, method=method,
            data=None if body is None else json.dumps(body).encode(),
            headers={'Authorization': 'Bearer ' + token,
                     'Content-Type': 'application/merge-patch+json' if patch else 'application/json'})
        try:
            response = opener.open(request, timeout=15)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.code, json.loads(response.read(1024 * 1024))

    status, identity = api('/apis/authentication.k8s.io/v1/selfsubjectreviews', 'POST',
        {'apiVersion': 'authentication.k8s.io/v1', 'kind': 'SelfSubjectReview', 'spec': {}})
    assert status == 201 and identity['status']['userInfo']['username'] == IDENTITY, 'Unexpected pod identity'
    results = []
    value = datetime.datetime.now(datetime.timezone.utc).isoformat()
    for group, resource in [('source.toolkit.fluxcd.io', 'gitrepositories'),
                             ('kustomize.toolkit.fluxcd.io', 'kustomizations')]:
        path = '/apis/' + group + '/v1/namespaces/flux-system/' + resource + '/flux-system'
        status, old = api(path)
        assert status == 200, 'Cannot read the intended target'
        request = {'metadata': {'annotations': {ANNOTATION: value}}}
        cases = [('annotation only', request, True)]
        def bundled(**changes):
            return {'metadata': {'annotations': {ANNOTATION: value}}, **changes}
        cases.append(('bundle spec change', bundled(spec={'suspend': not old['spec'].get('suspend', False)}), False))
        if resource == 'gitrepositories':
            cases.append(('change Git URL', bundled(spec={'url': 'https://example.invalid/guard-check.git'}), False))
        else:
            cases.append(('change manifest path', bundled(spec={'path': './guard-check'}), False))
        cases += [
            ('change labels', {'metadata': {'annotations': {ANNOTATION: value}, 'labels': {'anton.wcygan.net/guard-check': 'true'}}}, False),
            ('change finalizers', {'metadata': {'annotations': {ANNOTATION: value}, 'finalizers': ['anton.wcygan.net/guard-check']}}, False),
            ('change owners', {'metadata': {'annotations': {ANNOTATION: value}, 'ownerReferences': [{'apiVersion': 'v1', 'kind': 'ConfigMap', 'name': 'guard-check', 'uid': '11111111-1111-1111-1111-111111111111'}]}}, False),
            ('change another annotation', {'metadata': {'annotations': {ANNOTATION: value, 'reconcile.fluxcd.io/forceAt': value}}}, False),
            ('remove request', {'metadata': {'annotations': {ANNOTATION: None}}}, False),
        ]
        for name, body, permitted in cases:
            status, result = api(path + '?dryRun=All', 'PATCH', body, patch=True)
            if permitted:
                assert status == 200 and result['metadata']['annotations'][ANNOTATION] == value, 'Reconciliation dry run rejected'
            else:
                assert status == 403 and POLICY in result.get('message', ''), 'Expected denial by the admission guard was not observed'
            results.append({'resource': resource, 'case': name, 'http_status': status, 'dry_run': True})
        status, after = api(path)
        assert status == 200 and after['metadata']['uid'] == old['metadata']['uid']
        assert after['spec'] == old['spec'], 'Concurrent configuration change; verification inconclusive'
        assert after['metadata'].get('annotations', {}) == old['metadata'].get('annotations', {}), 'Concurrent annotation change; verification inconclusive'
    print(json.dumps({'identity': IDENTITY, 'tests': results, 'passed': True}, indent=2))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(json.dumps({'passed': False, 'failure_type': type(error).__name__,
                          'detail': str(error) if isinstance(error, AssertionError) else 'Probe failed; raw error suppressed'}))
        raise SystemExit(1)
