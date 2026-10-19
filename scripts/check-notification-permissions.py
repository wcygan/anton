"""Check the proposed webhook identity without contacting Kubernetes."""

import argparse
import concurrent.futures
import json
from pathlib import Path
import re
import subprocess

REPO = Path(__file__).resolve().parents[1]
APP = REPO / 'kubernetes/apps/flux-system/flux-instance/app'
IDENTITY = 'notification-controller-restricted'
NS = 'flux-system'
NOTIFY = 'notification.toolkit.fluxcd.io'
SOURCE = 'source.toolkit.fluxcd.io'
KUSTOMIZE = 'kustomize.toolkit.fluxcd.io'


def documents(path):
    result = subprocess.check_output(['yq', '-o=json', '-I=0', '.', str(path)], text=True)
    return [json.loads(line) for line in result.splitlines() if line.strip() and line != 'null']


def allowed(rules, verb, group, resource, namespace=NS, name=None):
    if namespace != NS:
        return False
    return any(verb in rule['verbs'] and group in rule['apiGroups']
               and resource in rule['resources']
               and ('resourceNames' not in rule or name in rule['resourceNames'])
               for rule in rules)


def permission_cases():
    cases = []
    def add(expected, verbs, group, resource, namespace=NS, name=None):
        cases.extend((expected, verb, group, resource, namespace, name) for verb in verbs)
    add(True, ['get'], '', 'secrets', name='github-webhook-token-secret')
    add(False, ['list', 'watch', 'create', 'update', 'patch', 'delete'], '', 'secrets')
    for secret in ['sops-age', 'cluster-secrets', 'unrelated-secret']:
        add(False, ['get'], '', 'secrets', name=secret)
    for group, resource in [(SOURCE, 'gitrepositories'), (KUSTOMIZE, 'kustomizations')]:
        add(True, ['get', 'list', 'watch'], group, resource)
        add(True, ['patch'], group, resource, name='flux-system')
        add(False, ['patch'], group, resource, name='auxiliary')
        add(False, ['create', 'update', 'delete'], group, resource, name='flux-system')
        add(False, ['patch'], group, resource + '/status', name='flux-system')
    for resource in ['receivers', 'alerts', 'providers']:
        add(True, ['get', 'list', 'watch'], NOTIFY, resource)
        add(False, ['create', 'delete'], NOTIFY, resource, name='github-webhook')
        add(False, ['patch', 'update'], NOTIFY, resource, name='unrelated')
    for resource in ['receivers', 'receivers/status']:
        add(True, ['patch', 'update'], NOTIFY, resource, name='github-webhook')
    add(True, ['create'], '', 'events')
    add(True, ['patch'], '', 'events', name='an-event')
    add(True, ['create'], 'coordination.k8s.io', 'leases')
    add(True, ['get', 'update', 'patch'], 'coordination.k8s.io', 'leases', name='notification-controller-leader-election')
    add(False, ['get', 'update', 'patch', 'delete'], 'coordination.k8s.io', 'leases', name='source-controller-leader-election')
    for namespace in ['default', 'network', 'kube-system', 'other']:
        add(False, ['get'], '', 'secrets', namespace, 'github-webhook-token-secret')
        add(False, ['get', 'list', 'patch'], SOURCE, 'gitrepositories', namespace, 'flux-system')
    for group, resource in [('', 'pods'), ('', 'pods/exec'), ('', 'serviceaccounts/token'),
                            ('', 'configmaps'), ('', 'serviceaccounts'),
                            ('rbac.authorization.k8s.io', 'roles'),
                            ('rbac.authorization.k8s.io', 'rolebindings'),
                            ('helm.toolkit.fluxcd.io', 'helmreleases')]:
        add(False, ['get', 'create', 'patch', 'delete'], group, resource, name='anything')
    return cases


def validate_policy(objects):
    sa, = [x for x in objects if x['kind'] == 'ServiceAccount']
    role, = [x for x in objects if x['kind'] == 'Role']
    binding, = [x for x in objects if x['kind'] == 'RoleBinding']
    assert len(objects) == 3, 'Only a ServiceAccount, Role, and RoleBinding belong here'
    for x in objects:
        assert x['metadata']['name'] == IDENTITY
        assert x['metadata'].get('namespace', NS) == NS
    assert binding['roleRef'] == {'apiGroup': 'rbac.authorization.k8s.io', 'kind': 'Role', 'name': IDENTITY}
    assert binding['subjects'] == [{'kind': 'ServiceAccount', 'name': IDENTITY, 'namespace': NS}]
    assert not sa.get('secrets'), 'Do not mount legacy service account tokens'
    for rule in role['rules']:
        assert set(rule) <= {'apiGroups', 'resources', 'resourceNames', 'verbs'}
        assert not any('*' in item for values in rule.values() for item in values), 'Wildcards are forbidden'
    for expected, verb, group, resource, namespace, name in permission_cases():
        actual = allowed(role['rules'], verb, group, resource, namespace, name)
        assert actual == expected, f'{verb} {group}/{resource} {namespace}/{name}: expected {expected}, got {actual}'
    return len(permission_cases())


