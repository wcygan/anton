#!/usr/bin/env python3
"""Verify retained local results and absence of their Docker resources."""
import argparse,datetime,json,re,subprocess
from pathlib import Path

def main():
 p=argparse.ArgumentParser();p.add_argument('--evidence',type=Path,required=True);a=p.parse_args();root=a.evidence.resolve()
 def read(path):return json.loads((root/path).read_text())
 main=read('run-07/summary.json');assert main['passed']
 assert main['loki_before']['verified_records']==8000
 assert main['cold_loki_before']['records']==8000 and main['cold_loki_before']['chunks_downloaded']>0
 assert main['outage_records']==main['cold_outage_records']==1000
 assert main['registry_before']['verified_layer_bytes']==71303168
 events=read('run-07/events.json')
 for event in ['growth_fence_passed','growth_reenabled_without_singletons']:
  matches=[e for e in events if e['event']==event];assert len(matches)==1 and matches[0]['seconds']>=660
 copied=[e for e in events if e['event']=='copy_verified'];assert len(copied)==4
 assert all(set(e['hashes'])=={'dat','idx','vif'} and all(len(h)==64 for h in e['hashes'].values()) for e in copied)
 assert len([e for e in events if e['event']=='owner_absent_exact_reads_and_writes'])==3
 joins=read('run-07/owner-read-joins-verified.json');assert len(joins)==6 and all(j['affected_checked_keys'] for j in joins)
 base=read('slots-02/summary.json');assert base['slots_passed'] and base['http_grow_bypasses_startup_flag']
 fixed=read('slots-fixed-03/summary.json');assert fixed['slots_passed'] and fixed['http_status']==503 and not fixed['http_grow_bypasses_startup_flag'] and fixed['growth_reenabled_verified']
 reserve=read('reserve-03/summary.json');assert reserve['baseline_slots']==[19,19,18] and reserve['fresh_two_copy_volumes']==4
 availability=read('availability-fixed-01/summary.json');assert len(availability['holds'])==3
 for h in availability['holds']:
  assert h['original_registry_bytes']==71303168 and h['original_cold_logs']==h['fresh_logs']==8000 and h['downloaded_chunks']>0
 assert all(sum(bool(h['affected_original_volumes'][bucket]) for h in availability['holds'])>=2 for bucket in ['harbor','loki'])
 fault=read('faults-fixed-01/summary.json')
 identity=read('growth-build-identity.json')
 assert fixed['image']==availability['image']==fault['image']==identity['candidate_image']
 runtime=read('availability-fixed-01/actual-runtime-images-verified.json')
 assert len(runtime['components'])==10 and all(c['imageId']==fixed['image'] for c in runtime['components'].values())
 assert all(fault[k] is True for k in ['interrupted_copy_source_preserved','failed_destination_not_retried','completed_pair_retained'])
 assert fault['original_bytes_verified']==268435475 and fault['untouched_singletons_retained']==2
 fault_events=read('faults-fixed-01/events.json');interrupt=next(e for e in fault_events if e['event']=='interrupted_copy_source_preserved')
 assert 'DeadlineExceeded' in interrupt['error'] and '.dat.copying' in interrupt['target_files'] and '.note' in interrupt['target_files']
 assert all(read('destination-guard-proof.json').values())
 assert read('existing-output-guard.json')['existing_evidence_unchanged']
 filesystem=(root/'filesystem-capacity.log').read_text()
 assert 'on-line resizing required' in filesystem and '168503083008' in filesystem
 assert filesystem.count('2b0b8153296d1e3fc7feb39d8ba58e14ca370ea7b78a812efe224dc579e8939c')==2
 assert 24*5000*1024*1024<168503083008*0.8
 assert 'FAIL' in (root/'growth-before.log').read_text()
 assert 'ok  ' in (root/'growth-after.log').read_text()
 assert 'ok  ' in (root/'operator-expansion.log').read_text()
 cases=['run-07','slots-02','slots-fixed-03','reserve-03','availability-01','availability-fixed-01','faults-08','faults-fixed-01']
 for case in cases:
  assert not (root/case/'failure.txt').exists(),case
  assert read(case+'/events.json')[-1]['event']=='cleaned',case
 prefixes={e['network'] for path in root.glob('*/events.json') for e in json.loads(path.read_text()) if e.get('event')=='identity' and 'network' in e}
 for prefix in prefixes:
  assert re.fullmatch(r'anton-sw-qual-[a-f0-9]{10}',prefix)
  for args in [('ps','-aq','--filter','name='+prefix),('network','ls','-q','--filter','name='+prefix),('volume','ls','-q','--filter','name='+prefix)]:
   assert not subprocess.check_output(['docker',*args],text=True).strip(),(prefix,args)
 result={'verified_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'isolated_functional_qualification':'passed','production_changed':False,'published':False,'production_CSI_expansion':'not_qualified','production_node_drain':'not_performed','long_observation_image':'deployed durable1','candidate_image':fixed['image'],'retained_evidence_cases':cases,'all_recorded_run_prefixes_absent':sorted(prefixes)}
 (root/'acceptance.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))

if __name__=='__main__':main()
