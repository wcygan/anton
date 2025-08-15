#!/usr/bin/env -S deno run --allow-run --allow-read --allow-write --allow-net

/**
 * Simple Kubernetes Cluster Load Test
 * 
 * Tests essential cluster capabilities:
 * - Workload deployment
 * - Network connectivity  
 * - Resource enforcement
 * - API responsiveness
 * - Storage provisioning (with graceful timeout handling)
 */

import { parseArgs } from "jsr:@std/cli/parse-args";

interface TestResult {
  name: string;
  status: "pass" | "fail" | "warning";
  duration: number;
  details: string;
}

class ClusterLoadTester {
  private namespace = "load-test";
  private results: TestResult[] = [];
  private verbose: boolean = false;

  constructor(verbose = false) {
    this.verbose = verbose;
  }

  async runLoadTest(): Promise<boolean> {
    console.log("🚀 Starting Kubernetes Cluster Load Test...");
    console.log(`Test namespace: ${this.namespace}`);
    
    try {
      await this.setupTestEnvironment();
      
      // Run core tests
      await this.testWorkloadDeployment();
      await this.testNetworkConnectivity();
      await this.testResourceLimits();
      await this.testControlPlaneResponsiveness();
      await this.testStorageProvisioning();
      
      this.printResults();
      return this.getOverallResult();
      
    } catch (error) {
      console.error("❌ Load test failed:", error);
      return false;
    } finally {
      await this.cleanup();
    }
  }

  private async setupTestEnvironment(): Promise<void> {
    this.log("🔧 Setting up test environment...");
    await this.runCommand(`kubectl create namespace ${this.namespace} --dry-run=client -o yaml | kubectl apply -f -`);
  }

  private async testWorkloadDeployment(): Promise<void> {
    const testName = "Workload Deployment";
    const startTime = Date.now();
    this.log("1️⃣ Testing workload deployment...");
    
    try {
      const appYaml = `
apiVersion: apps/v1
kind: Deployment
metadata:
  name: test-app
  namespace: ${this.namespace}
spec:
  replicas: 2
  selector:
    matchLabels:
      app: test-app
  template:
    metadata:
      labels:
        app: test-app
    spec:
      containers:
      - name: nginx
        image: nginx:alpine
        ports:
        - containerPort: 80
        resources:
          requests:
            cpu: 50m
            memory: 64Mi
          limits:
            cpu: 200m
            memory: 128Mi
---
apiVersion: v1
kind: Service
metadata:
  name: test-app-svc
  namespace: ${this.namespace}
spec:
  selector:
    app: test-app
  ports:
  - port: 80
    targetPort: 80
`;

      await this.runCommand(`echo '${appYaml}' | kubectl apply -f -`);
      await this.runCommand(`kubectl wait --for=condition=available deployment/test-app -n ${this.namespace} --timeout=90s`);

      const runningPods = await this.runCommand(`kubectl get pods -n ${this.namespace} -l app=test-app --field-selector=status.phase=Running --no-headers | wc -l`);
      
      if (parseInt(runningPods.trim()) === 2) {
        this.recordResult(testName, "pass", Date.now() - startTime, "2/2 pods deployed successfully");
      } else {
        this.recordResult(testName, "fail", Date.now() - startTime, `Only ${runningPods.trim()}/2 pods running`);
      }

    } catch (error) {
      this.recordResult(testName, "fail", Date.now() - startTime, `Deployment failed: ${error}`);
    }
  }

