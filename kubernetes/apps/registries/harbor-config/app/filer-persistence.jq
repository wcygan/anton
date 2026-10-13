. as $$input |
if (.pods.items|length)!=2 or (.claims.items|length)!=2
then error("incomplete filer persistence inventory") else . end |
[range(0;2) as $$i |
 ("seaweedfs-filer-"+($$i|tostring)) as $$name |
 ("seaweedfs-filer-"+$$name) as $$claim |
 [$$input.pods.items[]|select(.metadata.name==$$name)] as $$pods |
 [$$input.claims.items[]|select(.metadata.name==$$claim)] as $$claims |
 if ($$pods|length)!=1 or ($$claims|length)!=1 then error("ambiguous filer identity") else . end |
 $$pods[0] as $$pod | $$claims[0] as $$pvc |
 [$$pod.spec.containers[]|select(.name=="filer")|.volumeMounts[]?|select(.mountPath=="/data" and .readOnly!=true)] as $$mounts |
 if ($$mounts|length)!=1 or
    ([$$pod.spec.volumes[]?|select(.name==$$mounts[0].name and .persistentVolumeClaim.claimName==$$claim)]|length)!=1 or
    (any($$pod.status.conditions[]?; .type=="Ready" and .status=="True")|not) or
    $$pvc.status.phase!="Bound" or ($$pvc.metadata.uid // "")=="" or ($$pvc.spec.volumeName // "")==""
 then error("filer metadata is not mounted on a ready persistent volume") else . end |
 [$$input.volumes.items[]|select(.metadata.name==$$pvc.spec.volumeName)] as $$volumes |
 if ($$volumes|length)!=1 or $$volumes[0].status.robustness!="healthy" or $$volumes[0].status.state!="attached"
 then error("filer Longhorn volume is not healthy and attached") else . end |
 {pod:$$name,pvc:$$claim,pvc_uid:$$pvc.metadata.uid,longhorn_volume:$$pvc.spec.volumeName}
] | sort_by(.pod)
