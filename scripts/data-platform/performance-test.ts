#!/usr/bin/env -S deno run --allow-all
/**
 * Data Platform Performance Testing Script
 * 
 * Validates performance across all data platform components:
 * - Trino query latency and throughput
 * - Spark job execution times
 * - S3 storage performance
 * - Resource utilization
 * 
 * Usage:
 *   ./scripts/data-platform/performance-test.ts
 *   ./scripts/data-platform/performance-test.ts --json
 *   ./scripts/data-platform/performance-test.ts --component=trino
 */

import { $ } from "https://deno.land/x/dax@0.39.2/mod.ts";

interface PerformanceResult {
  status: "healthy" | "warning" | "critical" | "error";
  timestamp: string;
  component: string;
  metrics: Record<string, number>;
  issues: string[];
  details?: any;
}

interface TestConfig {
  component?: string;
  jsonOutput: boolean;
  verbose: boolean;
}

const TRINO_ENDPOINT = "http://trino.data-platform.svc.cluster.local:8080";
const NAMESPACE = "data-platform";

// Performance thresholds
const THRESHOLDS = {
  trino: {
    query_latency_max: 30_000,      // 30 seconds max
    concurrent_queries: 5,
    memory_usage_max: 0.85,         // 85% max memory usage
  },
  spark: {
    job_startup_max: 120_000,       // 2 minutes max startup
    executor_memory_max: 0.80,      // 80% max executor memory
  },
  storage: {
    s3_latency_max: 5_000,          // 5 seconds max for large operations
    throughput_min: 100_000_000,    // 100MB/s minimum throughput
  },
  resources: {
    namespace_cpu_max: 0.80,        // 80% of quota
    namespace_memory_max: 0.80,     // 80% of quota
  },
};

async function runTrinoPerformanceTest(): Promise<PerformanceResult> {
  const result: PerformanceResult = {
    status: "healthy",
    timestamp: new Date().toISOString(),
    component: "trino",
    metrics: {},
    issues: [],
  };

  try {
    console.log("🔍 Testing Trino performance...");

    // Test 1: Basic connectivity and health
    const healthStart = Date.now();
    const healthCheck = await $`kubectl exec -n ${NAMESPACE} deployment/trino-coordinator -- \
      curl -s http://localhost:8080/v1/info || echo "FAILED"`.text();
    
    const healthLatency = Date.now() - healthStart;
    result.metrics.health_check_latency = healthLatency;

    if (healthCheck.includes("FAILED")) {
      result.status = "critical";
      result.issues.push("Trino coordinator health check failed");
      return result;
    }

    // Test 2: Simple query performance
    const queryStart = Date.now();
    const simpleQuery = await $`kubectl exec -n ${NAMESPACE} deployment/trino-coordinator -- \
      trino --server localhost:8080 --execute "SELECT COUNT(*) FROM system.runtime.nodes" || echo "QUERY_FAILED"`.text();
    
    const queryLatency = Date.now() - queryStart;
    result.metrics.simple_query_latency = queryLatency;

    if (simpleQuery.includes("QUERY_FAILED")) {
      result.status = "critical";
      result.issues.push("Basic Trino query failed");
      return result;
    }

    if (queryLatency > THRESHOLDS.trino.query_latency_max) {
      result.status = "warning";
      result.issues.push(`Query latency ${queryLatency}ms exceeds threshold ${THRESHOLDS.trino.query_latency_max}ms`);
    }

    // Test 3: Memory usage check
    const memoryUsage = await $`kubectl top pod -n ${NAMESPACE} -l app.kubernetes.io/name=trino --no-headers`.text();
    const coordinatorMem = memoryUsage.split('\n')
      .find(line => line.includes('coordinator'))
      ?.split(/\s+/)[1];

    if (coordinatorMem) {
      result.metrics.coordinator_memory_usage = coordinatorMem;
    }

    // Test 4: Worker availability
    const workerStatus = await $`kubectl get pods -n ${NAMESPACE} -l app.kubernetes.io/name=trino,app.kubernetes.io/component=worker -o json`.json();
    const readyWorkers = workerStatus.items.filter((pod: any) => 
      pod.status.phase === "Running" && 
      pod.status.conditions?.some((c: any) => c.type === "Ready" && c.status === "True")
    ).length;

    result.metrics.ready_workers = readyWorkers;
    
    if (readyWorkers === 0) {
      result.status = "critical";
      result.issues.push("No Trino workers are ready");
    }

    console.log(`✅ Trino test completed: ${result.issues.length} issues found`);

  } catch (error) {
    result.status = "error";
    result.issues.push(`Trino test failed: ${error.message}`);
  }

  return result;
}

