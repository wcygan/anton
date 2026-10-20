#!/usr/bin/env python3
"""Real Registry and cold Loki operations during each serving-owner hold."""
import argparse,json,traceback,xml.etree.ElementTree as ET
from pathlib import Path
import run as q

def main():
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--image',default=q.IMAGE);a=p.parse_args();assert not a.output.exists()
 lab=q.Lab(a.output.resolve());lab.default='001'
 assert a.image.startswith('sha256:') and len(a.image)==71
 q.m.IMAGES['durable']=a.image
 try:
  lab.start();lab.start_registry();registry=q.b.registry_work(lab)
  lab.start_loki();logs=q.b.loki_work(lab);lab.stop('loki');lab.placement()
  native={}
  for bucket in ['harbor','loki']:
   status,body,_=lab.request('GET','/'+bucket+'?list-type=2');assert status==200
   keys=[e.text for e in ET.fromstring(body).iter() if e.tag.endswith('}Key')]
   vids=set()
   for key in keys:
    metadata=json.loads(q.b.ORIGINAL_DOCKER('exec',lab.name+'-filer','wget','-qO-','http://127.0.0.1:8888/buckets/'+bucket+'/'+key+'?metadata=true'))
    vids.update(int(c['file_id'].split(',')[0]) for c in metadata.get('chunks',[]))
   assert vids
   native[bucket]=sorted(vids)
  (lab.directory/'original-application-volumes.json').write_text(json.dumps(native,indent=2)+'\n')
  holds=[]
  for owner in ['volume','volume-b','volume-c']:
   placement={vid:[role for role,_ in copies] for vid,copies in lab.volumes().items()}
   lab.stop(owner)
   q.registry_read(lab,registry)
   lab.loki_generation+=1
   original=q.b.cold_loki(lab,logs)
   fresh=q.b.loki_work(lab)
   lab.stop('loki')
   lab.launch(owner);lab.wait(lambda:all(len(c)==2 for c in lab.volumes().values()))
   affected={bucket:[vid for vid in vids if owner in placement[vid]] for bucket,vids in native.items()}
   result={'absent_owner':owner,'placement_before':placement,'affected_original_volumes':affected,'original_registry_bytes':registry['verified_layer_bytes'],'original_cold_logs':original['records'],'fresh_logs':fresh['verified_records'],'downloaded_chunks':original['chunks_downloaded']}
   holds.append(result);lab.record('application_owner_hold_passed',**result)
  assert all(sum(bool(h['affected_original_volumes'][bucket]) for h in holds)>=2 for bucket in ['harbor','loki'])
  (lab.directory/'summary.json').write_text(json.dumps({'holds':holds,'production':False,'image':a.image},indent=2)+'\n')
 except BaseException:
  if lab.directory.exists():(lab.directory/'failure.txt').write_text(traceback.format_exc())
  raise
 finally:lab.cleanup()

if __name__=='__main__':main()
