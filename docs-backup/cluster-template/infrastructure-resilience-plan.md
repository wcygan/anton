# Infrastructure Resilience Plan

This document outlines strategies and implementations to prevent critical infrastructure failures in the Kubernetes cluster, particularly focusing on CNI and DNS resilience.

## Prevention Strategies

### 1. Automated Health Monitoring

#### Continuous Health Checks Script

Create `/scripts/cluster-health-monitor-critical.ts`:

```typescript
#!/usr/bin/env -S deno run --allow-all

import { $ } from "@david/dax";

interface HealthCheck {
  name: string;
  check: () => Promise<boolean>;
  critical: boolean;
}

const healthChecks: HealthCheck[] = [
  {
    name: "Cilium CNI",
    critical: true,
    check: async () => {
      try {
        const result = await $`kubectl get ds -n kube-system cilium -o json`.json();
        return result.status.numberReady === result.status.desiredNumberScheduled;
      } catch {
        return false;
      }
    }
  },
  {
    name: "CoreDNS",
    critical: true,
    check: async () => {
      try {
        const result = await $`kubectl get deploy -n kube-system coredns -o json`.json();
        return result.status.readyReplicas >= 2;
      } catch {
        return false;
      }
    }
  },
  {
    name: "DNS Service",
    critical: true,
    check: async () => {
      try {
        await $`kubectl get svc -n kube-system kube-dns`.quiet();
        return true;
      } catch {
        return false;
      }
    }
  },
  {
    name: "Pod DNS Resolution",
    critical: true,
    check: async () => {
      try {
        await $`kubectl run dns-test-${Date.now()} --image=busybox:1.36 --rm -i --restart=Never -- nslookup kubernetes.default.svc.cluster.local`.quiet();
        return true;
      } catch {
        return false;
      }
    }
  },
  {
    name: "Flux Controllers",
    critical: false,
    check: async () => {
      try {
        const result = await $`flux check`.text();
        return !result.includes("✗");
      } catch {
        return false;
      }
    }
  }
];

async function runHealthChecks() {
  console.log("🏥 Running critical infrastructure health checks...\n");
  
  let allHealthy = true;
  const criticalFailures: string[] = [];

  for (const check of healthChecks) {
    const healthy = await check.check();
    const status = healthy ? "✅" : "❌";
    
    console.log(`${status} ${check.name}`);
    
    if (!healthy) {
      allHealthy = false;
      if (check.critical) {
        criticalFailures.push(check.name);
      }
    }
  }

  if (criticalFailures.length > 0) {
    console.error("\n🚨 CRITICAL FAILURES DETECTED!");
    console.error("Failed components:", criticalFailures.join(", "));
    console.error("\nRun recovery: task bootstrap:apps");
    Deno.exit(2);
  }

  if (!allHealthy) {
    console.warn("\n⚠️  Some non-critical checks failed");
    Deno.exit(1);
  }

  console.log("\n✅ All infrastructure components healthy!");
}

await runHealthChecks();
```

#### Scheduled Monitoring

Add to `deno.json`:

```json
{
  "tasks": {
    "health:critical": "deno run --allow-all scripts/cluster-health-monitor-critical.ts",
    "health:watch": "watch -n 300 deno task health:critical"
  }
}
```

### 2. Bootstrap State Tracking

#### State File Management

Create `/scripts/bootstrap-state-manager.ts`:

