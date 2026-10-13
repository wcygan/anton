# Flux preserves jq variables with doubled dollars.
def parse_ref($$aliases):
  sub("^(docker-pullable|containerd)://"; "") as $$image |
  ($$image|split("/")) as $$parts |
  if ($$aliases|index($$parts[0]|sub(":(80|443)$";""))) == null then empty
  else ($$parts[1:]|join("/")) as $$path |
    if ($$path|test("^[a-z0-9]+([._/-][a-z0-9]+)*(?::[^@/]+)?(?:@sha256:[0-9a-f]{64})?$$"))|not
    then error("invalid Harbor image reference")
    else ($$path|capture("^(?<repository>[^:@]+)(?::(?<tag>[^@]+))?(?:@(?<digest>sha256:[0-9a-f]{64}))?$$")) |
      {repository,reference:(.digest // .tag // "latest")}
    end
  end;
if (.workloads.items|type)!="array" or (.ingresses.items|type)!="array"
then error("incomplete workload or registry-alias inventory") else . end |
if any(.workloads.items[]; .kind=="ControllerRevision" and (.data|type)!="object") then error("unreadable controller revision") else . end |
([ $$host, "harbor", "harbor.registries", "harbor.registries.svc", "harbor.registries.svc.cluster.local", "harbor-registry:5000", "harbor-registry.registries:5000", "harbor-registry.registries.svc:5000", "harbor-registry.registries.svc.cluster.local:5000"] +
 [ .ingresses.items[] | select(.spec.defaultBackend.service.name=="harbor" or any(.spec.rules[]?.http.paths[]?; .backend.service.name=="harbor")) | (.status.loadBalancer.ingress[]?.hostname // empty), (.spec.rules[]?.host // empty), (.spec.tls[]?.hosts[]? // empty)] | unique) as $$aliases |
# A runtime digest must have a repository identity; never mistake a config hash
# for a registry manifest. Pending containers may legitimately have no imageID.
if any(.workloads.items[]|select(.kind=="Pod")|.status|(.containerStatuses[]?,.initContainerStatuses[]?,.ephemeralContainerStatuses[]?);
   ([.image|parse_ref($$aliases)]|length)>0 and (.imageID // "")!="" and
   ([.imageID|parse_ref($$aliases)]|length)==0)
then error("ambiguous Harbor runtime image identity") else . end |
[.workloads.items[] | .. | objects |
  (.image? // empty),(.imageID? // empty) | select(type=="string") | parse_ref($$aliases)] |
unique_by([.repository,.reference]) | sort_by(.repository,.reference)