async function runSparkPerformanceTest(): Promise<PerformanceResult> {
  const result: PerformanceResult = {
    status: "healthy",
    timestamp: new Date().toISOString(),
    component: "spark",
    metrics: {},
    issues: [],
  };

  try {
    console.log("⚡ Testing Spark performance...");

    // Test 1: Spark Operator health
    const operatorStatus = await $`kubectl get deployment -n ${NAMESPACE} spark-operator-controller -o json`.json();
    const operatorReady = operatorStatus.status.readyReplicas === operatorStatus.status.replicas;
    
    if (!operatorReady) {
      result.status = "critical";
      result.issues.push("Spark Operator is not ready");
      return result;
    }

    // Test 2: Submit a simple test job
    const testJobName = `spark-perf-test-${Date.now()}`;
    const jobManifest = `
apiVersion: sparkoperator.k8s.io/v1beta2
kind: SparkApplication
metadata:
  name: ${testJobName}
  namespace: ${NAMESPACE}
spec:
  type: Scala
  mode: cluster
  image: apache/spark:3.5.5
  imagePullPolicy: IfNotPresent
  mainClass: org.apache.spark.examples.SparkPi
  mainApplicationFile: local:///opt/spark/examples/jars/spark-examples_2.12-3.5.5.jar
  arguments: ["100"]
  sparkVersion: "3.5.5"
  restartPolicy:
    type: Never
  driver:
    cores: 1
    memory: "512m"
    serviceAccount: spark-application-sa
  executor:
    cores: 1
    instances: 1
    memory: "512m"
`;

    // Submit the test job
    const jobStart = Date.now();
    await $`echo ${jobManifest} | kubectl apply -f -`;

    // Wait for job completion or timeout (2 minutes)
    let jobCompleted = false;
    let attempts = 0;
    const maxAttempts = 24; // 2 minutes with 5-second intervals

    while (!jobCompleted && attempts < maxAttempts) {
      await new Promise(resolve => setTimeout(resolve, 5000)); // Wait 5 seconds
      
      const jobStatus = await $`kubectl get sparkapplication ${testJobName} -n ${NAMESPACE} -o jsonpath='{.status.applicationState.state}' || echo "MISSING"`.text();
      
      if (jobStatus.includes("COMPLETED")) {
        jobCompleted = true;
      } else if (jobStatus.includes("FAILED") || jobStatus.includes("ERROR")) {
        result.status = "critical";
        result.issues.push(`Spark test job failed with state: ${jobStatus}`);
        break;
      }
      
      attempts++;
    }

    const jobDuration = Date.now() - jobStart;
    result.metrics.test_job_duration = jobDuration;

    if (!jobCompleted && attempts >= maxAttempts) {
      result.status = "warning";
      result.issues.push(`Spark test job did not complete within ${maxAttempts * 5} seconds`);
    }

    if (jobDuration > THRESHOLDS.spark.job_startup_max) {
      result.status = "warning";
      result.issues.push(`Job duration ${jobDuration}ms exceeds threshold ${THRESHOLDS.spark.job_startup_max}ms`);
    }

    // Cleanup test job
    await $`kubectl delete sparkapplication ${testJobName} -n ${NAMESPACE} --ignore-not-found=true`;

    console.log(`✅ Spark test completed: ${result.issues.length} issues found`);

  } catch (error) {
    result.status = "error";
    result.issues.push(`Spark test failed: ${error.message}`);
  }

  return result;
}