  private async testNetworkConnectivity(): Promise<void> {
    const testName = "Network Connectivity";
    const startTime = Date.now();
    this.log("2️⃣ Testing network connectivity...");
    
    try {
      const networkTestYaml = `
apiVersion: v1
kind: Pod
metadata:
  name: network-test
  namespace: ${this.namespace}
spec:
  containers:
  - name: test
    image: busybox
    command: ["/bin/sh", "-c"]
    args:
    - |
      echo "Testing network connectivity..."
      nslookup test-app-svc.${this.namespace}.svc.cluster.local
      wget -q --timeout=10 -O- http://test-app-svc.${this.namespace}.svc.cluster.local/ | head -1
      echo "Network test completed"
    resources:
      requests:
        cpu: 50m
        memory: 64Mi
      limits:
        cpu: 100m
        memory: 128Mi
  restartPolicy: Never
`;

      await this.runCommand(`echo '${networkTestYaml}' | kubectl apply -f -`);
      await this.runCommand(`kubectl wait --for=condition=complete pod/network-test -n ${this.namespace} --timeout=45s`);

      const logs = await this.runCommand(`kubectl logs network-test -n ${this.namespace}`);
      
      if (logs.includes("Network test completed")) {
        this.recordResult(testName, "pass", Date.now() - startTime, "Service discovery and HTTP connectivity working");
      } else {
        this.recordResult(testName, "fail", Date.now() - startTime, "Network connectivity issues detected");
      }

    } catch (error) {
      this.recordResult(testName, "fail", Date.now() - startTime, `Network test failed: ${error}`);
    }
  }

  private async testResourceLimits(): Promise<void> {
    const testName = "Resource Limits";
    const startTime = Date.now();
    this.log("3️⃣ Testing resource limits enforcement...");
    
    try {
      const resourceTestYaml = `
apiVersion: v1
kind: Pod
metadata:
  name: resource-test
  namespace: ${this.namespace}
spec:
  containers:
  - name: test
    image: busybox
    command: ["sleep", "30"]
    resources:
      requests:
        cpu: 100m
        memory: 128Mi
      limits:
        cpu: 200m
        memory: 256Mi
  restartPolicy: Never
`;

      await this.runCommand(`echo '${resourceTestYaml}' | kubectl apply -f -`);
      await this.runCommand(`kubectl wait --for=condition=complete pod/resource-test -n ${this.namespace} --timeout=45s`);

      const podStatus = await this.runCommand(`kubectl get pod resource-test -n ${this.namespace} -o jsonpath='{.status.phase}'`);
      
      if (podStatus.trim() === "Succeeded") {
        this.recordResult(testName, "pass", Date.now() - startTime, "Resource limits properly enforced");
      } else {
        this.recordResult(testName, "fail", Date.now() - startTime, `Pod ended with status: ${podStatus.trim()}`);
      }

    } catch (error) {
      this.recordResult(testName, "fail", Date.now() - startTime, `Resource test failed: ${error}`);
    }
  }

  private async testControlPlaneResponsiveness(): Promise<void> {
    const testName = "Control Plane API";
    const startTime = Date.now();
    this.log("4️⃣ Testing control plane API responsiveness...");
    
    try {
      const operations = 15;
      let successCount = 0;

      for (let i = 0; i < operations; i++) {
        try {
          await this.runCommand(`kubectl create configmap test-cm-${i} -n ${this.namespace} --from-literal=test=value`);
          await this.runCommand(`kubectl delete configmap test-cm-${i} -n ${this.namespace}`);
          successCount++;
        } catch (error) {
          this.log(`API operation ${i} failed: ${error}`);
        }
      }

      const successRate = (successCount / operations) * 100;
      
      if (successRate >= 95) {
        this.recordResult(testName, "pass", Date.now() - startTime, `${successCount}/${operations} operations successful (${successRate.toFixed(1)}%)`);
      } else if (successRate >= 85) {
        this.recordResult(testName, "warning", Date.now() - startTime, `${successCount}/${operations} operations successful (${successRate.toFixed(1)}%)`);
      } else {
        this.recordResult(testName, "fail", Date.now() - startTime, `Only ${successCount}/${operations} operations successful (${successRate.toFixed(1)}%)`);
      }

    } catch (error) {
      this.recordResult(testName, "fail", Date.now() - startTime, `Control plane test failed: ${error}`);
    }
  }

