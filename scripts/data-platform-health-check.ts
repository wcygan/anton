#!/usr/bin/env deno run --allow-all

/**
 * Data Platform Health Check
 * 
 * Monitors the health of data platform components including:
 * - Nessie data catalog
 * - PostgreSQL cluster 
 * - Spark operators and applications
 * - S3 storage connectivity
 */

import { $ } from "https://deno.land/x/dax@0.35.0/mod.ts";
import { parse } from "https://deno.land/std@0.224.0/flags/mod.ts";

interface HealthResult {
  status: "healthy" | "warning" | "critical" | "error";
  timestamp: string;
  summary: {
    total: number;
    healthy: number;
    warnings: number;
    critical: number;
  };
  details: {
    components: ComponentHealth[];
  };
  issues: string[];
}

interface ComponentHealth {
  name: string;
  type: "service" | "database" | "storage" | "operator";
  status: "healthy" | "warning" | "critical";
  details: any;
}

const args = parse(Deno.args, {
  boolean: ["json", "verbose"],
  default: {
    json: false,
    verbose: false,
  },
});

class DataPlatformHealthChecker {
  private results: ComponentHealth[] = [];
  private issues: string[] = [];

  async checkNessieHealth(): Promise<void> {
    try {
      // Check Nessie pod status
      const pods = await $`kubectl get pods -n data-platform -l app.kubernetes.io/name=nessie -o json`.json();
      const nessiePods = pods.items.filter((pod: any) => pod.metadata.name.startsWith('nessie-'));
      
      let healthy = 0;
      const podDetails = [];
      
      for (const pod of nessiePods) {
        const status = pod.status.phase === "Running" ? "healthy" : "critical";
        if (status === "healthy") healthy++;
        
        podDetails.push({
          name: pod.metadata.name,
          status: pod.status.phase,
          ready: pod.status.conditions?.find((c: any) => c.type === "Ready")?.status === "True"
        });
      }

      const overallStatus = healthy === nessiePods.length ? "healthy" : 
                           healthy > 0 ? "warning" : "critical";

      this.results.push({
        name: "Nessie Data Catalog",
        type: "service",
        status: overallStatus,
        details: {
          totalPods: nessiePods.length,
          healthyPods: healthy,
          pods: podDetails
        }
      });

      if (overallStatus !== "healthy") {
        this.issues.push(`❌ Nessie: ${healthy}/${nessiePods.length} pods healthy`);
      }

      // Check Nessie API health
      try {
        const nessieService = await $`kubectl get svc -n data-platform nessie -o json`.json();
        if (nessieService.spec.clusterIP) {
          this.results.push({
            name: "Nessie API Service",
            type: "service", 
            status: "healthy",
            details: {
              clusterIP: nessieService.spec.clusterIP,
              port: nessieService.spec.ports[0].port
            }
          });
        }
      } catch {
        this.results.push({
          name: "Nessie API Service",
          type: "service",
          status: "critical", 
          details: { error: "Service not found" }
        });
        this.issues.push("❌ Nessie API service not accessible");
      }

    } catch (error) {
      this.results.push({
        name: "Nessie Data Catalog",
        type: "service",
        status: "error",
        details: { error: error.message }
      });
      this.issues.push(`❌ Nessie check failed: ${error.message}`);
    }
  }

  async checkPostgreSQLHealth(): Promise<void> {
    try {
      // Check CNPG cluster status
      const cluster = await $`kubectl get cluster -n data-platform nessie-postgres -o json`.json();
      
      const status = cluster.status.phase === "Cluster in healthy state" ? "healthy" : "warning";
      const instances = cluster.status.instances || 0;
      const readyInstances = cluster.status.readyInstances || 0;

      this.results.push({
        name: "PostgreSQL Cluster (CNPG)",
        type: "database",
        status,
        details: {
          phase: cluster.status.phase,
          instances,
          readyInstances,
          currentPrimary: cluster.status.currentPrimary
        }
      });

      if (readyInstances < instances) {
        this.issues.push(`⚠️  PostgreSQL: ${readyInstances}/${instances} instances ready`);
      }

    } catch (error) {
      this.results.push({
        name: "PostgreSQL Cluster (CNPG)",
        type: "database", 
        status: "critical",
        details: { error: error.message }
      });
      this.issues.push(`❌ PostgreSQL cluster check failed: ${error.message}`);
    }
  }

  async checkSparkOperatorHealth(): Promise<void> {
    try {
      // Check Spark operator pods
      const pods = await $`kubectl get pods -n data-platform -l app.kubernetes.io/name=spark-operator -o json`.json();
      const operatorPods = pods.items;

      let healthy = 0;
      const podDetails = [];

      for (const pod of operatorPods) {
        const status = pod.status.phase === "Running" ? "healthy" : "critical";
        if (status === "healthy") healthy++;
        
        podDetails.push({
          name: pod.metadata.name,
          status: pod.status.phase,
          ready: pod.status.conditions?.find((c: any) => c.type === "Ready")?.status === "True"
        });
      }

      const overallStatus = healthy === operatorPods.length ? "healthy" :
                           healthy > 0 ? "warning" : "critical";

      this.results.push({
        name: "Spark Operator",
        type: "operator",
        status: overallStatus,
        details: {
          totalPods: operatorPods.length,
          healthyPods: healthy,
          pods: podDetails
        }
      });

      if (overallStatus !== "healthy") {
        this.issues.push(`❌ Spark Operator: ${healthy}/${operatorPods.length} pods healthy`);
      }

    } catch (error) {
      this.results.push({
        name: "Spark Operator",
        type: "operator",
        status: "error", 
        details: { error: error.message }
      });
      this.issues.push(`❌ Spark operator check failed: ${error.message}`);
    }
  }