async function runStoragePerformanceTest(): Promise<PerformanceResult> {
  const result: PerformanceResult = {
    status: "healthy",
    timestamp: new Date().toISOString(),
    component: "storage",
    metrics: {},
    issues: [],
  };

  try {
    console.log("💾 Testing S3 storage performance...");

    // Test 1: S3 connectivity through Trino
    const s3TestStart = Date.now();
    const s3Test = await $`kubectl exec -n ${NAMESPACE} deployment/trino-coordinator -- \
      trino --server localhost:8080 --execute "SELECT * FROM system.metadata.table_comments LIMIT 1" || echo "S3_FAILED"`.text();
    
    const s3Latency = Date.now() - s3TestStart;
    result.metrics.s3_connectivity_latency = s3Latency;

    if (s3Test.includes("S3_FAILED")) {
      result.status = "critical";
      result.issues.push("S3 connectivity test failed");
      return result;
    }

    // Test 2: Check Ceph cluster health
    const cephHealth = await $`kubectl exec -n storage deploy/rook-ceph-tools -- ceph health || echo "CEPH_UNAVAILABLE"`.text();
    
    if (cephHealth.includes("HEALTH_OK")) {
      result.metrics.ceph_health = 1;
    } else if (cephHealth.includes("HEALTH_WARN")) {
      result.metrics.ceph_health = 0.5;
      result.status = "warning";
      result.issues.push("Ceph cluster health is in warning state");
    } else {
      result.metrics.ceph_health = 0;
      result.status = "critical";
      result.issues.push("Ceph cluster health is critical or unavailable");
    }

    // Test 3: Check object store gateway
    const rgwStatus = await $`kubectl get pods -n storage -l app=rook-ceph-rgw -o json`.json();
    const rgwReady = rgwStatus.items.filter((pod: any) => 
      pod.status.phase === "Running" && 
      pod.status.conditions?.some((c: any) => c.type === "Ready" && c.status === "True")
    ).length;

    result.metrics.rgw_pods_ready = rgwReady;

    if (rgwReady === 0) {
      result.status = "critical";
      result.issues.push("No RADOS Gateway pods are ready");
    }

    console.log(`✅ Storage test completed: ${result.issues.length} issues found`);

  } catch (error) {
    result.status = "error";
    result.issues.push(`Storage test failed: ${error.message}`);
  }

  return result;
}

async function runResourceUtilizationTest(): Promise<PerformanceResult> {
  const result: PerformanceResult = {
    status: "healthy",
    timestamp: new Date().toISOString(),
    component: "resources",
    metrics: {},
    issues: [],
  };

  try {
    console.log("📊 Testing resource utilization...");

    // Test 1: Namespace resource usage vs quotas
    const quotaData = await $`kubectl get resourcequota -n ${NAMESPACE} -o json`.json();
    
    if (quotaData.items.length > 0) {
      const quota = quotaData.items[0];
      const hard = quota.status.hard;
      const used = quota.status.used;

      // Check memory usage
      if (hard["requests.memory"] && used["requests.memory"]) {
        const memoryUsageRatio = parseMemory(used["requests.memory"]) / parseMemory(hard["requests.memory"]);
        result.metrics.memory_usage_ratio = memoryUsageRatio;

        if (memoryUsageRatio > THRESHOLDS.resources.namespace_memory_max) {
          result.status = "warning";
          result.issues.push(`Memory usage ${(memoryUsageRatio * 100).toFixed(1)}% exceeds threshold ${(THRESHOLDS.resources.namespace_memory_max * 100)}%`);
        }
      }

      // Check CPU usage
      if (hard["requests.cpu"] && used["requests.cpu"]) {
        const cpuUsageRatio = parseCPU(used["requests.cpu"]) / parseCPU(hard["requests.cpu"]);
        result.metrics.cpu_usage_ratio = cpuUsageRatio;

        if (cpuUsageRatio > THRESHOLDS.resources.namespace_cpu_max) {
          result.status = "warning";
          result.issues.push(`CPU usage ${(cpuUsageRatio * 100).toFixed(1)}% exceeds threshold ${(THRESHOLDS.resources.namespace_cpu_max * 100)}%`);
        }
      }
    }

    // Test 2: Pod resource utilization
    const podMetrics = await $`kubectl top pods -n ${NAMESPACE} --no-headers || echo "METRICS_UNAVAILABLE"`.text();
    
    if (!podMetrics.includes("METRICS_UNAVAILABLE")) {
      const pods = podMetrics.trim().split('\n').filter(line => line.trim());
      result.metrics.pod_count = pods.length;

      // Check for high memory usage pods
      const highMemoryPods = pods.filter(line => {
        const parts = line.split(/\s+/);
        if (parts.length >= 3) {
          const memoryStr = parts[2];
          return memoryStr.includes('Gi') && parseFloat(memoryStr) > 20; // > 20Gi
        }
        return false;
      });

      if (highMemoryPods.length > 0) {
        result.status = "warning";
        result.issues.push(`${highMemoryPods.length} pods using >20Gi memory`);
      }
    }

    console.log(`✅ Resource test completed: ${result.issues.length} issues found`);

  } catch (error) {
    result.status = "error";
    result.issues.push(`Resource test failed: ${error.message}`);
  }

  return result;
}

