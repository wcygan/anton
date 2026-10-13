"""Credential-free Kubernetes fixtures for the real Harbor shell adapter."""
import json
from pathlib import Path


def filer_data():
    pods=[];claims=[];volumes=[]
    for i in range(2):
        name=f'seaweedfs-filer-{i}';claim=f'seaweedfs-filer-{name}'
        pods.append({'metadata':{'name':name},'spec':{'containers':[{'name':'filer','volumeMounts':[{'name':'data','mountPath':'/data'}]}], 'volumes':[{'name':'data','persistentVolumeClaim':{'claimName':claim}}]}, 'status':{'conditions':[{'type':'Ready','status':'True'}]}})
        claims.append({'metadata':{'name':claim,'uid':f'pvc-uid-{i}'},'spec':{'volumeName':f'v{i}'},'status':{'phase':'Bound'}})
        volumes.append({'metadata':{'name':f'v{i}'},'status':{'robustness':'healthy','state':'attached'}})
    return {'pods':{'items':pods},'claims':{'items':claims},'volumes':{'items':volumes}}


def write_kubectl(directory, workload):
    p=Path(directory)
    p.joinpath('kube-fixture.json').write_text(json.dumps({'workload':workload,**filer_data()}))
    script=p/'kubectl'
    script.write_text('''#!/usr/bin/env python3
import json,sys,pathlib
p=pathlib.Path(__file__).parent;d=json.loads((p/'kube-fixture.json').read_text());a=sys.argv[1:]
if '-A' in a:print(json.dumps(d['workload']))
elif 'ingresses' in a:print('{"items":[]}')
elif 'pods' in a:print(json.dumps(d['pods']))
elif 'pvc' in a:print(json.dumps(d['claims']))
elif 'volumes.longhorn.io' in a:print(json.dumps(d['volumes']))
elif 'patch' in a:
 with (p/'kube-actions').open('a') as f:f.write(json.dumps(a)+'\\n')
else:sys.exit(1)
''')
    script.chmod(0o755)


def copy_scripts(directory, app):
    for name in ['helpers.sh','protected-images.jq','filer-persistence.jq']:
        Path(directory,name).write_text(Path(app,name).read_text().replace('$$','$'))
