#!/usr/bin/env -S deno run --allow-run --allow-read --allow-write --allow-net

/**
 * Chaos Engineering & Resilience Testing
 * 
 * Tests cluster resilience by introducing controlled failures:
 * - Pod failures and restarts
 * - Node resource pressure
 * - Network partitions (simulation)
 * - Storage failures
 */

import { parseArgs } from "jsr:@std/cli/parse-args";

interface ChaosTest {
  name: string;
  description: string;
  run: () => Promise<boolean>;
}

class ChaosResilienceTester {
  private namespace = "chaos-test";
  private tests: ChaosTest[] = [];

  constructor() {
    this.tests = [
      {
        name: "Pod Failure Recovery",
        description: "Kill pods and verify automatic recovery",
        run: () => this.testPodFailureRecovery()
      },
      {
        name: "Resource Pressure",
        description: "Create resource pressure and test scheduling",
        run: () => this.testResourcePressure()
      },
      {
        name: "Storage Resilience", 
        description: "Test storage failure handling",
        run: () => this.testStorageResilience()
      },
      {
        name: "Control Plane Stress",
        description: "Stress API server with rapid requests",
        run: () => this.testControlPlaneStress()
      }
    ];
  }

  async runChaosTests(): Promise<void> {
    console.log("🔥 Starting Chaos Engineering Tests...");
    
    await this.setupNamespace();
    
    let passed = 0;
    let total = this.tests.length;

    for (const test of this.tests) {
      console.log(`\n🧪 Running: ${test.name}`);
      console.log(`   ${test.description}`);
      
      try {
        const success = await test.run();
        if (success) {
          console.log(`✅ ${test.name} PASSED`);
          passed++;
        } else {
          console.log(`❌ ${test.name} FAILED`);
        }
      } catch (error) {
        console.log(`❌ ${test.name} ERROR: ${error}`);
      }
    }

    await this.cleanup();

    console.log("\n" + "=".repeat(50));
    console.log("🔥 CHAOS ENGINEERING RESULTS");
    console.log("=".repeat(50));
    console.log(`Passed: ${passed}/${total} tests`);
    
    if (passed === total) {
      console.log("🎉 Cluster shows excellent resilience!");
    } else if (passed >= total * 0.75) {
      console.log("⚠️  Cluster has good resilience with some areas for improvement");
    } else {
      console.log("❌ Cluster needs significant resilience improvements");
    }
    console.log("=".repeat(50));
  }

  private async setupNamespace(): Promise<void> {
    await this.runCommand(`kubectl create namespace ${this.namespace} --dry-run=client -o yaml | kubectl apply -f -`);
  }

  private async testPodFailureRecovery(): Promise<boolean> {
    // Deploy a test application
    const testAppYaml = `
apiVersion: apps/v1
kind: Deployment
metadata:
  name: resilience-test-app
  namespace: ${this.namespace}
spec:
  replicas: 3
  selector:
    matchLabels:
      app: resilience-test
  template:
    metadata:
      labels:
        app: resilience-test
    spec:
      containers:
      - name: app
        image: nginx:alpine
        resources:
          requests:
            cpu: 50m
            memory: 64Mi
          limits:
            cpu: 100m
            memory: 128Mi
`;

    await this.runCommand(`echo '${testAppYaml}' | kubectl apply -f -`);
    await this.runCommand(`kubectl wait --for=condition=available deployment/resilience-test-app -n ${this.namespace} --timeout=120s`);

    // Get initial pod count
    const initialPods = await this.runCommand(`kubectl get pods -n ${this.namespace} -l app=resilience-test --no-headers | wc -l`);
    console.log(`   Initial pods: ${initialPods.trim()}`);

    // Kill a pod
    const podToKill = await this.runCommand(`kubectl get pods -n ${this.namespace} -l app=resilience-test -o jsonpath='{.items[0].metadata.name}'`);
    console.log(`   Killing pod: ${podToKill.trim()}`);
    
    await this.runCommand(`kubectl delete pod ${podToKill.trim()} -n ${this.namespace}`);

    // Wait for recovery
    await new Promise(resolve => setTimeout(resolve, 30000)); // 30 seconds

    // Check if pods recovered
    const finalPods = await this.runCommand(`kubectl get pods -n ${this.namespace} -l app=resilience-test --no-headers | wc -l`);
    const readyPods = await this.runCommand(`kubectl get pods -n ${this.namespace} -l app=resilience-test --no-headers | grep Running | wc -l`);

    console.log(`   Final pods: ${finalPods.trim()}, Ready: ${readyPods.trim()}`);

    return parseInt(finalPods.trim()) === 3 && parseInt(readyPods.trim()) === 3;
  }

