#!/usr/bin/env python3
"""Disposable amd64 migration qualification. Never calls Kubernetes or production."""
import argparse,hashlib,importlib.util,ipaddress,json,subprocess,time,traceback
from pathlib import Path
from urllib.parse import urlencode

spec=importlib.util.spec_from_file_location('rehearsal',Path(__file__).parents[1]/'seaweedfs-durability/rehearse.py')
r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)
b=r.b;m=r.m
IMAGE='sha256:6636cc129d5a27328999eda8d9f424772da01831fbd7667781e102b433651efd'
GRPC='sha256:ac0f176ac1038811a69b9004b6619d7eebe5ddbb521645bd9bfb3167816babb3'
RAW=b.ORIGINAL_DOCKER
RELAY='sha256:b6e5d14867528ed7ac3dbcea6e8d99be33be0e41d34ada04cab1a7587360810d'
b.LOKI='sha256:e08b7f504501aada07bd6d4b79c4468f6480393740c483d1c3785cafaf1f2370'

class Lab(r.Rehearsal):
    def __init__(self,directory):
        super().__init__(directory,IMAGE)
        self.versions=dict.fromkeys(self.roles,'durable')
        self.fenced=False;self.default='000';self.rpc_count=0;self.loki_generation=0
        self.slots=24;self.relay=False
        self.port_map={(role,port):10000+i for i,(role,port) in enumerate(
            [(r,'9333') for r in ['master','master-b','master-c']]+
            [(r,'8080') for r in ['volume','volume-b','volume-c']]+
            [(r,p) for r in ['s3','s3-b'] for p in ['8333','9327']]+
            [('registry','5000'),('loki','3100')])}

    def route(self,*args,**kwargs):
        if len(args)>=3 and args[0]=='port':
            key=(args[1].removeprefix(self.name+'-'),args[2].split('/')[0])
            if key in self.port_map:return RAW('port',self.name+'-relay',str(self.port_map[key])+'/tcp')
        return RAW(*args,**kwargs)

    def wrapped_docker(self,*args,**kwargs):
        a=list(args)
        if a[:2]==['network','create']:
            networks=json.loads(RAW('network','inspect',*RAW('network','ls','-q').splitlines()))
            occupied=[ipaddress.ip_network(c['Subnet']) for n in networks for c in (n['IPAM'].get('Config') or []) if c.get('Subnet')]
            def available(prefix):
                for offset in range(254):
                    i=(int(self.name[-2:],16)+offset)%254+1
                    candidate=ipaddress.ip_network(prefix+str(i)+'.0/24')
                    if not any(candidate.overlaps(old) for old in occupied):return str(candidate)
                raise RuntimeError('no private rehearsal subnet available')
            a[2:2]=['--internal','--subnet',available('10.211.')];result=RAW(*a,**kwargs)
            RAW('network','create','--subnet',available('10.212.'),'--label','anton.migration-rehearsal=true',self.name+'-gateway')
            cfg=self.directory/'Caddyfile'
            cfg.write_text('{\n admin off\n auto_https off\n}\n'+''.join(
                f':{port} {{\n reverse_proxy {role}:{target}\n}}\n' for (role,target),port in self.port_map.items()))
            cmd=['run','-d','--name',self.name+'-relay','--network',self.name+'-gateway',
                 '--memory','96m','--label','anton.migration-rehearsal=true','-v',str(cfg)+':/etc/caddy/Caddyfile:ro']
            for port in self.port_map.values():cmd+=['-p','127.0.0.1::'+str(port)]
            self.relay=True
            RAW(*cmd,'--entrypoint','caddy',RELAY,'run','--config','/etc/caddy/Caddyfile','--adapter','caddyfile')
            RAW('network','connect',self.name,self.name+'-relay');self.relay=True
            return result
        if a and a[0]=='run' and '--name' in a:
            role=a[a.index('--name')+1].removeprefix(self.name+'-')
            if role in self.roles:
                a=[v.replace('-defaultReplication=000','-defaultReplication='+self.default)
                   .replace('-volumeSizeLimitMB=64','-volumeSizeLimitMB=5000')
                   .replace('-max=20','-max='+str(self.slots)) for v in a]
                idx=a.index('--entrypoint')
                a[idx:idx]=['-e','WEED_MASTER_VOLUME_GROWTH_COPY_2=1',
                            '-e','WEED_MASTER_VOLUME_GROWTH_DISABLE='+str(self.fenced).lower()]
                if not role.startswith('s3'):
                    vi=a.index('-v');vol=self.name+'-'+role+'-data'
                    if vol not in self.named:
                        b.ORIGINAL_DOCKER('volume','create','--label','anton.durability=true',vol);self.named.add(vol)
                    a[vi+1]=vol+':/data'
                if role.startswith('volume'):a[a.index('--entrypoint'):a.index('--entrypoint')]=['-p','127.0.0.1::8080']
                if role.startswith('filer'):
                    cfg=self.directory/(role+'.toml');cfg.write_text('[leveldb2]\nenabled=true\ndir="/data/filerldb2"\nsync=true\n')
                    a[a.index('--entrypoint'):a.index('--entrypoint')]=['-v',str(cfg)+':/etc/seaweedfs/filer.toml:ro']
        # Applications use ORIGINAL_DOCKER directly; route only their Loki data mount here.
        return b.ORIGINAL_DOCKER(*a,**kwargs)

    def app(self,*args,**kwargs):
        if args[0]=='loki':kwargs['platform']='linux/amd64'
        original=b.ORIGINAL_DOCKER
        def application(*a,**kw):
            a=list(a)
            if a and a[0]=='run' and '--name' in a and a[a.index('--name')+1]==self.name+'-loki':
                vol=self.name+'-loki-data-'+str(self.loki_generation)
                if vol not in self.named:
                    original('volume','create','--label','anton.durability=true',vol);self.named.add(vol)
                a[1:1]=['-v',vol+':/tmp/loki']
            return original(*a,**kw)
        b.ORIGINAL_DOCKER=application
        try:return b.Comparison.app(self,*args,**kwargs)
        finally:b.ORIGINAL_DOCKER=original

    def start(self):
        b.ORIGINAL_DOCKER=self.route
        m.docker=self.wrapped_docker;m.Lab.start(self)
        net=json.loads(b.ORIGINAL_DOCKER('network','inspect',self.name))[0]
        assert net['Internal'] and not net['EnableIPv6']
        for role in self.roles:
            x=self.identity(role);assert not x['HostConfig']['Privileged']
            for mount in x['Mounts']:
                if mount['Type']=='bind':assert str(self.directory) in mount['Source']
        for bucket in ['qualification','harbor','loki','s3-read-probe']:
            assert self.request('PUT','/'+bucket)[0]==200
        self.record('isolation_verified',network_internal=net['Internal'],host_bindings='loopback only',production_credentials=False,image=m.IMAGES['durable'])

    def cleanup(self):
        if not self.owns_directory:return
        if self.relay:
            logs=subprocess.run(['docker','logs',self.name+'-relay'],capture_output=True,text=True)
            (self.directory/'relay.log').write_text(logs.stdout+logs.stderr)
            RAW('rm','-f',self.name+'-relay',check=False)
        RAW('network','rm',self.name+'-gateway',check=False)
        try:super().cleanup()
        finally:
            RAW('network','rm',self.name+'-gateway',check=False)
            b.ORIGINAL_DOCKER=RAW;m.docker=RAW
            assert not RAW('ps','-aq','--filter','name='+self.name)
            assert not RAW('network','ls','-q','--filter','name='+self.name)
            assert not RAW('volume','ls','-q','--filter','name='+self.name)

    def identity(self,role):return json.loads(b.ORIGINAL_DOCKER('inspect',self.name+'-'+role))[0]
    def binding(self,role):
        x=self.identity(role)
        return {'id':x['Id'],'ip':x['NetworkSettings']['Networks'][self.name]['IPAddress'],
                'mounts':[(v['Destination'],v.get('Name',v['Source'])) for v in x['Mounts']]}
    def guard(self,role,bound):
        if self.binding(role)!=bound:raise ValueError('identity changed: '+role)
    def rpc(self,address,method,payload,timeout=8,check=True):
        self.rpc_count+=1;name=self.name+'-rpc-'+str(self.rpc_count)
        cmd=['docker','run','--rm','--name',name,'--network',self.name,'--memory','128m',GRPC,
             '-max-time',str(timeout),'-plaintext','-d',json.dumps(payload),address,
             method if '/' in method else 'volume_server_pb.VolumeServer/'+method]
        try:
            x=subprocess.run(cmd,capture_output=True,text=True,timeout=timeout+10)
        finally:b.ORIGINAL_DOCKER('rm','-f',name,check=False)
        if check:
            assert x.returncode==0,(method,x.stderr)
            assert not ('"error":' in x.stdout.lower()),x.stdout
        return x
    def at(self,role,method,payload,timeout=8):
        bound=self.binding(role);self.guard(role,bound)
        result=self.rpc(bound['ip']+':18080',method,payload,timeout)
        self.guard(role,bound);return result
    def volumes(self):
        out={}
        for role in ['volume','volume-b','volume-c']:
            if role not in self.active:continue
            port=b.ORIGINAL_DOCKER('port',self.name+'-'+role,'8080/tcp')
            status,body,_=b.http('GET','http://'+port+'/status',timeout=5);assert status==200,(role,status,body[:300])
            for v in json.loads(body)['Volumes'] or []:out.setdefault(v['Id'],[]).append((role,v))
        return out
    def shell(self,commands):
        x=subprocess.run(['docker','exec','-i',self.name+'-master','weed','shell',
                          '-master=master:9333','-filer=filer:8888'],input=commands,
                         capture_output=True,text=True,timeout=30)
        assert x.returncode==0,(x.stdout,x.stderr)
        assert not any(w in (x.stdout+x.stderr).lower() for w in ['rpc error','error:','command not found']),x.stdout+x.stderr
        return x.stdout+x.stderr
    def hashfiles(self,role,vid,collection):
        stem=(collection+'_' if collection else '')+str(vid)
        x=b.ORIGINAL_DOCKER('exec',self.name+'-'+role,'sha256sum',
                           *['/data/'+stem+ext for ext in ['.dat','.idx','.vif']])
        return {line.split()[1].rsplit('.',1)[1]:line.split()[0] for line in x.splitlines()}
    def require_empty_destination(self,role,vid,collection):
        bound=self.binding(role)
        if any(r==role for r,_ in self.volumes().get(vid,[])):
            raise ValueError('destination already serves volume '+str(vid))
        stem=(collection+'_' if collection else '')+str(vid)
        files=b.ORIGINAL_DOCKER('exec',self.name+'-'+role,'find','/data','-maxdepth','1','-name',stem+'.*','-print')
        self.guard(role,bound)
        if files:raise ValueError('destination has existing or partial files: '+files)
    def leader(self):
        states={role:json.loads(b.http('GET',self.urls[role]+'/cluster/status')[1])
                for role in ['master','master-b','master-c'] if role in self.active}
        return next(role for role,s in states.items() if s.get('IsLeader'))
    def restart_masters(self,fenced,default):
        self.fenced=fenced;self.default=default;leader=self.leader()
        for role in [v for v in ['master','master-b','master-c'] if v!=leader]+[leader]:
            self.stop(role);self.launch(role);self.verify_quorum()
        self.record('master_settings_verified',growth_disabled=fenced,default=default)

