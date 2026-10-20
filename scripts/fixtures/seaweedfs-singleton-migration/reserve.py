#!/usr/bin/env python3
"""Exercise 56-copy placement and four fresh allocations with one owner absent."""
import argparse,ipaddress,json,traceback
from pathlib import Path
import run as q

def main():
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();assert not a.output.exists()
 lab=q.Lab(a.output.resolve());lab.roles=['master','volume','volume-b','volume-c'];lab.ha=False
 lab.versions=dict.fromkeys(lab.roles,'durable');lab.fenced=True;lab.default='001'
 try:
  lab.directory.mkdir(parents=True);lab.owns_directory=True
  for role in lab.roles:(lab.directory/role).mkdir()
  q.b.ORIGINAL_DOCKER=lab.route;q.m.docker=lab.wrapped_docker
  lab.wrapped_docker('network','create','--label','anton.migration-rehearsal=true',lab.name)
  net=json.loads(q.RAW('network','inspect',lab.name))[0];assert net['Internal']
  lab.subnet=ipaddress.ip_network(net['IPAM']['Config'][0]['Subnet'])
  for role in lab.roles:lab.launch(role)
  lab.wait(lambda:lab.volumes()=={})
  pairs=[('volume','volume-b')]*10+[('volume','volume-c')]*9+[('volume-b','volume-c')]*9
  for offset,pair in enumerate(pairs):
   for role in pair:lab.at(role,'AllocateVolume',{'volumeId':2001+offset,'collection':'reserve','replication':'001','version':3})
  def counts():return {role:sum(role==r for copies in lab.volumes().values() for r,_ in copies) for role in ['volume','volume-b','volume-c']}
  assert list(counts().values())==[19,19,18]
  original=set(lab.volumes());lab.stop('volume');lab.fenced=False
  lab.stop('master');lab.launch('master')
  lab.wait(lambda:json.loads(q.b.http('GET',lab.urls['master']+'/cluster/status')[1]).get('IsLeader',False))
  lab.wait(lambda:len(lab.volumes())==28)
  def registered():
   topology=json.loads(q.b.http('GET',lab.urls['master']+'/dir/status')[1])['Topology']
   nodes=[n for dc in topology.get('DataCenters',[]) for rack in dc.get('Racks',[]) for n in rack.get('DataNodes',[])]
   return len(nodes)==2 and all(n['Max']==24 and n['Volumes']>=18 and n['Max']-n['Volumes']>=4 for n in nodes)
  lab.wait(registered)
  for collection in ['harbor','loki','s3-read-probe','default-control']:
   leader_ip=lab.binding('master')['ip']
   lab.rpc(leader_ip+':19333','master_pb.Seaweed/VolumeGrow',{'collection':collection,'replication':'001','writableVolumeCount':1})
  lab.wait(lambda:len(set(lab.volumes())-original)==4)
  fresh={vid:c for vid,c in lab.volumes().items() if vid not in original}
  assert len(fresh)==4 and all({r for r,_ in c}=={'volume-b','volume-c'} for c in fresh.values())
  result={'baseline_slots':[19,19,18],'surviving_slots':counts(),'fresh_collections':[c[0][1]['Collection'] for c in fresh.values()],'fresh_two_copy_volumes':4,'absent_owner':'volume'}
  (lab.directory/'summary.json').write_text(json.dumps(result,indent=2)+'\n');lab.record('survivor_capacity_passed',**result)
 except BaseException:
  if lab.directory.exists():(lab.directory/'failure.txt').write_text(traceback.format_exc())
  raise
 finally:lab.cleanup()

if __name__=='__main__':main()
