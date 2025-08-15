# Power Consumption Monitoring Guide for Anton Homelab

## Overview

Understanding power consumption is crucial for operating costs and capacity planning. This guide covers hardware-based monitoring, software metrics, and cost calculation methods for your MS-01 mini PC cluster.

## Hardware Specifications

### MS-01 Power Profile
- **TDP**: Intel 12th Gen (Alder Lake) - typically 65W TDP
- **Idle Power**: ~20-30W per node
- **Average Load**: ~40-60W per node
- **Peak Power**: ~90-120W per node
- **Power Supply**: External adapter (efficiency ~85-90%)

### Cluster Total (3 nodes)
- **Idle**: ~60-90W
- **Average**: ~120-180W
- **Peak**: ~270-360W

## Power Monitoring Methods

### 1. Hardware-Based Monitoring (Most Accurate)

#### Smart Power Outlets
```yaml
# Recommended devices for accurate measurement
Options:
  - TP-Link Kasa Smart Plug (KP125)
    - Real-time power monitoring
    - Historical data tracking
    - ~$15-20 per outlet
    
  - Shelly Plug US
    - MQTT integration
    - Prometheus metrics export
    - ~$25-30 per outlet
    
  - Emporia Vue Smart Plug
    - Detailed energy monitoring
    - API access available
    - ~$10-15 per outlet
```

#### Setup with Prometheus
```yaml
# prometheus-smart-plug-exporter.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: power-monitor
  namespace: monitoring
spec:
  replicas: 1
  selector:
    matchLabels:
      app: power-monitor
  template:
    metadata:
      labels:
        app: power-monitor
    spec:
      containers:
      - name: shelly-exporter
        image: geerlingguy/shelly-plug-prometheus:latest
        env:
        - name: SHELLY_HOSTS
          value: "192.168.1.201,192.168.1.202,192.168.1.203"  # Your Shelly IPs
        ports:
        - containerPort: 9924
---
apiVersion: v1
kind: Service
metadata:
  name: power-monitor
  namespace: monitoring
spec:
  selector:
    app: power-monitor
  ports:
  - port: 9924
    targetPort: 9924
```

### 2. Software-Based Estimation

#### Node Exporter Power Metrics
```bash
# Install intel-rapl exporter for CPU power monitoring
cat > scripts/setup-power-monitoring.ts << 'EOF'
#!/usr/bin/env -S deno run --allow-all

import { $ } from "https://deno.land/x/dax@0.35.0/mod.ts";

async function setupPowerMonitoring() {
  console.log("Setting up software-based power monitoring...");
  
  // Create DaemonSet for RAPL power monitoring
  const raplExporter = `
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: rapl-exporter
  namespace: monitoring
spec:
  selector:
    matchLabels:
      app: rapl-exporter
  template:
    metadata:
      labels:
        app: rapl-exporter
    spec:
      hostPID: true
      containers:
      - name: rapl-exporter
        image: hubblo/scaphandre:latest
        ports:
        - containerPort: 8080
        securityContext:
          privileged: true
        volumeMounts:
        - name: proc
          mountPath: /proc
        - name: sys
          mountPath: /sys
      volumes:
      - name: proc
        hostPath:
          path: /proc
      - name: sys
        hostPath:
          path: /sys
`;

  await Deno.writeTextFile("kubernetes/monitoring/rapl-exporter.yaml", raplExporter);
  await $`kubectl apply -f kubernetes/monitoring/rapl-exporter.yaml`;
  
  console.log("✅ RAPL exporter deployed for CPU power monitoring");
}

if (import.meta.main) {
  await setupPowerMonitoring();
}
EOF

chmod +x scripts/setup-power-monitoring.ts
```

### 3. IPMI/BMC Monitoring (If Available)

```yaml
# ipmi-exporter.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ipmi-exporter
  namespace: monitoring
spec:
  replicas: 1
  selector:
    matchLabels:
      app: ipmi-exporter
  template:
    metadata:
      labels:
        app: ipmi-exporter
    spec:
      containers:
      - name: ipmi-exporter
        image: prometheuscommunity/ipmi-exporter:latest
        args:
        - --config.file=/config/ipmi.yml
        volumeMounts:
        - name: config
          mountPath: /config
      volumes:
      - name: config
        configMap:
          name: ipmi-config
```

## Power Consumption Dashboard

### Grafana Dashboard Configuration
```json
{
  "dashboard": {
    "title": "Anton Homelab Power Consumption",
    "panels": [
      {
        "title": "Current Power Draw",
        "targets": [
          {
            "expr": "sum(power_consumption_watts)"
          }
        ]
      },
      {
        "title": "Power Cost per Day",
        "targets": [
          {
            "expr": "sum(power_consumption_watts) * 24 / 1000 * 0.12"
          }
        ]
      },
      {
        "title": "Monthly Power Cost",
        "targets": [
          {
            "expr": "sum(power_consumption_watts) * 24 * 30 / 1000 * 0.12"
          }
        ]
      }
    ]
  }
}
```

## Cost Calculation

### Power Cost Formula
```
Daily Cost = (Total Watts / 1000) × 24 hours × $/kWh
Monthly Cost = Daily Cost × 30
Annual Cost = Daily Cost × 365
```

