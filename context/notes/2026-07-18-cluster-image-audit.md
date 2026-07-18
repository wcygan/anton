# 2026-07-18 cluster workload image audit

## Result

The current workload inventory contained 100 unique Pod spec image references. Trivy 0.72.0 completed coverage for all 100: the aggregate in-cluster Kubernetes scan covered 98, and two exact node-local containerd scans covered the ClickStack HyperDX and OTel collector images that could not be fetched remotely. The private bakery image and all three Harbor references were included in the aggregate scan.

Raw JSON, stderr, status files, and the mechanically generated inventory remain private under `.private/security-audits/20260718T011714Z/`; they are intentionally not committed. The aggregate scan used a 30-minute timeout and isolated credentials. Targeted scans used only the read-only containerd socket on the node already running the exact image. Manifest-list versus child-digest presentation does not create a coverage gap: the deployed spec reference was the scan input in every case.

## Normalized findings

Findings are normalized across 99 unique artifacts by Trivy artifact/configuration ID so replica copies do not multiply the distinct-ID counts. The scan reported 23 distinct Critical IDs (189 occurrences) and 291 distinct High IDs (3,934 occurrences). Of those, 17 Critical IDs (171 occurrences) and 260 High IDs (3,742 occurrences) have an available fix. This is coverage evidence, not blanket CVE clearance.

| Image concentration | Critical occurrences | High occurrences |
| --- | ---: | ---: |
| install-cni | 21 | 291 |
| MongoDB agent | 10 | 291 |
| MongoDB Community server | 8 | 251 |
| CNPG PostgreSQL 17.2 | 26 | 184 |
| alpine/k8s 1.36.2 | 4 | 202 |
| Multus | 9 | 161 |
| ClickStack OTel | 13 | 155 |

The two purpose-built host-agent images, `storage-vxlan` and `nvme-power-collector`, each reported zero Critical and zero High findings. The targeted HyperDX image reported 2 Critical and 73 High occurrences; the targeted ClickStack OTel image reported 13 Critical and 155 High occurrences. Prioritize fixable concentrations in ClickStack and other repeated base images, then reassess items with no upstream fix.

## Method and limitations

The aggregate in-cluster scan used a minimal read-only ServiceAccount and a read-only bakery pull-secret mount; it was not an empty-credential scan. Two remote rate-limit errors (HyperDX and ClickStack OTel) were recovered with exact node-local containerd scans of the deployed references. The committed host script now defaults Trivy scans to 30 minutes and an isolated empty Docker config unless an operator explicitly supplies `TRIVY_DOCKER_CONFIG`; it records stderr and a nonzero status before returning failure. This prevents implicit host credential-helper use while preserving an auditable override path.

The 2026-07-09 audit is the comparison baseline: it covered 100 of 102 refs and reported 29 Critical IDs/397 High IDs with 286/4,919 occurrences. This point-in-time run covers 100 of 100 refs and reports 23/291 IDs with 189/3,934 occurrences. The comparison is observed evidence, not proof of a single causal change.

The temporary scanner resources used restrictive security contexts, no service-account token for node-local scans, and were deleted after reports were copied. Vulnerability data is point-in-time database evidence; it does not assess runtime behavior, configuration weaknesses, or future disclosures.