  async checkS3StorageHealth(): Promise<void> {
    try {
      // Check if s3-credentials secret exists
      const secret = await $`kubectl get secret -n data-platform s3-credentials -o json`.json();
      
      // Check if iceberg CephObjectStoreUser exists
      const user = await $`kubectl get cephobjectstoreuser -n storage iceberg -o json`.json();
      const userReady = user.status?.phase === "Ready";

      const status = secret && userReady ? "healthy" : "warning";

      this.results.push({
        name: "S3 Storage (Ceph)",
        type: "storage",
        status,
        details: {
          secretExists: !!secret,
          icebergUserReady: userReady,
          userPhase: user.status?.phase,
          secretName: user.status?.info?.secretName
        }
      });

      if (!userReady) {
        this.issues.push("⚠️  Iceberg S3 user not ready");
      }

    } catch (error) {
      this.results.push({
        name: "S3 Storage (Ceph)",
        type: "storage",
        status: "critical",
        details: { error: error.message }
      });
      this.issues.push(`❌ S3 storage check failed: ${error.message}`);
    }
  }

  async checkDataPlatformPods(): Promise<void> {
    try {
      // Get all pods in data-platform namespace
      const pods = await $`kubectl get pods -n data-platform -o json`.json();
      
      const runningPods = pods.items.filter((pod: any) => 
        pod.status.phase === "Running" && 
        !pod.metadata.name.includes("restore-template") // Exclude backup job pods
      );
      
      const totalPods = pods.items.filter((pod: any) => 
        !pod.metadata.name.includes("restore-template")
      ).length;

      const healthyPods = runningPods.length;
      const healthPercentage = totalPods > 0 ? (healthyPods / totalPods) * 100 : 0;

      const status = healthPercentage >= 80 ? "healthy" : 
                    healthPercentage >= 60 ? "warning" : "critical";

      this.results.push({
        name: "Data Platform Pods",
        type: "service",
        status,
        details: {
          totalPods,
          healthyPods,
          healthPercentage: Math.round(healthPercentage),
          runningPods: runningPods.map((pod: any) => ({
            name: pod.metadata.name,
            status: pod.status.phase,
            age: pod.metadata.creationTimestamp
          }))
        }
      });

      if (status !== "healthy") {
        this.issues.push(`⚠️  Data Platform: ${healthyPods}/${totalPods} pods healthy (${Math.round(healthPercentage)}%)`);
      }

    } catch (error) {
      this.results.push({
        name: "Data Platform Pods",
        type: "service",
        status: "error",
        details: { error: error.message }
      });
      this.issues.push(`❌ Pod health check failed: ${error.message}`);
    }
  }

  async runAllChecks(): Promise<HealthResult> {
    if (args.verbose) {
      console.log("🔍 Running data platform health checks...");
    }

    await Promise.all([
      this.checkNessieHealth(),
      this.checkPostgreSQLHealth(), 
      this.checkSparkOperatorHealth(),
      this.checkS3StorageHealth(),
      this.checkDataPlatformPods()
    ]);

    const summary = {
      total: this.results.length,
      healthy: this.results.filter(r => r.status === "healthy").length,
      warnings: this.results.filter(r => r.status === "warning").length,
      critical: this.results.filter(r => r.status === "critical").length + 
                this.results.filter(r => r.status === "error").length
    };

    const overallStatus = summary.critical > 0 ? "critical" :
                         summary.warnings > 0 ? "warning" : "healthy";

    return {
      status: overallStatus,
      timestamp: new Date().toISOString(),
      summary,
      details: {
        components: this.results
      },
      issues: this.issues
    };
  }
}

// Main execution
if (import.meta.main) {
  try {
    const checker = new DataPlatformHealthChecker();
    const result = await checker.runAllChecks();

    if (args.json) {
      console.log(JSON.stringify(result, null, 2));
    } else {
      // Human-readable output
      console.log("🔍 Data Platform Health Check");
      console.log("=" .repeat(50));
      console.log(`Overall Status: ${result.status.toUpperCase()}`);
      console.log(`Timestamp: ${result.timestamp}`);
      console.log(`\nSummary: ${result.summary.healthy}/${result.summary.total} components healthy`);
      
      if (args.verbose || result.issues.length > 0) {
        console.log("\nComponent Details:");
        for (const component of result.details.components) {
          const statusIcon = component.status === "healthy" ? "✅" : 
                            component.status === "warning" ? "⚠️" : "❌";
          console.log(`${statusIcon} ${component.name} (${component.type}): ${component.status}`);
          
          if (args.verbose) {
            console.log(`   ${JSON.stringify(component.details, null, 2)}`);
          }
        }
      }

      if (result.issues.length > 0) {
        console.log("\nIssues Found:");
        result.issues.forEach(issue => console.log(`  ${issue}`));
      }

      console.log(`\n${result.status === "healthy" ? "✅" : "❌"} Data platform health check ${result.status === "healthy" ? "PASSED" : "FAILED"}`);
    }

    // Exit codes: 0 = healthy, 1 = warnings, 2 = critical
    const exitCode = result.status === "healthy" ? 0 : 
                    result.status === "warning" ? 1 : 2;
    Deno.exit(exitCode);

  } catch (error) {
    if (args.json) {
      console.log(JSON.stringify({
        status: "error",
        timestamp: new Date().toISOString(), 
        error: error.message
      }));
    } else {
      console.error(`❌ Health check failed: ${error.message}`);
    }
    Deno.exit(3);
  }
}