### Cost Calculator Script
```typescript
#!/usr/bin/env -S deno run --allow-all
// scripts/calculate-power-costs.ts

interface PowerMetrics {
  idleWatts: number;
  averageWatts: number;
  peakWatts: number;
  electricityRate: number; // $/kWh
}

function calculatePowerCosts(metrics: PowerMetrics) {
  const hoursPerDay = 24;
  const daysPerMonth = 30;
  const daysPerYear = 365;
  
  // Convert watts to kilowatts
  const idleKw = metrics.idleWatts / 1000;
  const avgKw = metrics.averageWatts / 1000;
  const peakKw = metrics.peakWatts / 1000;
  
  // Calculate costs
  const dailyCost = avgKw * hoursPerDay * metrics.electricityRate;
  const monthlyCost = dailyCost * daysPerMonth;
  const annualCost = dailyCost * daysPerYear;
  
  // Calculate for different scenarios
  const idleCostMonthly = idleKw * hoursPerDay * daysPerMonth * metrics.electricityRate;
  const peakCostMonthly = peakKw * hoursPerDay * daysPerMonth * metrics.electricityRate;
  
  return {
    daily: dailyCost.toFixed(2),
    monthly: monthlyCost.toFixed(2),
    annual: annualCost.toFixed(2),
    scenarios: {
      idle: idleCostMonthly.toFixed(2),
      average: monthlyCost.toFixed(2),
      peak: peakCostMonthly.toFixed(2)
    }
  };
}

// MS-01 cluster estimates (3 nodes)
const clusterMetrics: PowerMetrics = {
  idleWatts: 90,      // 30W × 3 nodes
  averageWatts: 150,  // 50W × 3 nodes
  peakWatts: 300,     // 100W × 3 nodes
  electricityRate: 0.12 // US average $/kWh
};

const costs = calculatePowerCosts(clusterMetrics);

console.log("=== Anton Homelab Power Cost Analysis ===");
console.log(`Electricity Rate: $${clusterMetrics.electricityRate}/kWh`);
console.log("");
console.log("Average Operating Costs:");
console.log(`  Daily: $${costs.daily}`);
console.log(`  Monthly: $${costs.monthly}`);
console.log(`  Annual: $${costs.annual}`);
console.log("");
console.log("Scenario Analysis (Monthly):");
console.log(`  Idle (${clusterMetrics.idleWatts}W): $${costs.scenarios.idle}`);
console.log(`  Average (${clusterMetrics.averageWatts}W): $${costs.scenarios.average}`);
console.log(`  Peak (${clusterMetrics.peakWatts}W): $${costs.scenarios.peak}`);
```

## Prometheus Alerts for Power

```yaml
# power-alerts.yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: power-consumption-alerts
  namespace: monitoring
spec:
  groups:
  - name: power
    rules:
    - alert: HighPowerConsumption
      expr: sum(power_consumption_watts) > 250
      for: 10m
      annotations:
        summary: "Cluster power consumption high"
        description: "Power draw is {{ $value }}W, above 250W threshold"
    
    - alert: PowerCostThreshold
      expr: (sum(power_consumption_watts) * 24 * 30 / 1000 * 0.12) > 30
      annotations:
        summary: "Monthly power cost exceeds $30"
        description: "Projected monthly cost: ${{ $value }}"
```

## Quick Power Estimates

### Based on Current Utilization (6.5% CPU)
- **Estimated Current Draw**: ~100-120W total
- **Daily Cost**: ~$0.35 @ $0.12/kWh
- **Monthly Cost**: ~$10.50
- **Annual Cost**: ~$128

### At Higher Utilization (50% CPU)
- **Estimated Draw**: ~180-200W total
- **Daily Cost**: ~$0.58
- **Monthly Cost**: ~$17.40
- **Annual Cost**: ~$212

### At Peak Load (90% CPU)
- **Estimated Draw**: ~270-300W total
- **Daily Cost**: ~$0.86
- **Monthly Cost**: ~$25.80
- **Annual Cost**: ~$314

## Recommendations

1. **Immediate Actions**
   - Deploy smart plugs on each node for accurate measurement
   - Set up Prometheus exporters for power metrics
   - Create Grafana dashboard for real-time monitoring

2. **Cost Optimization**
   - Enable CPU power scaling (if not already enabled)
   - Consider node sleep schedules for non-critical times
   - Monitor correlation between workload and power draw

3. **Long-term Planning**
   - Track power efficiency as workloads grow
   - Consider power cost in capacity planning decisions
   - Evaluate newer hardware for better performance/watt

## Integration with Capacity Planning

Power consumption should factor into expansion decisions:
- Adding a 4th node: +$3-5/month in power costs
- Memory upgrades: Minimal power impact (~5W per node)
- Storage expansion: +10-15W per NVMe drive

## Summary

Your Anton homelab cluster is very power-efficient:
- Current estimated cost: **~$10-15/month**
- Maximum cost at full load: **~$26/month**
- Annual operating cost: **~$120-300**

This makes it extremely cost-effective compared to cloud alternatives, which would cost thousands per month for equivalent compute resources.