```typescript
#!/usr/bin/env -S deno run --allow-all

import { $ } from "@david/dax";
import { exists } from "@std/fs";

const STATE_FILE = ".bootstrap-state.json";

interface BootstrapState {
  timestamp: string;
  version: string;
  components: {
    [key: string]: {
      installed: boolean;
      version: string;
      healthy: boolean;
    };
  };
}

async function saveBootstrapState() {
  const state: BootstrapState = {
    timestamp: new Date().toISOString(),
    version: "1.0.0",
    components: {}
  };

  // Check each component
  const components = [
    { name: "cilium", namespace: "kube-system", type: "daemonset" },
    { name: "coredns", namespace: "kube-system", type: "deployment" },
    { name: "cert-manager", namespace: "cert-manager", type: "deployment" },
    { name: "flux-operator", namespace: "flux-system", type: "deployment" },
  ];

  for (const comp of components) {
    try {
      const result = await $`kubectl get ${comp.type} -n ${comp.namespace} ${comp.name} -o json`.json();
      state.components[comp.name] = {
        installed: true,
        version: result.metadata.labels?.["app.kubernetes.io/version"] || "unknown",
        healthy: comp.type === "daemonset" 
          ? result.status.numberReady === result.status.desiredNumberScheduled
          : result.status.readyReplicas > 0
      };
    } catch {
      state.components[comp.name] = {
        installed: false,
        version: "not-installed",
        healthy: false
      };
    }
  }

  await Deno.writeTextFile(STATE_FILE, JSON.stringify(state, null, 2));
  console.log("✅ Bootstrap state saved to", STATE_FILE);
}

async function verifyBootstrapState() {
  if (!await exists(STATE_FILE)) {
    console.error("❌ No bootstrap state file found. Run bootstrap first.");
    Deno.exit(1);
  }

  const state: BootstrapState = JSON.parse(await Deno.readTextFile(STATE_FILE));
  console.log("📋 Last bootstrap:", state.timestamp);
  
  let allHealthy = true;
  for (const [name, info] of Object.entries(state.components)) {
    if (!info.installed || !info.healthy) {
      console.error(`❌ ${name}: Not healthy`);
      allHealthy = false;
    } else {
      console.log(`✅ ${name}: ${info.version}`);
    }
  }

  return allHealthy;
}

// Main
const command = Deno.args[0];
switch (command) {
  case "save":
    await saveBootstrapState();
    break;
  case "verify":
    const healthy = await verifyBootstrapState();
    Deno.exit(healthy ? 0 : 1);
    break;
  default:
    console.log("Usage: bootstrap-state-manager.ts [save|verify]");
}
```

### 3. Automated Recovery

#### Self-Healing Script

Create `/scripts/auto-recover-infrastructure.ts`:

```typescript
#!/usr/bin/env -S deno run --allow-all

import { $ } from "@david/dax";
import { delay } from "@std/async";

interface RecoveryAction {
  name: string;
  check: () => Promise<boolean>;
  recover: () => Promise<void>;
  maxRetries: number;
}

const recoveryActions: RecoveryAction[] = [
  {
    name: "Cilium CNI Recovery",
    check: async () => {
      try {
        const pods = await $`kubectl get pods -n kube-system -l app.kubernetes.io/name=cilium -o json`.json();
        return pods.items.length > 0;
      } catch {
        return false;
      }
    },
    recover: async () => {
      console.log("🔧 Attempting to recover Cilium...");
      await $`helmfile --file bootstrap/helmfile.yaml -l name=cilium sync`;
    },
    maxRetries: 3
  },
  {
    name: "CoreDNS Recovery",
    check: async () => {
      try {
        const deploy = await $`kubectl get deploy -n kube-system coredns -o json`.json();
        return deploy.status.readyReplicas >= 1;
      } catch {
        return false;
      }
    },
    recover: async () => {
      console.log("🔧 Attempting to recover CoreDNS...");
      await $`helmfile --file bootstrap/helmfile.yaml -l name=coredns sync`;
    },
    maxRetries: 3
  },
  {
    name: "Flux Recovery",
    check: async () => {
      try {
        const flux = await $`kubectl get pods -n flux-system -l app.kubernetes.io/part-of=flux -o json`.json();
        return flux.items.length >= 4; // Should have 4 controllers
      } catch {
        return false;
      }
    },
    recover: async () => {
      console.log("🔧 Attempting to recover Flux...");
      // Check if FluxInstance exists
      try {
        await $`kubectl get fluxinstance -n flux-system flux`;
      } catch {
        // Recreate FluxInstance
        await $`helm get manifest flux-instance -n flux-system | kubectl apply -f -`;
      }
    },
    maxRetries: 2
  }
];

async function autoRecover() {
  console.log("🚑 Starting infrastructure auto-recovery...\n");

  for (const action of recoveryActions) {
    let retries = 0;
    while (retries < action.maxRetries) {
      const healthy = await action.check();
      
      if (healthy) {
        console.log(`✅ ${action.name}: Healthy`);
        break;
      }

      console.log(`❌ ${action.name}: Unhealthy (attempt ${retries + 1}/${action.maxRetries})`);
      
      try {
        await action.recover();
        await delay(30000); // Wait 30s for recovery
      } catch (error) {
        console.error(`Recovery failed: ${error.message}`);
      }
      
      retries++;
    }
    
    if (retries >= action.maxRetries) {
      console.error(`🚨 ${action.name}: Recovery failed after ${action.maxRetries} attempts`);
      console.error("Manual intervention required!");
      Deno.exit(1);
    }
  }

  console.log("\n✅ All infrastructure components recovered successfully!");
}

// Add to deno.json
if (import.meta.main) {
  await autoRecover();
}
```

