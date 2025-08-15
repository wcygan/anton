#!/usr/bin/env -S deno run --allow-run --allow-read --allow-write --allow-net

/**
 * Realistic Workload Load Test
 * 
 * Simulates real-world application patterns:
 * - Web applications with varying traffic
 * - Database workloads with read/write patterns
 * - Batch processing jobs
 * - Microservices communication
 */

import { parseArgs } from "jsr:@std/cli/parse-args";

interface WorkloadPattern {
  name: string;
  replicas: number;
  cpuRequest: string;
  memoryRequest: string;
  cpuLimit: string;
  memoryLimit: string;
  storageSize?: string;
}

class RealisticWorkloadTester {
  private namespace = "realistic-load-test";
  
  private workloads: WorkloadPattern[] = [
    {
      name: "web-frontend",
      replicas: 3,
      cpuRequest: "100m",
      memoryRequest: "256Mi", 
      cpuLimit: "500m",
      memoryLimit: "512Mi"
    },
    {
      name: "api-backend",
      replicas: 2,
      cpuRequest: "200m",
      memoryRequest: "512Mi",
      cpuLimit: "1000m", 
      memoryLimit: "1Gi"
    },
    {
      name: "database",
      replicas: 1,
      cpuRequest: "500m",
      memoryRequest: "1Gi",
      cpuLimit: "2000m",
      memoryLimit: "2Gi",
      storageSize: "10Gi"
    },
    {
      name: "batch-processor",
      replicas: 1,
      cpuRequest: "1000m",
      memoryRequest: "2Gi",
      cpuLimit: "4000m",
      memoryLimit: "4Gi"
    },
    {
      name: "log-aggregator",
      replicas: 2,
      cpuRequest: "150m",
      memoryRequest: "384Mi",
      cpuLimit: "750m",
      memoryLimit: "768Mi"
    }
  ];

  async runRealisticLoadTest(): Promise<void> {
    console.log("🏭 Starting Realistic Workload Load Test...");
    
    try {
      await this.setupNamespace();
      await this.deployWorkloads();
      await this.simulateTraffic();
      await this.runPerformanceTests();
      await this.generateReport();
    } finally {
      await this.cleanup();
    }
  }

  private async setupNamespace(): Promise<void> {
    console.log("🔧 Setting up test namespace...");
    await this.runCommand(`kubectl create namespace ${this.namespace} --dry-run=client -o yaml | kubectl apply -f -`);
  }

  private async deployWorkloads(): Promise<void> {
    console.log("🚀 Deploying realistic workloads...");

    for (const workload of this.workloads) {
      console.log(`  Deploying ${workload.name}...`);
      await this.deployWorkload(workload);
    }

    // Wait for all deployments to be ready
    console.log("⏳ Waiting for workloads to be ready...");
    for (const workload of this.workloads) {
      await this.runCommand(`kubectl wait --for=condition=available deployment/${workload.name} -n ${this.namespace} --timeout=300s`);
    }
  }

  private async deployWorkload(workload: WorkloadPattern): Promise<void> {
    const yaml = this.generateWorkloadYAML(workload);
    await this.runCommand(`echo '${yaml}' | kubectl apply -f -`);
  }

  private generateWorkloadYAML(workload: WorkloadPattern): string {
    const hasStorage = workload.storageSize !== undefined;
    
    let yaml = `
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ${workload.name}
  namespace: ${this.namespace}
spec:
  replicas: ${workload.replicas}
  selector:
    matchLabels:
      app: ${workload.name}
  template:
    metadata:
      labels:
        app: ${workload.name}
    spec:
      containers:
      - name: ${workload.name}
        image: ${this.getWorkloadImage(workload.name)}
        ${this.getWorkloadCommand(workload.name)}
        resources:
          requests:
            cpu: ${workload.cpuRequest}
            memory: ${workload.memoryRequest}
          limits:
            cpu: ${workload.cpuLimit}
            memory: ${workload.memoryLimit}
        ${hasStorage ? `volumeMounts:\n        - name: data\n          mountPath: /data` : ''}
      ${hasStorage ? `volumes:\n      - name: data\n        persistentVolumeClaim:\n          claimName: ${workload.name}-pvc` : ''}
---
apiVersion: v1
kind: Service
metadata:
  name: ${workload.name}-svc
  namespace: ${this.namespace}
spec:
  selector:
    app: ${workload.name}
  ports:
  - port: 80
    targetPort: 8080
`;

    if (hasStorage) {
      yaml += `
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: ${workload.name}-pvc
  namespace: ${this.namespace}
spec:
  accessModes:
  - ReadWriteOnce
  resources:
    requests:
      storage: ${workload.storageSize}
  storageClassName: ceph-block
`;
    }

    return yaml;
  }

  private getWorkloadImage(name: string): string {
    const images = {
      "web-frontend": "nginx:alpine",
      "api-backend": "httpd:alpine", 
      "database": "postgres:13-alpine",
      "batch-processor": "busybox",
      "log-aggregator": "fluent/fluent-bit:latest"
    };
    return images[name] || "busybox";
  }

