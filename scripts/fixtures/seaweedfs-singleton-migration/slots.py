#!/usr/bin/env python3
"""Real 20-to-24-slot allocation and growth-disable negative control, local only."""
import ipaddress,json,traceback
from pathlib import Path
import run as q

def main():
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    p.add_argument('--image',default=q.IMAGE);p.add_argument('--expect-http-blocked',action='store_true');a=p.parse_args()
    assert not a.output.exists()
    lab=q.Lab(a.output.resolve());lab.roles=['master','volume'];lab.ha=False
    lab.versions=dict.fromkeys(lab.roles,'durable');lab.fenced=True;lab.default='001';lab.slots=20
    assert a.image.startswith('sha256:') and len(a.image)==71
    q.m.IMAGES['durable']=a.image
    try:
        lab.directory.mkdir(parents=True);lab.owns_directory=True
        for role in lab.roles:(lab.directory/role).mkdir()
        q.b.ORIGINAL_DOCKER=lab.route;q.m.docker=lab.wrapped_docker
        lab.wrapped_docker('network','create','--label','anton.migration-rehearsal=true',lab.name)
        net=json.loads(q.RAW('network','inspect',lab.name))[0];assert net['Internal']
        lab.subnet=ipaddress.ip_network(net['IPAM']['Config'][0]['Subnet'])
        lab.launch('master');lab.launch('volume')
        lab.wait(lambda:lab.volumes()=={})
        lab.wait(lambda:q.b.http('GET',lab.urls['master']+'/cluster/status')[0]==200)
        for i in range(1,21):lab.at('volume','AllocateVolume',{'volumeId':1000+i,'collection':'slots','replication':'000','version':3})
        ip=lab.binding('volume')['ip']
        fail20=lab.rpc(ip+':18080','AllocateVolume',{'volumeId':1021,'collection':'slots','replication':'000','version':3},check=False)
        assert fail20.returncode!=0 and len(lab.volumes())==20
        original={vid:lab.hashfiles('volume',vid,'slots') for vid in lab.volumes()}
        lab.slots=24;lab.stop('volume');lab.launch('volume')
        lab.wait(lambda:len(lab.volumes())==20)
        assert all(lab.hashfiles('volume',vid,'slots')==h for vid,h in original.items())
        for i in range(21,25):lab.at('volume','AllocateVolume',{'volumeId':1000+i,'collection':'slots','replication':'000','version':3})
        fail24=lab.rpc(lab.binding('volume')['ip']+':18080','AllocateVolume',{'volumeId':1025,'collection':'slots','replication':'000','version':3},check=False)
        assert fail24.returncode!=0 and len(lab.volumes())==24
        lab.record('slot_limit_qualified',old_limit=20,new_limit=24,original_file_hashes_preserved=True,rejected_25th=fail24.stderr)
        # Make one slot available for an explicit, owned administrative negative control.
        lab.at('volume','VolumeDelete',{'volumeId':1024})
        before=set(lab.volumes())
        response=q.b.http('GET',lab.urls['master']+'/vol/grow?count=1&collection=fence-negative-control&replication=000')
        after=set(lab.volumes());created=sorted(after-before)
        lab.record('growth_flag_http_negative_control',status=response[0],created=created,body=response[1].decode())
        summary={'slots_passed':True,'image':a.image,'http_grow_bypasses_startup_flag':bool(created),'http_status':response[0]}
        if a.expect_http_blocked:
            assert response[0]==503 and not created
            lab.fenced=False;lab.stop('master');lab.launch('master')
            def registered():
                data=json.loads(q.b.http('GET',lab.urls['master']+'/dir/status')[1])['Topology']
                nodes=[n for dc in data.get('DataCenters',[]) for rack in dc.get('Racks',[]) for n in rack.get('DataNodes',[])]
                return len(nodes)==1 and nodes[0]['Max']==24 and nodes[0]['Volumes']==23
            lab.wait(registered)
            response=q.b.http('GET',lab.urls['master']+'/vol/grow?count=1&collection=fence-positive-control&replication=000')
            assert response[0]==200 and len(set(lab.volumes())-before)==1
            summary['growth_reenabled_verified']=True
            lab.record('growth_http_guard_and_restore_passed',**summary)
        (lab.directory/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    except BaseException:
        if lab.directory.exists():(lab.directory/'failure.txt').write_text(traceback.format_exc())
        raise
    finally:lab.cleanup()

if __name__=='__main__':main()
