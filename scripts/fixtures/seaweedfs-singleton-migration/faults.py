#!/usr/bin/env python3
"""Interrupt a real throttled copy; retain source and reopen a partial migration."""
import argparse,hashlib,json,time,traceback
from pathlib import Path
import run as q

def main():
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--image',default=q.IMAGE);a=p.parse_args();assert not a.output.exists()
 lab=q.Lab(a.output.resolve());lab.roles=['master','volume','volume-b','filer','s3'];lab.ha=False
 assert a.image.startswith('sha256:') and len(a.image)==71
 q.m.IMAGES['durable']=a.image
 try:
  lab.start()
  objects={'/harbor/abort-proof':hashlib.shake_256(b'abort-copy').digest(256*1024*1024),'/qualification/untouched':b'untouched-singleton'}
  for key,body in objects.items():assert lab.request('PUT',key,body,timeout=90)[0]==200
  metadata=json.loads(q.b.ORIGINAL_DOCKER('exec',lab.name+'-filer','wget','-qO-','http://127.0.0.1:8888/buckets/harbor/abort-proof?metadata=true'))
  chunks=metadata['chunks'];assert chunks and len({c['file_id'].split(',')[0] for c in chunks})==1
  fid=chunks[0]['file_id'];vid=int(fid.split(',')[0]);legacy=lab.volumes();src=legacy[vid][0][0]
  failed_target=next(role for role in ['volume','volume-b'] if role!=src)
  lab.stop('s3');lab.stop('filer');lab.fenced=True;lab.default='001';lab.stop('master');lab.launch('master')
  lab.wait(lambda:json.loads(q.b.http('GET',lab.urls['master']+'/cluster/status')[1]).get('IsLeader'))
  refreshed=lab.volumes()
  lab.record('final_fault_fixture_inventory',initial=sorted(legacy),fenced=sorted(refreshed),added_before_fence=sorted(set(refreshed)-set(legacy)))
  legacy=refreshed
  for v,copies in legacy.items():
   for role,_ in copies:lab.at(role,'VolumeMarkReadonly',{'volumeId':v,'persist':True})
  for role in ['volume','volume-b']:lab.stop(role);lab.launch(role)
  lab.wait(lambda:set(lab.volumes())==set(legacy))
  before=lab.hashfiles(src,vid,'harbor')
  lab.at(src,'VolumeConfigure',{'volumeId':vid,'replication':'001'})
  configured=lab.hashfiles(src,vid,'harbor')
  bound=lab.binding(src)
  result=lab.rpc(lab.binding(failed_target)['ip']+':18080','VolumeCopy',{'volumeId':vid,'sourceDataNode':bound['ip']+':8080','ioBytePerSecond':16777216},timeout=0.5,check=False)
  assert result.returncode!=0
  time.sleep(2)
  assert lab.hashfiles(src,vid,'harbor')==configured
  leftovers=q.b.ORIGINAL_DOCKER('exec',lab.name+'-'+failed_target,'sh','-c',f'ls -l /data/harbor_{vid}.* 2>/dev/null || true')
  lab.record('interrupted_copy_source_preserved',vid=vid,error=result.stderr,target_files=leftovers,source_hashes=configured)
  # Never retry the ambiguous destination. Preserve it and use a separately empty server.
  lab.roles.append('volume-c');(lab.directory/'volume-c').mkdir();lab.launch('volume-c')
  lab.wait(lambda:'volume-c' in lab.active and lab.volumes().get(vid) is not None)
  lab.at('volume-c','VolumeCopy',{'volumeId':vid,'sourceDataNode':lab.binding(src)['ip']+':8080'},timeout=90)
  assert lab.hashfiles('volume-c',vid,'harbor')==configured
  # Abort further migration, restore both verified copies plus untouched sources.
  for v,copies in lab.volumes().items():
   for role,_ in copies:lab.at(role,'VolumeMarkWritable',{'volumeId':v})
  lab.fenced=False;lab.stop('master');lab.launch('master')
  lab.wait(lambda:json.loads(q.b.http('GET',lab.urls['master']+'/cluster/status')[1]).get('IsLeader'))
  lab.launch('filer');lab.launch('s3')
  lab.wait(lambda:lab.request('GET','/')[0]==200)
  for key,body in objects.items():
   lab.wait(lambda:lab.request('GET',key)[1]==body)
  after_metadata=json.loads(q.b.ORIGINAL_DOCKER('exec',lab.name+'-filer','wget','-qO-','http://127.0.0.1:8888/buckets/harbor/abort-proof?metadata=true'))
  assert [c['file_id'] for c in after_metadata['chunks']]==[c['file_id'] for c in chunks]
  copies=lab.volumes();assert len(copies[vid])==2
  untouched=[(v,c) for v,c in copies.items() if v in legacy and v!=vid]
  assert untouched and all(len(c)==1 and sum(c[0][1]['ReplicaPlacement'].values())==0 for _,c in untouched)
  summary={'image':a.image,'interrupted_copy_source_preserved':True,'failed_destination_not_retried':True,'completed_pair_retained':True,'untouched_singletons_retained':len(untouched),'original_fid_preserved':fid,'original_bytes_verified':sum(map(len,objects.values()))}
  (lab.directory/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');lab.record('partial_progress_abort_recovery_passed',**summary)
 except BaseException:
  if lab.directory.exists():(lab.directory/'failure.txt').write_text(traceback.format_exc())
  raise
 finally:lab.cleanup()

if __name__=='__main__':main()
