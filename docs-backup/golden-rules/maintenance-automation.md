# Maintenance Automation Golden Rules

## The Golden Rule

**Never allow unattended updates without rollback capability.** Automated updates are powerful but can break production. Always ensure you can quickly revert any automated change.

## Critical Rules

### 1. Always Pin Versions with Automated Updates

**WRONG:**
```yaml
# Renovate config allowing any version
{
  "packageRules": [{
    "matchPackagePatterns": ["*"],
    "automerge": true,
    "matchUpdateTypes": ["major", "minor", "patch"]
    # No version constraints!
  }]
}
```

**RIGHT:**
```yaml
# Renovate with safe constraints
{
  "packageRules": [{
    "matchPackagePatterns": ["*"],
    "matchUpdateTypes": ["patch"],
    "automerge": true
  }, {
    "matchPackagePatterns": ["*"],
    "matchUpdateTypes": ["minor"],
    "automerge": false,
    "schedule": ["after 9am on monday"]
  }, {
    "matchPackagePatterns": ["*"],
    "matchUpdateTypes": ["major"],
    "enabled": false  # Require manual review
  }],
  "prConcurrentLimit": 3,
  "prHourlyLimit": 2
}
```

**Why:** Major updates often have breaking changes. Automated merging should be limited to safe updates.

### 2. Never Auto-Merge Without Successful Tests

**WRONG:**
```yaml
# GitHub workflow with blind auto-merge
name: Auto-merge
on:
  pull_request:
jobs:
  auto-merge:
    runs-on: ubuntu-latest
    steps:
      - uses: pascalgn/merge-action@v1
        # No test requirements!
```

**RIGHT:**
```yaml
name: Auto-merge
on:
  pull_request:
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Validate manifests
        run: ./scripts/validate-manifests.ts
      - name: Test build
        run: flux build kustomization flux-system --path ./kubernetes/flux
  
  auto-merge:
    needs: [test]  # Require tests to pass
    if: success() && github.actor == 'renovate[bot]'
    runs-on: ubuntu-latest
    steps:
      - uses: pascalgn/merge-action@v1
        with:
          method: squash
          strict: true  # Require branch to be up-to-date
```

**Why:** Broken updates merged automatically can cascade through the system.

### 3. Always Stage Updates Through Environments

**WRONG:**
```yaml
# Direct production updates
kind: ImageUpdateAutomation
metadata:
  name: flux-system
spec:
  sourceRef:
    kind: GitRepository
    name: flux-system
  git:
    commit:
      author:
        name: fluxcdbot
    push:
      branch: main  # Direct to production!
```

**RIGHT:**
```yaml
# Stage through environments
kind: ImageUpdateAutomation
metadata:
  name: flux-system
spec:
  sourceRef:
    kind: GitRepository
    name: flux-system
  git:
    commit:
      author:
        name: fluxcdbot
    push:
      branch: staging  # Push to staging first
  postBuild:
    substituteFrom:
      - kind: ConfigMap
        name: environment-config
---
# Separate automation for production
kind: Kustomization
metadata:
  name: promote-to-prod
spec:
  interval: 24h  # Daily promotion
  sourceRef:
    kind: GitRepository
    name: flux-system
  path: ./kubernetes/apps
  prune: false  # Never auto-prune in production
  wait: true
  timeout: 30m
  healthChecks:
    - apiVersion: apps/v1
      kind: Deployment
      namespace: default
      selector:
        matchLabels:
          env: staging
```

**Why:** Staging catches issues before they hit production.

### 4. Never Schedule Maintenance During Peak Hours

**WRONG:**
```yaml
# System upgrade during business hours
apiVersion: batch/v1
kind: CronJob
metadata:
  name: system-upgrade
spec:
  schedule: "0 14 * * *"  # 2 PM daily - peak hours!
```

**RIGHT:**
```yaml
# Maintenance windows with timezone awareness
apiVersion: batch/v1
kind: CronJob
metadata:
  name: system-upgrade
spec:
  schedule: "0 3 * * 6"  # 3 AM Saturday UTC
  successfulJobsHistoryLimit: 3
  failedJobsHistoryLimit: 3
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: upgrade
            env:
            - name: TZ
              value: "UTC"
            - name: MAINTENANCE_WINDOW_START
              value: "03:00"
            - name: MAINTENANCE_WINDOW_END
              value: "05:00"
```

**Reloader pattern for safe restarts:**
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: reloader-config
data:
  config.yaml: |
    reloadStrategy: rolling
    ignoredNamespaces:
      - kube-system
      - flux-system
    reloadOnCreate: false
    reloadTime:
      start: "02:00"
      end: "04:00"
      timezone: "UTC"
      daysOfWeek: ["Saturday", "Sunday"]
```

**Why:** Updates during peak hours maximize user impact if something goes wrong.

### 5. Always Implement Update Notifications

**WRONG:**
```yaml
# Silent updates
kind: HelmRelease
spec:
  upgrade:
    remediation:
      retries: 3
  # No notifications on failure!
```

**RIGHT:**
```yaml
# Comprehensive notifications
apiVersion: notification.toolkit.fluxcd.io/v1
kind: Alert
metadata:
  name: upgrade-alerts