function parseMemory(memStr: string): number {
  const match = memStr.match(/^(\d+(?:\.\d+)?)([KMGT]i?)$/);
  if (!match) return 0;
  
  const value = parseFloat(match[1]);
  const unit = match[2];
  
  const multipliers: Record<string, number> = {
    '': 1,
    'K': 1000, 'Ki': 1024,
    'M': 1000000, 'Mi': 1024 * 1024,
    'G': 1000000000, 'Gi': 1024 * 1024 * 1024,
    'T': 1000000000000, 'Ti': 1024 * 1024 * 1024 * 1024,
  };
  
  return value * (multipliers[unit] || 1);
}

function parseCPU(cpuStr: string): number {
  if (cpuStr.endsWith('m')) {
    return parseFloat(cpuStr.slice(0, -1)) / 1000;
  }
  return parseFloat(cpuStr);
}

function parseArgs(): TestConfig {
  const args = Deno.args;
  const config: TestConfig = {
    jsonOutput: false,
    verbose: false,
  };

  for (const arg of args) {
    if (arg === "--json") {
      config.jsonOutput = true;
    } else if (arg === "--verbose" || arg === "-v") {
      config.verbose = true;
    } else if (arg.startsWith("--component=")) {
      config.component = arg.split("=")[1];
    }
  }

  return config;
}

async function main() {
  const config = parseArgs();
  const results: PerformanceResult[] = [];

  console.log("🚀 Starting data platform performance tests...\n");

  // Run tests based on component filter
  if (!config.component || config.component === "trino") {
    results.push(await runTrinoPerformanceTest());
  }
  
  if (!config.component || config.component === "spark") {
    results.push(await runSparkPerformanceTest());
  }
  
  if (!config.component || config.component === "storage") {
    results.push(await runStoragePerformanceTest());
  }
  
  if (!config.component || config.component === "resources") {
    results.push(await runResourceUtilizationTest());
  }

  // Calculate overall status
  const criticalIssues = results.filter(r => r.status === "critical").length;
  const warningIssues = results.filter(r => r.status === "warning").length;
  const errors = results.filter(r => r.status === "error").length;

  let overallStatus: "healthy" | "warning" | "critical" | "error";
  if (errors > 0) {
    overallStatus = "error";
  } else if (criticalIssues > 0) {
    overallStatus = "critical";
  } else if (warningIssues > 0) {
    overallStatus = "warning";
  } else {
    overallStatus = "healthy";
  }

  const summary = {
    status: overallStatus,
    timestamp: new Date().toISOString(),
    summary: {
      total_components: results.length,
      healthy: results.filter(r => r.status === "healthy").length,
      warnings: warningIssues,
      critical: criticalIssues,
      errors: errors,
    },
    results: results,
    issues: results.flatMap(r => r.issues),
  };

  if (config.jsonOutput) {
    console.log(JSON.stringify(summary, null, 2));
  } else {
    console.log("\n" + "=".repeat(60));
    console.log("📋 PERFORMANCE TEST SUMMARY");
    console.log("=".repeat(60));
    console.log(`🎯 Overall Status: ${getStatusEmoji(overallStatus)} ${overallStatus.toUpperCase()}`);
    console.log(`📊 Components Tested: ${summary.summary.total_components}`);
    console.log(`✅ Healthy: ${summary.summary.healthy}`);
    console.log(`⚠️  Warnings: ${summary.summary.warnings}`);
    console.log(`🚨 Critical: ${summary.summary.critical}`);
    console.log(`❌ Errors: ${summary.summary.errors}`);

    if (summary.issues.length > 0) {
      console.log("\n📝 Issues Found:");
      summary.issues.forEach(issue => console.log(`   • ${issue}`));
    }

    if (config.verbose) {
      console.log("\n📈 Detailed Results:");
      results.forEach(result => {
        console.log(`\n${result.component.toUpperCase()}:`);
        console.log(`  Status: ${getStatusEmoji(result.status)} ${result.status}`);
        console.log(`  Metrics:`);
        Object.entries(result.metrics).forEach(([key, value]) => {
          console.log(`    ${key}: ${value}`);
        });
      });
    }
  }

  // Exit with appropriate code
  const exitCode = overallStatus === "healthy" ? 0 :
                  overallStatus === "warning" ? 1 :
                  overallStatus === "critical" ? 2 : 3;

  Deno.exit(exitCode);
}

function getStatusEmoji(status: string): string {
  switch (status) {
    case "healthy": return "✅";
    case "warning": return "⚠️";
    case "critical": return "🚨";
    case "error": return "❌";
    default: return "❓";
  }
}

if (import.meta.main) {
  main();
}