def registry_read(lab,state):
    url=lab.apps['registry']+'/v2/qualification/image'
    for digest in state['layer_hashes']:
        status,body,_=b.http('GET',url+'/blobs/'+digest)
        assert status==200 and hashlib.sha256(body).hexdigest()==digest[7:]
    config='sha256:'+hashlib.sha256(b'{}').hexdigest()
    assert b.http('GET',url+'/blobs/'+config)[:2]==(200,b'{}')
    status,body,_=b.http('GET',url+'/manifests/test',headers={'Accept':'application/vnd.oci.image.manifest.v1+json'})
    assert status==200
    manifest=json.loads(body)
    assert [v['digest'] for v in manifest['layers']]==state['layer_hashes']
    assert manifest['config']['digest']==config

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    p.add_argument('--sweep-seconds',type=int,default=660);args=p.parse_args()
    assert args.sweep_seconds>=660,'cover two full background sweeps'
    assert not args.output.exists(),'refuse to overwrite existing evidence'
    lab=Lab(args.output.resolve());summary={}
    try:
        lab.start()
        # Real application writes produce the legacy corpus.
        lab.start_registry();summary['registry_before']=b.registry_work(lab)
        lab.start_loki();summary['loki_before']=b.loki_work(lab)
        cold={}
        for bucket in ['qualification','harbor','loki','s3-read-probe']:
            for i in range(6):
                body=hashlib.shake_256((bucket+str(i)).encode()).digest(1024*1024)
                key='/'+bucket+'/never-read-'+str(i)
                assert lab.request('PUT',key,body)[0]==200;cold[key]=body
        legacy=lab.volumes();assert legacy and all(len(c)==1 for c in legacy.values())
        cold_map={}
        for key in cold:
            output=b.ORIGINAL_DOCKER('exec',lab.name+'-filer','wget','-qO-',
                                      'http://127.0.0.1:8888/buckets'+key+'?metadata=true')
            chunks=json.loads(output)['chunks'];assert len(chunks)==1
            cold_map[key]={'fid':chunks[0]['file_id'],'vid':int(chunks[0]['file_id'].split(',')[0])}
        (lab.directory/'cold-map.json').write_text(json.dumps(cold_map,indent=2)+'\n')
        lab.record('legacy_corpus',volumes={str(k):[r for r,_ in v] for k,v in legacy.items()})
        lab.restart_masters(True,'001')
        # Freeze writers and preserve Loki WAL while S3 is unavailable.
        lab.stop('s3');lab.stop('s3-b');lab.stop('filer');lab.stop('filer-b')
        outage_start=time.monotonic()
        # Persistent hard-RO, then clean process replacement drains admitted work.
        for vid,copies in legacy.items():
            role,v=copies[0];lab.at(role,'VolumeMarkReadonly',{'volumeId':vid,'persist':True})
        old={role:lab.binding(role) for role in ['volume','volume-b','volume-c']}
        lab.move=60
        for role in ['volume','volume-b','volume-c']:
            lab.stop(role);lab.launch(role)
        lab.wait(lambda:set(lab.volumes())==set(legacy))
        assert all(v['ReadOnly'] for copies in lab.volumes().values() for _,v in copies)
        # Refuse stale identities and observe failed old-IP RPC before the safe path.
        src=legacy[max(legacy,key=lambda v:legacy[v][0][1]['Size'])][0][0]
        vid=max(legacy,key=lambda v:legacy[v][0][1]['Size'])
        try:lab.guard(src,old[src]);raise AssertionError('old identity accepted')
        except ValueError:pass
        failed=lab.rpc(old[src]['ip']+':18080','VolumeConfigure',{'volumeId':vid,'replication':'001'},timeout=2,check=False)
        assert failed.returncode!=0
        lab.record('stale_address_rejected',role=src,old=old[src],current=lab.binding(src),rpc_error=failed.stderr)
        # Verify pre-copy rollback on one exact singleton.
        before=lab.hashfiles(src,vid,legacy[vid][0][1]['Collection'])
        stem=(legacy[vid][0][1]['Collection']+'_' if legacy[vid][0][1]['Collection'] else '')+str(vid)
        before_vif=json.loads(b.ORIGINAL_DOCKER('exec',lab.name+'-'+src,'cat','/data/'+stem+'.vif'))
        lab.at(src,'VolumeConfigure',{'volumeId':vid,'replication':'001'})
        lab.at(src,'VolumeConfigure',{'volumeId':vid,'replication':'000'})
        after=lab.hashfiles(src,vid,legacy[vid][0][1]['Collection'])
        after_vif=json.loads(b.ORIGINAL_DOCKER('exec',lab.name+'-'+src,'cat','/data/'+stem+'.vif'))
        lab.record('precopy_rollback_comparison',vid=vid,before_hashes=before,after_hashes=after,before_vif=before_vif,after_vif=after_vif)
        assert all(after[k]==before[k] for k in ['dat','idx'])
        assert before_vif.get('replication','000') in ['','000'] and after_vif.get('replication')=='000'
        assert {k:v for k,v in before_vif.items() if k!='replication'}=={k:v for k,v in after_vif.items() if k!='replication'}
        assert all(v['ReadOnly'] for _,v in lab.volumes()[vid])
        lab.record('precopy_rollback_verified',vid=vid,data_and_index_unchanged=True,replication_restored='000',readonly_retained=True)
        # Ingest numbered records throughout a real object-store outage.
        start=time.time_ns();expected=[]
        for i in range(1000):expected.append([str(start+i*1000000),'migration-outage-'+str(i)])
        payload=json.dumps({'streams':[{'stream':{'qualification':'migration-outage'},'values':expected}]}).encode()
        response=b.http('POST',lab.apps['loki']+'/loki/api/v1/push',payload,{'Content-Type':'application/json'})
        assert response[0]==204
        b.http('POST',lab.apps['loki']+'/flush',b'',timeout=10)
        # Measured real background sweeps, with a leader replacement mid-fence.
        deadline=time.monotonic()+args.sweep_seconds;changed=False
        while time.monotonic()<deadline:
            assert set(lab.volumes())==set(legacy),'unexpected growth while fenced'
            if not changed and time.monotonic()>deadline-args.sweep_seconds/2:
                leader=lab.leader();lab.stop(leader);lab.launch(leader);lab.verify_quorum();changed=True
                lab.record('fenced_leader_replaced',role=leader)
            time.sleep(5)
        lab.record('growth_fence_passed',seconds=args.sweep_seconds,leader_replaced=changed,volumes=len(legacy))
        # One exact non-destructive copy at a time; retain completed pairs on abort.
        counts={role:sum(role==r for c in lab.volumes().values() for r,_ in c) for role in ['volume','volume-b','volume-c']}
        pairs={}
        for vid,copies in sorted(legacy.items(),key=lambda item:-item[1][0][1]['Size']):
            src,v=copies[0];dst=min((r for r in counts if r!=src),key=lambda r:counts[r])
            lab.require_empty_destination(dst,vid,v['Collection'])
            lab.at(src,'VolumeConfigure',{'volumeId':vid,'replication':'001'})
            bound=lab.binding(src);t=time.monotonic()
            lab.at(dst,'VolumeCopy',{'volumeId':vid,'sourceDataNode':bound['ip']+':8080'},timeout=90)
            lab.guard(src,bound)
            hashes=lab.hashfiles(src,vid,v['Collection']);assert hashes==lab.hashfiles(dst,vid,v['Collection'])
            pairs[vid]=(src,dst);counts[dst]+=1
            lab.record('copy_verified',vid=vid,source=src,destination=dst,hashes=hashes,seconds=time.monotonic()-t)
        for vid,pair in pairs.items():
            for role in pair:lab.at(role,'VolumeMarkWritable',{'volumeId':vid})
        lab.record('completed_pairs_retained',pairs_retained=True,deleted_copies=0)
        # Refresh topology under the growth fence before re-enabling it.
        lab.restart_masters(True,'001')
        for role in ['filer','filer-b','s3','s3-b']:lab.launch(role)
        lab.wait(lambda:lab.request('GET','/')[0]==200)
        summary['outage_seconds']=time.monotonic()-outage_start
        for bucket in ['harbor','loki']:
            lab.shell(f'fs.configure -locationPrefix=/buckets/{bucket}/ -fsync -replication=001 -apply\n')
        lab.restart_masters(False,'001')
        # Cold bytes on both gateways, then absence of either original owner.
        lab.gateway='s3';lab.placement()
        # Wait for WAL-backed outage records to persist and read exact sequence.
        def query():
            q=urlencode({'query':'{qualification="migration-outage"}','start':start-1,'end':start+2_000_000_000,'limit':2000,'direction':'forward'})
            status,body,_=b.http('GET',lab.apps['loki']+'/loki/api/v1/query_range?'+q)
            if status!=200:return False
            lines=[v for s in json.loads(body)['data']['result'] for v in s['values']]
            return lines==expected
        lab.wait(query,timeout=120)
        lab.wait(lambda:b.metric(b.http('GET',lab.apps['loki']+'/metrics')[1].decode(),'loki_ingester_flush_queue_length')==0,timeout=180)
        lab.stop('loki');lab.start_loki();lab.wait(query)
        summary['outage_records']=1000
        # Read original data before any test helper can upload it again.
        registry_read(lab,summary['registry_before'])
        lab.stop('loki');lab.loki_generation+=1
        summary['cold_loki_before']=b.cold_loki(lab,summary['loki_before'])
        lab.wait(query,timeout=120)
        summary['cold_outage_records']=1000
        lab.record('original_applications_verified_read_only',registry_bytes=summary['registry_before']['verified_layer_bytes'],original_logs=8000,outage_logs=1000)
        summary['registry_after']=b.registry_work(lab)
        summary['loki_after']=b.loki_work(lab)
        lab.stop('loki');lab.loki_generation+=1
        summary['cold_loki']=b.cold_loki(lab,summary['loki_after'])
        lab.stop('loki')
        # Each role is an isolated node-equivalent serving process, not a real drain.
        consumed_cold=set()
        for owner_index,owner in enumerate(['volume','volume-b','volume-c']):
            affected={key:entry for key,entry in cold_map.items() if owner in pairs[entry['vid']]}
            assert affected,'hold did not withdraw any real owner'
            reads={}
            lab.stop(owner)
            for gateway_index,gateway in enumerate(['s3','s3-b']):
                lab.gateway=gateway
                checked=[]
                for bucket in sorted({key.split('/')[1] for key in affected}):
                    key=next(key for key in affected if key.split('/')[1]==bucket and key not in consumed_cold)
                    consumed_cold.add(key);checked.append(key)
                    assert lab.request('GET',key,timeout=10)[1]==cold[key]
                reads[gateway]=checked
                key='/harbor/owner-absent-'+owner+'-'+gateway;body=hashlib.sha256(key.encode()).digest()
                assert lab.request('PUT',key,body)[0]==200 and lab.request('GET',key)[1]==body
            lab.launch(owner);lab.wait(lambda:all(len(c)==2 for c in lab.volumes().values()))
            lab.record('owner_absent_exact_reads_and_writes',owner=owner,gateways=2,affected=affected,checked=reads)
        lab.gateway='s3'
        # Re-enable long enough to expose resurrection of old empty layouts.
        end=time.monotonic()+args.sweep_seconds
        while time.monotonic()<end:
            assert all(len(c)==2 and all(1+sum(v['ReplicaPlacement'].values())==2 for _,v in c) for c in lab.volumes().values())
            time.sleep(5)
        lab.record('growth_reenabled_without_singletons',seconds=args.sweep_seconds)
        summary['passed']=True;(lab.directory/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
        lab.record('qualification_passed',summary=summary)
    except BaseException:
        if lab.directory.exists():(lab.directory/'failure.txt').write_text(traceback.format_exc())
        raise
    finally:lab.cleanup()

if __name__=='__main__':main()
