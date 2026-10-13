# Flux substitutes this ConfigMap; doubled dollars preserve jq variables.
def epoch:
  if type != "string" then error("missing execution timestamp")
  else sub("[.][0-9]+Z$"; "Z") | fromdateiso8601 end;

def ready_gc($$now):
  . as $$input |
  if (.harbor.health.components|length)==0 or any(.harbor.health.components[]; .status!="healthy")
  then error("Harbor health is not ready") else . end |
  ($$now | gmtime) as $$clock |
  ($$now - $$clock[6]*86400 - $$clock[3]*3600 - $$clock[4]*60 - $$clock[5]) as $$sunday |
  if .harbor.gc != {schedule:{type:"Custom",cron:"0 30 5 * * 0"},
                   parameters:{dry_run:false,delete_untagged:false,workers:1}}
  then error("GC policy does not match approved Git intent") else . end |
  [.harbor.gc_executions[] | select((.creation_time|epoch) >= $$sunday + 19800)
     | select(.parameters.dry_run == false)] | max_by(.creation_time|epoch) as $$gc | $$input |
  if $$gc == null or $$gc.job_status != "Success" or
     ($$gc.job_kind|ascii_downcase) != "schedule" or
     $$gc.parameters.delete_untagged != false or $$gc.parameters.workers != 1
  then error("no successful scheduled real GC this week") else . end |
  if ($$gc.update_time|epoch) > $$now - 3600 or ($$gc.creation_time|epoch) > $$now
  then error("wait one hour after GC completion") else . end |
  if ($$input.harbor.projects|length) == 0 then error("empty project inventory") else . end |
  if (.filers|length)!=2 or ([.filers[].pvc_uid]|unique|length)!=2 or
     any(.filers[]; (.pvc_uid // "")=="" or (.longhorn_volume // "")=="")
  then error("persistent filer proof missing") else . end |
  if any(.harbor.projects[]; .policy.algorithm!="or" or .policy.trigger.kind!="Manual" or
      (.policy.rules|length)!=3 or .policy.rules[0].params.latestPushedK!=2 or
      .policy.rules[1].template!="always" or .policy.rules[1].tag_selectors[0].pattern!="{in-use-*,rollback}" or
      .policy.rules[2].template!="always" or .policy.rules[2].tag_selectors[0].pattern!="" or
      (.policy.rules[2].tag_selectors[0].extras|fromjson|.untagged)!=true or any(.policy.rules[];.disabled==true))
  then error("retention policy does not preserve protected/untagged images") else . end |
  .retention_evidence as $$e |
  if $$e.schema!=1 or $$e.state!="Success" or $$e.dry_run!=false or
     ($$e.completed_at|type)!="number" or $$e.completed_at < $$sunday+5400 or
     $$e.completed_at > ($$gc.creation_time|epoch) or
     ($$e.inventory_sha256|type)!="string" or
     ($$e.inventory_sha256|test("^[0-9a-f]{64}$")|not) or
     $$e.inventory_sha256 != .images.inventory_sha256 or $$e.filers != .filers
  then error("fresh successful protection/retention proof missing or changed") else . end |
  if ($$e.executions|length)!=($$input.harbor.projects|length) or
     any($$e.executions[]; .status!="Success" or .dry_run!=false)
  then error("incomplete real retention proof") else . end |
  if any($$input.harbor.projects[];
      [.executions[] as $$history|select(any($$e.executions[];.id==$$history.id and .policy_id==$$history.policy_id))] | length==0)
  then error("retention proof is not in Harbor history") else . end |
  if any($$input.harbor.projects[];
      ([.executions[] | select((.start_time|epoch) >= $$sunday + 5400)
        | select((.start_time|epoch) < ($$gc.creation_time|epoch))] | max_by(.start_time|epoch)) as $$r |
      $$r == null or $$r.status != "Success" or $$r.dry_run != false or
      ($$r.end_time|epoch) > ($$gc.creation_time|epoch))
  then error("preceding real project retention is missing or failed") else $$gc end;

def eligible_volumes:
  . as $$input |
  if (.seaweed|length) != 3 or ([.seaweed[].pod]|unique|length) != 3
  then error("incomplete SeaweedFS inventory") else . end |
  if any(.longhorn_volumes.items[]; .status.robustness != "healthy") or
     (.longhorn_volumes.items|length) == 0
  then error("Longhorn is not healthy") else . end |
  if any(.nodes.items[]; all(.status.conditions[]; .type != "Ready" or .status != "True")) or
     (.nodes.items|length) != 3
  then error("node health is not ready") else . end |
  if any(.seaweed[]; (.status.Version|test("(^| )4\\.40( |$)")|not) or
      ([.status.DiskStatuses[]|select(.dir=="/data0")]|length) != 1)
  then error("unexpected Seaweed version or filesystem layout") else . end |
  [.seaweed[] as $$server | $$server.status.Volumes[] | select(.Collection=="harbor") |
    . + {pod:$$server.pod, longhorn_volume:$$server.longhorn_volume,
         free_bytes:($$server.status.DiskStatuses[]|select(.dir=="/data0")|.free)}] as $$volumes |
  if ($$volumes|length) == 0 or ([$$volumes[].Id]|unique|length) != ($$volumes|length)
  then error("missing or ambiguous Harbor volume IDs") else . end |
  if any($$input.seaweed[]; .longhorn_volume as $$name |
       ([$$input.longhorn_volumes.items[]|select(.metadata.name==$$name and
            .status.state=="attached" and .status.robustness=="healthy")]|length) != 1)
  then error("SeaweedFS PVC does not map to one healthy attached Longhorn volume") else . end |
  [$$volumes[] | select(.DeletedByteCount >= 268435456 and .Size > 0 and
      .DeletedByteCount/.Size >= 0.10 and .ReadOnly == false)] as $$candidates |
  if ($$candidates|length)>0 and ([$$volumes[]|select(.ReadOnly==false)]|length)<2
  then error("no alternate writable Harbor volume") else . end |
  if any($$candidates[]; (.free_bytes|type)!="number" or .free_bytes <= .Size*2)
  then error("insufficient filesystem space for compaction") else $$candidates end;

. as $$input | ready_gc($$now) as $$gc | $$input | eligible_volumes as $$candidates |
{gc_id:$$gc.id,gc_completed_at:$$gc.update_time,
 candidates:[$$candidates[]|{pod,volume_id:.Id,size_bytes:.Size,deleted_bytes:.DeletedByteCount,longhorn_volume}]}