  private getWorkloadCommand(name: string): string {
    const commands = {
      "web-frontend": "",
      "api-backend": "",
      "database": `
        env:
        - name: POSTGRES_DB
          value: testdb
        - name: POSTGRES_USER
          value: testuser
        - name: POSTGRES_PASSWORD
          value: testpass`,
      "batch-processor": `
        command: ["/bin/sh", "-c"]
        args:
        - |
          while true; do
            echo "Processing batch job $(date)"
            # Simulate CPU intensive work
            dd if=/dev/urandom of=/tmp/test bs=1M count=100 2>/dev/null
            sleep 30
          done`,
      "log-aggregator": ""
    };
    return commands[name] || "";
  }

  private async simulateTraffic(): Promise<void> {
    console.log("🌐 Simulating realistic traffic patterns...");

    // Deploy traffic generator
    const trafficGenYaml = `
apiVersion: batch/v1
kind: Job
metadata:
  name: traffic-generator
  namespace: ${this.namespace}
spec:
  template:
    spec:
      restartPolicy: Never
      containers:
      - name: traffic-gen
        image: peterevans/curl:latest
        command: ["/bin/sh", "-c"]
        args:
        - |
          echo "Starting traffic simulation..."
          
          # Simulate web traffic (varying load)
          for i in {1..60}; do
            # Peak traffic (10 requests)
            if [ $((i % 10)) -eq 0 ]; then
              for j in {1..10}; do
                curl -s http://web-frontend-svc.${this.namespace}.svc.cluster.local/ &
              done
            # Normal traffic (2 requests)  
            else
              for j in {1..2}; do
                curl -s http://web-frontend-svc.${this.namespace}.svc.cluster.local/ &
              done
            fi
            
            # API backend requests
            curl -s http://api-backend-svc.${this.namespace}.svc.cluster.local/ &
            
            sleep 10
          done
          
          wait
          echo "Traffic simulation completed"
`;

    await this.runCommand(`echo '${trafficGenYaml}' | kubectl apply -f -`);
    
    // Wait for traffic generation to complete
    await this.runCommand(`kubectl wait --for=condition=complete job/traffic-generator -n ${this.namespace} --timeout=600s`);
  }

  private async runPerformanceTests(): Promise<void> {
    console.log("📊 Running performance analysis...");

    // Get resource usage for each workload
    const resourceUsage = await this.runCommand(`kubectl top pods -n ${this.namespace}`);
    console.log("Resource Usage:\n" + resourceUsage);

    // Check node resource utilization
    const nodeUsage = await this.runCommand(`kubectl top nodes`);
    console.log("Node Utilization:\n" + nodeUsage);

    // Check storage usage
    try {
      const pvcs = await this.runCommand(`kubectl get pvc -n ${this.namespace}`);
      console.log("Storage Claims:\n" + pvcs);
    } catch (e) {
      console.log("No PVCs found");
    }
  }

  private async generateReport(): Promise<void> {
    console.log("📝 Generating load test report...");

    const report = {
      timestamp: new Date().toISOString(),
      workloads: this.workloads.length,
      totalReplicas: this.workloads.reduce((sum, w) => sum + w.replicas, 0),
      resourceRequests: {
        cpu: this.workloads.reduce((sum, w) => sum + parseFloat(w.cpuRequest.replace('m', '')), 0) + "m",
        memory: this.calculateTotalMemory()
      },
      testDuration: "10 minutes",
      status: "completed"
    };

    console.log("\n" + "=".repeat(50));
    console.log("📊 REALISTIC LOAD TEST REPORT");
    console.log("=".repeat(50));
    console.log(JSON.stringify(report, null, 2));
    console.log("=".repeat(50));
  }

  private calculateTotalMemory(): string {
    let totalMi = 0;
    this.workloads.forEach(w => {
      const memStr = w.memoryRequest.replace('Mi', '').replace('Gi', '');
      const multiplier = w.memoryRequest.includes('Gi') ? 1024 : 1;
      totalMi += parseFloat(memStr) * multiplier * w.replicas;
    });
    return totalMi > 1024 ? `${(totalMi / 1024).toFixed(1)}Gi` : `${totalMi}Mi`;
  }

  private async cleanup(): Promise<void> {
    console.log("🧹 Cleaning up realistic load test...");
    try {
      await this.runCommand(`kubectl delete namespace ${this.namespace} --timeout=120s`);
    } catch (error) {
      console.log("Cleanup completed with warnings");
    }
  }

  private async runCommand(command: string): Promise<string> {
    const cmd = new Deno.Command("sh", {
      args: ["-c", command],
      stdout: "piped",
      stderr: "piped"
    });

    const { success, stdout, stderr } = await cmd.output();
    
    if (!success) {
      throw new Error(`Command failed: ${new TextDecoder().decode(stderr)}`);
    }
    
    return new TextDecoder().decode(stdout);
  }
}

// Main execution
async function main() {
  const tester = new RealisticWorkloadTester();
  await tester.runRealisticLoadTest();
}

if (import.meta.main) {
  main();
}