### 4. Pre-Flight Checks

#### Deployment Validator

Create `/scripts/pre-deployment-check.ts`:

```typescript
#!/usr/bin/env -S deno run --allow-all

import { $ } from "@david/dax";

async function preFlightCheck(): Promise<boolean> {
  console.log("🛫 Running pre-flight checks...\n");

  const checks = [
    {
      name: "Node Readiness",
      run: async () => {
        const nodes = await $`kubectl get nodes -o json`.json();
        return nodes.items.every((node: any) => 
          node.status.conditions.find((c: any) => c.type === "Ready")?.status === "True"
        );
      }
    },
    {
      name: "CNI Running",
      run: async () => {
        const ds = await $`kubectl get ds -n kube-system cilium -o json`.json();
        return ds.status.numberReady === ds.status.desiredNumberScheduled;
      }
    },
    {
      name: "DNS Functional",
      run: async () => {
        try {
          await $`kubectl run preflight-dns-${Date.now()} --image=busybox:1.36 --rm -i --restart=Never -- nslookup kubernetes.default.svc.cluster.local`.quiet();
          return true;
        } catch {
          return false;
        }
      }
    },
    {
      name: "Flux Healthy",
      run: async () => {
        try {
          const result = await $`flux check`.text();
          return !result.includes("✗");
        } catch {
          return false;
        }
      }
    }
  ];

  let allPassed = true;
  for (const check of checks) {
    try {
      const passed = await check.run();
      console.log(`${passed ? "✅" : "❌"} ${check.name}`);
      if (!passed) allPassed = false;
    } catch (error) {
      console.log(`❌ ${check.name}: ${error.message}`);
      allPassed = false;
    }
  }

  if (!allPassed) {
    console.error("\n❌ Pre-flight checks failed! Do not proceed with deployment.");
    console.log("Run: deno task health:critical");
  } else {
    console.log("\n✅ All pre-flight checks passed!");
  }

  return allPassed;
}

if (import.meta.main) {
  const passed = await preFlightCheck();
  Deno.exit(passed ? 0 : 1);
}
```

### 5. GitOps Improvements

#### Add Health Checks to Kustomizations

Update critical kustomizations with health checks:

```yaml
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: critical-infrastructure
  namespace: flux-system
spec:
  interval: 5m
  path: ./kubernetes/critical
  healthChecks:
    - apiVersion: apps/v1
      kind: DaemonSet
      name: cilium
      namespace: kube-system
    - apiVersion: apps/v1
      kind: Deployment
      name: coredns
      namespace: kube-system
```

### 6. Monitoring and Alerting

#### Prometheus Rules

Create `/kubernetes/apps/monitoring/kube-prometheus-stack/app/prometheus-rules/infrastructure-critical.yaml`:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: infrastructure-critical
  namespace: monitoring