def validate_render(before, after):
    def index(objects):
        return {(x['kind'], x['metadata'].get('namespace', ''), x['metadata']['name']): x for x in objects}
    old, new = index(before), index(after)
    assert old.keys() == new.keys(), 'Controller inventory must not change'
    changed = [key for key in old if old[key] != new[key]]
    assert changed == [('Deployment', NS, 'notification-controller')], changed
    key, = changed
    original, proposed = old[key], new[key]
    old_spec = original['spec']['template']['spec']
    spec = proposed['spec']['template']['spec']
    assert old_spec['serviceAccountName'] == 'notification-controller'
    assert spec['serviceAccountName'] == IDENTITY
    args = spec['containers'][0]['args']
    assert '--watch-all-namespaces=false' in args
    assert '--no-cross-namespace-refs=true' in args
    gates, = [a for a in args if a.startswith('--feature-gates=')]
    assert set(gates.removeprefix('--feature-gates=').split(',')) == {
        'ObjectLevelWorkloadIdentity=false', 'CacheSecretsAndConfigMaps=false', 'DisableConfigWatchers=true'}
    for name in ['watch-all-namespaces', 'feature-gates', 'no-cross-namespace-refs']:
        assert len([a for a in args if a.startswith('--' + name + '=')]) == 1
    assert any(e['name'] == 'RUNTIME_NAMESPACE' and e['valueFrom']['fieldRef']['fieldPath'] == 'metadata.namespace'
               for e in spec['containers'][0]['env'])
    restored = json.loads(json.dumps(proposed))
    restored['spec']['template']['spec']['serviceAccountName'] = old_spec['serviceAccountName']
    restored['spec']['template']['spec']['containers'][0]['args'] = old_spec['containers'][0]['args']
    assert restored == original, 'Only serviceAccountName and controller arguments may change'
    for obj in after:
        if obj['kind'] in ['ClusterRoleBinding', 'RoleBinding']:
            assert not any(s.get('name') == IDENTITY for s in obj.get('subjects', [])), 'New identity inherited distribution RBAC'
    return len(new)


def check_live_permissions():
    context = subprocess.check_output(['kubectl', 'config', 'current-context'], text=True).strip()
    assert re.fullmatch(r'tailscale-operator\..+\.ts\.net', context), 'Unexpected Kubernetes context'
    identity = 'system:serviceaccount:' + NS + ':' + IDENTITY
    groups = ['system:serviceaccounts', 'system:serviceaccounts:' + NS, 'system:authenticated']

    def check(case):
        expected, verb, group, resource, namespace, name = case
        base, _, subresource = resource.partition('/')
        attributes = {'namespace': namespace, 'verb': verb, 'group': group, 'resource': base}
        if subresource:
            attributes['subresource'] = subresource
        if name:
            attributes['name'] = name
        request = {'apiVersion': 'authorization.k8s.io/v1', 'kind': 'SubjectAccessReview',
                   'spec': {'user': identity, 'groups': groups, 'resourceAttributes': attributes}}
        response = subprocess.check_output(
            ['kubectl', 'create', '--raw', '/apis/authorization.k8s.io/v1/subjectaccessreviews', '-f', '-'],
            input=json.dumps(request), text=True, timeout=30)
        result = json.loads(response)
        assert result['spec']['user'] == identity, 'Authorization review changed subject'
        status = result['status']
        assert not status.get('evaluationError'), 'Authorization evaluation failed'
        return {**attributes, 'expected': expected, 'allowed': status['allowed'],
                'passed': status['allowed'] == expected}

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(check, permission_cases()))
    return {'identity': identity, 'checks': results, 'passed': all(x['passed'] for x in results)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rendered-before', type=Path)
    parser.add_argument('--rendered-after', type=Path)
    parser.add_argument('--live', action='store_true', help='Query non-persisted SubjectAccessReviews for the proposed identity')
    parser.add_argument('--live-report', type=Path)
    args = parser.parse_args()
    assert bool(args.rendered_before) == bool(args.rendered_after), 'Supply both renders'
    count = validate_policy(documents(APP / 'notification-rbac.yaml'))
    config, = documents(APP / 'kustomization.yaml')
    assert './notification-rbac.yaml' in config['resources']
    receiver, = documents(APP / 'receiver.yaml')
    assert receiver['spec']['interval'] == '1m'
    assert receiver['spec']['type'] == 'github' and receiver['spec']['events'] == ['ping', 'push']
    assert receiver['spec']['secretRef'] == {'name': 'github-webhook-token-secret'}
    assert receiver['spec']['resources'] == [
        {'apiVersion': SOURCE + '/v1', 'kind': 'GitRepository', 'name': NS, 'namespace': NS},
        {'apiVersion': KUSTOMIZE + '/v1', 'kind': 'Kustomization', 'name': NS, 'namespace': NS}]
    print(f'PASS: {count} allow/deny decisions; namespaced binding; unchanged receiver targets and authentication')
    if args.rendered_before:
        count = validate_render(documents(args.rendered_before), documents(args.rendered_after))
        print(f'PASS: {count} rendered objects compared; only notification-controller identity and arguments change')
    else:
        print('Controller render comparison not requested; live enforcement and webhook delivery remain unverified')
    if args.live:
        report = check_live_permissions()
        if args.live_report:
            args.live_report.write_text(json.dumps(report, indent=2) + '\n')
        failures = [x for x in report['checks'] if not x['passed']]
        assert not failures, json.dumps(failures)
        print(f'PASS: {len(report["checks"])} API-server authorization decisions for the explicit service account subject')


if __name__ == '__main__':
    main()