  private async testResourcePressure(): Promise<boolean> {
    // Create memory pressure pod
    const memoryPressureYaml = `
apiVersion: v1
kind: Pod
metadata:
  name: memory-pressure
  namespace: ${this.namespace}
spec:
  containers:
  - name: memory-eater
    image: polinux/stress
    command: ["stress"]
    args: ["--vm", "1", "--vm-bytes", "1G", "--timeout", "60s"]
    resources:
      requests:
        memory: 512Mi
      limits:
        memory: 1Gi
`;

    await this.runCommand(`echo '${memoryPressureYaml}' | kubectl apply -f -`);

    // Deploy a test pod during pressure
    const testPodYaml = `
apiVersion: v1
kind: Pod
metadata:
  name: test-under-pressure
  namespace: ${this.namespace}
spec:
  containers:
  - name: test
    image: busybox
    command: ["sleep", "120"]
    resources:
      requests:
        memory: 256Mi
      limits:
        memory: 512Mi
`;

    await this.runCommand(`echo '${testPodYaml}' | kubectl apply -f -`);

    // Wait and check if test pod was scheduled
    await new Promise(resolve => setTimeout(resolve, 30000));

    try {
      const podStatus = await this.runCommand(`kubectl get pod test-under-pressure -n ${this.namespace} -o jsonpath='{.status.phase}'`);
      return podStatus.trim() === "Running";
    } catch {
      return false;
    }
  }

  private async testStorageResilience(): Promise<boolean> {
    // Create a pod with storage
    const storagePodYaml = `
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: chaos-storage-test
  namespace: ${this.namespace}
spec:
  accessModes:
  - ReadWriteOnce
  resources:
    requests:
      storage: 1Gi
  storageClassName: ceph-block
---
apiVersion: v1
kind: Pod
metadata:
  name: storage-test-pod
  namespace: ${this.namespace}
spec:
  containers:
  - name: test
    image: busybox
    command: ["/bin/sh", "-c"]
    args:
    - |
      echo "Writing test data..." > /data/test.txt
      sleep 300
    volumeMounts:
    - name: test-storage
      mountPath: /data
  volumes:
  - name: test-storage
    persistentVolumeClaim:
      claimName: chaos-storage-test
`;

    await this.runCommand(`echo '${storagePodYaml}' | kubectl apply -f -`);
    await this.runCommand(`kubectl wait --for=condition=ready pod/storage-test-pod -n ${this.namespace} --timeout=120s`);

    // Kill the pod and recreate
    await this.runCommand(`kubectl delete pod storage-test-pod -n ${this.namespace}`);

    const recreatePodYaml = `
apiVersion: v1
kind: Pod
metadata:
  name: storage-test-pod-2
  namespace: ${this.namespace}
spec:
  containers:
  - name: test
    image: busybox
    command: ["/bin/sh", "-c"]
    args:
    - |
      if [ -f /data/test.txt ]; then
        echo "Data persisted successfully"
        exit 0
      else
        echo "Data lost!"
        exit 1
      fi
    volumeMounts:
    - name: test-storage
      mountPath: /data
  volumes:
  - name: test-storage
    persistentVolumeClaim:
      claimName: chaos-storage-test
  restartPolicy: Never
`;

    await this.runCommand(`echo '${recreatePodYaml}' | kubectl apply -f -`);
    await this.runCommand(`kubectl wait --for=condition=complete pod/storage-test-pod-2 -n ${this.namespace} --timeout=60s`);

    try {
      const logs = await this.runCommand(`kubectl logs storage-test-pod-2 -n ${this.namespace}`);
      return logs.includes("Data persisted successfully");
    } catch {
      return false;
    }
  }

  private async testControlPlaneStress(): Promise<boolean> {
    console.log("   Creating API server stress...");
    
    const iterations = 100;
    let successCount = 0;
    const startTime = Date.now();

    // Rapid fire API requests
    const promises = [];
    for (let i = 0; i < iterations; i++) {
      promises.push(
        this.runCommand(`kubectl create configmap stress-test-${i} -n ${this.namespace} --from-literal=test=value`)
          .then(() => { successCount++; })
          .catch(() => {})
      );
    }

    await Promise.all(promises);
    
    const duration = Date.now() - startTime;
    const successRate = (successCount / iterations) * 100;
    
    console.log(`   API stress test: ${successCount}/${iterations} successful (${successRate.toFixed(1)}%) in ${duration}ms`);

    // Cleanup configmaps
    await this.runCommand(`kubectl delete configmap -n ${this.namespace} -l test=value`).catch(() => {});

    return successRate > 90; // 90% success rate under stress
  }

  private async cleanup(): Promise<void> {
    console.log("\n🧹 Cleaning up chaos tests...");
    try {
      await this.runCommand(`kubectl delete namespace ${this.namespace} --timeout=60s`);
    } catch (error) {
      console.log("Note: Some cleanup may need manual intervention");
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
  const tester = new ChaosResilienceTester();
  await tester.runChaosTests();
}

if (import.meta.main) {
  main();
}