spec:
  groups:
    - name: infrastructure.critical
      interval: 30s
      rules:
        - alert: CiliumDown
          expr: up{job="cilium"} == 0
          for: 2m
          labels:
            severity: critical
            component: cni
          annotations:
            summary: "Cilium CNI is down"
            description: "Cilium CNI has been down for more than 2 minutes. Cluster networking is broken."
            runbook_url: "docs/cluster-template/cluster-recovery-guide.md"

        - alert: CoreDNSDown
          expr: up{job="coredns"} == 0
          for: 2m
          labels:
            severity: critical
            component: dns
          annotations:
            summary: "CoreDNS is down"
            description: "CoreDNS has been down for more than 2 minutes. Service discovery is broken."
            
        - alert: NoDNSResolution
          expr: probe_success{job="dns-probe"} == 0
          for: 3m
          labels:
            severity: critical
            component: dns
          annotations:
            summary: "DNS resolution failing"
            description: "DNS probes have been failing for 3 minutes."
```

### 7. Regular Maintenance Tasks

#### Weekly Infrastructure Validation

Add to `deno.json`:

```json
{
  "tasks": {
    "maintenance:weekly": "deno run --allow-all scripts/weekly-maintenance.ts"
  }
}
```

Create `/scripts/weekly-maintenance.ts`:

```typescript
#!/usr/bin/env -S deno run --allow-all

import { $ } from "@david/dax";

async function weeklyMaintenance() {
  console.log("🔧 Running weekly infrastructure maintenance...\n");

  // 1. Verify bootstrap components
  console.log("1️⃣ Verifying bootstrap components...");
  await $`./scripts/bootstrap-state-manager.ts verify`;

  // 2. Check for updates
  console.log("\n2️⃣ Checking for component updates...");
  await $`helmfile --file bootstrap/helmfile.yaml diff`;

  // 3. Validate manifests
  console.log("\n3️⃣ Validating Kubernetes manifests...");
  await $`deno task validate`;

  // 4. Run full health check
  console.log("\n4️⃣ Running comprehensive health check...");
  await $`./scripts/k8s-health-check.ts --verbose`;

  // 5. Check certificate expiration
  console.log("\n5️⃣ Checking certificate expiration...");
  await $`kubectl get cert -A -o json | jq '.items[] | {name: .metadata.name, namespace: .metadata.namespace, notAfter: .status.notAfter}'`;

  console.log("\n✅ Weekly maintenance complete!");
}

await weeklyMaintenance();
```

### 8. Documentation and Training

#### Runbook Template

Create `/docs/runbooks/infrastructure-failure-response.md`:

```markdown
# Infrastructure Failure Response Runbook

## Alert: [Component] Down

### Symptoms
- [ ] Pods failing to start
- [ ] DNS resolution errors
- [ ] Network timeouts

### Immediate Actions
1. Run health check: `deno task health:critical`
2. Check node status: `kubectl get nodes`
3. Review recent changes: `git log --oneline -10`

### Recovery Steps
1. **Automatic Recovery**
   ```bash
   deno run --allow-all scripts/auto-recover-infrastructure.ts
   ```

2. **Manual Recovery** (if automatic fails)
   ```bash
   task bootstrap:apps
   ```

3. **Verification**
   ```bash
   deno task health:critical
   flux reconcile kustomization cluster-apps
   ```

### Escalation
If recovery fails after 2 attempts:
1. Check Talos logs: `talosctl -n <node-ip> logs`
2. Review cluster events: `kubectl get events -A --sort-by='.lastTimestamp'`
3. Consider node reboot as last resort
```

## Implementation Plan

1. **Week 1**: Deploy monitoring scripts and automation
2. **Week 2**: Set up Prometheus alerts and dashboards
3. **Week 3**: Test recovery procedures in staging
4. **Week 4**: Document lessons learned and refine procedures

## Summary

By implementing these preventive measures:
- **Continuous monitoring** catches issues before they cascade
- **Automated recovery** reduces MTTR (Mean Time To Recovery)
- **State tracking** provides clear recovery points
- **Pre-flight checks** prevent bad deployments
- **Regular maintenance** keeps infrastructure healthy

The key is defense in depth - multiple layers of protection to ensure critical infrastructure remains operational.