spec:
  eventSeverity: info
  eventSources:
    - kind: HelmRelease
      namespace: '*'
    - kind: Kustomization
      namespace: '*'
  inclusionList:
    - ".*upgrade.*"
    - ".*error.*"
  providerRef:
    name: discord-webhook
---
apiVersion: notification.toolkit.fluxcd.io/v1
kind: Provider
metadata:
  name: discord-webhook
spec:
  type: discord
  channel: operations
  secretRef:
    name: discord-webhook-secret
```

**Why:** Silent failures mean extended downtime. Notifications enable quick response.

## Automation Patterns

### Safe Rolling Updates

```yaml
# Deployment with safe update strategy
apiVersion: apps/v1
kind: Deployment
spec:
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0  # Zero downtime
  minReadySeconds: 30  # Bake time
  progressDeadlineSeconds: 600
  revisionHistoryLimit: 10  # Keep history for rollback
```

### Canary Automation

```yaml
# Flagger for automated canary
apiVersion: flagger.app/v1beta1
kind: Canary
metadata:
  name: app-canary
spec:
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: app
  service:
    port: 80
  analysis:
    interval: 1m
    threshold: 5
    maxWeight: 50
    stepWeight: 10
    # Automatic rollback on failures
    metrics:
    - name: request-success-rate
      thresholdRange:
        min: 99
      interval: 1m
    webhooks:
    - name: load-test
      url: http://flagger-loadtester.test/
      metadata:
        type: cmd
        cmd: "hey -z 1m -q 10 -c 2 http://app-canary.test/"
```

### Dependency Update Groups

```yaml
# Renovate grouping related updates
{
  "packageRules": [{
    "groupName": "kubernetes packages",
    "matchPackagePatterns": ["kubernetes", "k8s"],
    "matchUpdateTypes": ["minor", "patch"],
    "automerge": false
  }, {
    "groupName": "monitoring stack",
    "matchPackageNames": [
      "prometheus",
      "grafana",
      "alertmanager"
    ],
    "schedule": ["every weekend"],
    "automerge": false
  }],
  "regexManagers": [{
    "fileMatch": [".*\\.ya?ml$"],
    "matchStrings": [
      "image: (?<depName>.*?):(?<currentValue>.*?)\\s"
    ],
    "datasourceTemplate": "docker"
  }]
}
```

## Monitoring Automation

### Update Metrics

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: update-dashboard
data:
  dashboard.json: |
    {
      "panels": [{
        "title": "Pending Updates",
        "targets": [{
          "expr": "count(renovate_pending_updates)"
        }]
      }, {
        "title": "Failed Updates",
        "targets": [{
          "expr": "rate(flux_reconcile_errors_total[5m])"
        }]
      }, {
        "title": "Update Success Rate",
        "targets": [{
          "expr": "rate(flux_reconcile_success_total[5m])"
        }]
      }]
    }
```

## Recovery Procedures

### Automated Update Rollback

```bash
#!/bin/bash
# Automatic rollback on failure detection

check_deployment_health() {
  local deployment=$1
  local namespace=$2
  
  # Check if deployment is healthy
  kubectl rollout status deployment/$deployment -n $namespace --timeout=5m
  return $?
}

rollback_if_unhealthy() {
  local deployment=$1
  local namespace=$2
  
  if ! check_deployment_health $deployment $namespace; then
    echo "Deployment unhealthy, rolling back..."
    kubectl rollout undo deployment/$deployment -n $namespace
    
    # Notify
    curl -X POST $WEBHOOK_URL \
      -H 'Content-Type: application/json' \
      -d "{\"text\":\"Rolled back $deployment in $namespace\"}"
  fi
}

# Monitor all deployments
for ns in $(kubectl get ns -o name | cut -d/ -f2); do
  for deploy in $(kubectl get deploy -n $ns -o name | cut -d/ -f2); do
    rollback_if_unhealthy $deploy $ns
  done
done
```

### Pause Automation

```bash
# Emergency automation pause
flux suspend kustomization --all
flux suspend helmrelease --all
flux suspend imagerepository --all

# Notify team
echo "EMERGENCY: All Flux automation suspended" | \
  discord-webhook-notify

# Resume after fix
flux resume kustomization --all
```

## Pre-Operation Checklist

- [ ] Update schedules configured for maintenance windows
- [ ] Test requirements defined for auto-merge
- [ ] Rollback procedures tested
- [ ] Notification channels configured
- [ ] Update groups logically organized
- [ ] Rate limits set on automation
- [ ] Monitoring dashboards created
- [ ] Emergency pause procedure documented

## Incidents

### 2024-04-12: Cascade Update Failure
- **What happened:** Auto-merged 50+ updates at once
- **Impact:** Multiple services broken simultaneously
- **Root cause:** No rate limiting on auto-merge
- **Lesson:** Limit concurrent automated updates

### 2024-06-28: Peak Hours Update Disaster
- **What happened:** Node updates triggered at 2 PM
- **Impact:** Production outage during business hours
- **Root cause:** Cron schedule in wrong timezone
- **Lesson:** Always specify timezone and maintenance windows

### 2024-09-15: Silent Update Failures
- **What happened:** Image updates failing for weeks
- **Impact:** Running 2-month-old versions with vulnerabilities
- **Root cause:** No alerts on automation failures
- **Lesson:** Monitor and alert on all automation