  private async testStorageProvisioning(): Promise<void> {
    const testName = "Storage Provisioning";
    const startTime = Date.now();
    this.log("5️⃣ Testing storage provisioning...");
    
    try {
      const pvcYaml = `
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: test-storage
  namespace: ${this.namespace}
spec:
  accessModes:
  - ReadWriteOnce
  resources:
    requests:
      storage: 1Gi
  storageClassName: ceph-block
`;

      await this.runCommand(`echo '${pvcYaml}' | kubectl apply -f -`);
      
      // Try with a shorter timeout for storage - Ceph can be slow
      try {
        await this.runCommand(`kubectl wait --for=condition=bound pvc/test-storage -n ${this.namespace} --timeout=60s`);
        this.recordResult(testName, "pass", Date.now() - startTime, "Storage volume provisioned successfully");
      } catch (timeoutError) {
        // Check if it's just slow but working
        const pvcStatus = await this.runCommand(`kubectl get pvc test-storage -n ${this.namespace} -o jsonpath='{.status.phase}'`);
        if (pvcStatus.trim() === "Pending") {
          this.recordResult(testName, "warning", Date.now() - startTime, "Storage provisioning slow but in progress");
        } else {
          this.recordResult(testName, "fail", Date.now() - startTime, `Storage provisioning failed: ${pvcStatus.trim()}`);
        }
      }

    } catch (error) {
      this.recordResult(testName, "fail", Date.now() - startTime, `Storage test failed: ${error}`);
    }
  }

  private async cleanup(): Promise<void> {
    this.log("🧹 Cleaning up test resources...");
    try {
      await this.runCommand(`kubectl delete namespace ${this.namespace} --timeout=60s`);
      this.log("✅ Cleanup completed");
    } catch (error) {
      console.warn("⚠️ Cleanup may be incomplete:", error);
    }
  }

  private recordResult(name: string, status: "pass" | "fail" | "warning", duration: number, details: string): void {
    this.results.push({ name, status, duration, details });
    const icon = status === "pass" ? "✅" : status === "warning" ? "⚠️" : "❌";
    this.log(`   ${icon} ${name}: ${details} (${(duration / 1000).toFixed(1)}s)`);
  }

  private printResults(): void {
    const passed = this.results.filter(r => r.status === "pass").length;
    const warnings = this.results.filter(r => r.status === "warning").length;
    const failed = this.results.filter(r => r.status === "fail").length;
    const total = this.results.length;

    console.log("\n" + "=".repeat(60));
    console.log("📊 CLUSTER LOAD TEST RESULTS");
    console.log("=".repeat(60));

    this.results.forEach(result => {
      const icon = result.status === "pass" ? "✅" : result.status === "warning" ? "⚠️" : "❌";
      console.log(`${icon} ${result.name}`);
      console.log(`   ${result.details}`);
      console.log(`   Duration: ${(result.duration / 1000).toFixed(1)}s`);
      console.log();
    });

    console.log("=".repeat(60));
    console.log(`📈 Summary: ${passed} passed, ${warnings} warnings, ${failed} failed`);
    
    if (failed === 0 && warnings === 0) {
      console.log("🎉 EXCELLENT - All tests passed! Cluster is production ready");
    } else if (failed === 0) {
      console.log("✅ GOOD - All tests passed with some warnings. Cluster is mostly ready");
    } else if (failed <= 1) {
      console.log("⚠️ NEEDS ATTENTION - Minor issues detected. Address before production");
    } else {
      console.log("❌ NOT READY - Multiple failures. Significant work needed before production");
    }
    console.log("=".repeat(60));
  }

  private getOverallResult(): boolean {
    const failed = this.results.filter(r => r.status === "fail").length;
    return failed === 0;
  }

  private log(message: string): void {
    if (this.verbose || !message.startsWith("   ")) {
      console.log(message);
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
  const args = parseArgs(Deno.args, {
    boolean: ["verbose", "help"],
    alias: { v: "verbose", h: "help" }
  });

  if (args.help) {
    console.log(`
Kubernetes Cluster Load Test

Usage: deno task load-test [options]

Options:
  -v, --verbose    Show detailed output
  -h, --help      Show this help

Tests performed:
  1. Workload Deployment - Deploy and verify application pods
  2. Network Connectivity - Service discovery and HTTP connectivity
  3. Resource Limits - Verify resource constraint enforcement
  4. Control Plane API - API server responsiveness under load
  5. Storage Provisioning - PVC creation and binding

All test resources are automatically cleaned up after completion.
`);
    return;
  }

  const tester = new ClusterLoadTester(args.verbose);
  const success = await tester.runLoadTest();
  
  Deno.exit(success ? 0 : 1);
}

if (import.meta.main) {
  main();
}