#!/usr/bin/env -S deno run --allow-all

import { parseArgs } from "@std/cli/parse-args";
import { delay } from "@std/async/delay";
import { MonitoringResult, ExitCode } from "./types/monitoring.ts";

interface HealthCheckOptions {
  verbose: boolean;
  namespace?: string;
  continuous: boolean;
  interval: number;
  help: boolean;
  includeFlux: boolean;
  json: boolean;
}

interface NodeInfo {
  name: string;
  status: string;
  version: string;
  osImage: string;
  internalIP: string;
  roles: string[];
  ready: boolean;
  conditions: Array<
    { type: string; status: string; reason?: string; message?: string }
  >;
}

interface PodInfo {
  name: string;
  namespace: string;
  status: string;
  ready: string;
  restarts: number;
  age: string;
  node?: string;
  healthy: boolean;
}

interface FluxComponentInfo {
  name: string;
  namespace: string;
  ready: boolean;
  status: string;
  version?: string;
  conditions: Array<
    { type: string; status: string; reason?: string; message?: string }
  >;
}

interface NamespaceInfo {
  name: string;
  hasFluxResources: boolean;
  podCount: number;
  healthyPods: number;
}

class KubernetesHealthChecker {
  private verbose: boolean;
  private includeFlux: boolean;
  private jsonOutput: boolean;
  private issues: string[] = [];
  private healthSummary = {
    total: 0,
    healthy: 0,
    warnings: 0,
    critical: 0
  };

  constructor(verbose = false, includeFlux = true, jsonOutput = false) {
    this.verbose = verbose;
    this.includeFlux = includeFlux;
    this.jsonOutput = jsonOutput;
  }

  private async runKubectl(
    args: string[],
  ): Promise<{ success: boolean; output: string; error?: string }> {
    try {
      const command = new Deno.Command("kubectl", {
        args,
        stdout: "piped",
        stderr: "piped",
      });

      const result = await command.output();
      const stdout = new TextDecoder().decode(result.stdout);
      const stderr = new TextDecoder().decode(result.stderr);

      return {
        success: result.success,
        output: stdout.trim(),
        error: stderr.trim() || undefined,
      };
    } catch (error) {
      const errorMessage = error instanceof Error
        ? error.message
        : String(error);
      return {
        success: false,
        output: "",
        error: `Failed to run kubectl: ${errorMessage}`,
      };
    }
  }

  private async runFlux(
    args: string[],
  ): Promise<{ success: boolean; output: string; error?: string }> {
    try {
      const command = new Deno.Command("flux", {
        args,
        stdout: "piped",
        stderr: "piped",
      });

      const result = await command.output();
      const stdout = new TextDecoder().decode(result.stdout);
      const stderr = new TextDecoder().decode(result.stderr);

      return {
        success: result.success,
        output: stdout.trim(),
        error: stderr.trim() || undefined,
      };
    } catch (error) {
      const errorMessage = error instanceof Error
        ? error.message
        : String(error);
      return {
        success: false,
        output: "",
        error: `Failed to run flux: ${errorMessage}`,
      };
    }
  }

  private log(
    message: string,
    level: "INFO" | "WARN" | "ERROR" = "INFO",
  ): void {
    if (this.jsonOutput) {
      // In JSON mode, collect issues
      if (level === "ERROR") {
        this.issues.push(message);
      } else if (level === "WARN" && message.includes("⚠️")) {
        this.issues.push(message);
      }
    } else {
      const timestamp = new Date().toISOString();
      const prefix = level === "ERROR" ? "❌" : level === "WARN" ? "⚠️ " : "ℹ️ ";
      console.log(`[${timestamp}] ${prefix} ${message}`);
    }
  }

  private verboseLog(message: string): void {
    if (this.verbose && !this.jsonOutput) {
      this.log(message);
    }
  }

  async checkClusterAccess(): Promise<boolean> {
    this.verboseLog("Checking cluster access...");

    const result = await this.runKubectl(["cluster-info"]);
    if (!result.success) {
      this.log(`Failed to access cluster: ${result.error}`, "ERROR");
      return false;
    }

    this.verboseLog("✅ Cluster access verified");
    return true;
  }

  async getNodes(): Promise<NodeInfo[]> {
    this.verboseLog("Fetching node information...");

    const result = await this.runKubectl(["get", "nodes", "-o", "json"]);
    if (!result.success) {
      throw new Error(`Failed to get nodes: ${result.error}`);
    }

    const data = JSON.parse(result.output);
    const nodes: NodeInfo[] = [];

    for (const node of data.items || []) {
      const conditions = node.status?.conditions || [];
      const readyCondition = conditions.find((c: any) => c.type === "Ready");
      const roles = Object.keys(node.metadata?.labels || {})
        .filter((label) => label.startsWith("node-role.kubernetes.io/"))
        .map((label) => label.replace("node-role.kubernetes.io/", ""));

      nodes.push({
        name: node.metadata?.name || "unknown",
        status: node.status?.phase || "unknown",
        version: node.status?.nodeInfo?.kubeletVersion || "unknown",
        osImage: node.status?.nodeInfo?.osImage || "unknown",
        internalIP: node.status?.addresses?.find((a: any) =>
          a.type === "InternalIP"
        )?.address || "unknown",
        roles: roles.length > 0 ? roles : ["worker"],
        ready: readyCondition?.status === "True",
        conditions: conditions.map((c: any) => ({
          type: c.type,
          status: c.status,
          reason: c.reason,
          message: c.message,
        })),
      });
    }

    return nodes;
  }

  async getNamespacesWithFluxResources(): Promise<NamespaceInfo[]> {
    this.verboseLog("Discovering namespaces with Flux resources...");

    // Get all namespaces
    const nsResult = await this.runKubectl(["get", "namespaces", "-o", "json"]);
    if (!nsResult.success) {
      throw new Error(`Failed to get namespaces: ${nsResult.error}`);
    }

    const nsData = JSON.parse(nsResult.output);
    const namespaces: NamespaceInfo[] = [];

    // Check for Flux resources in each namespace
    for (const ns of nsData.items || []) {
      const namespaceName = ns.metadata?.name || "unknown";

      // Skip system namespaces that typically don't have user workloads
      if (
        namespaceName.startsWith("kube-") && namespaceName !== "kube-system"
      ) {
        continue;
      }

      let hasFluxResources = false;
      let podCount = 0;
      let healthyPods = 0;

      // Check for Flux resources (Kustomizations and HelmReleases)
      if (this.includeFlux) {
        const fluxCheck = await this.runKubectl([
          "get",
          "kustomizations.kustomize.toolkit.fluxcd.io,helmreleases.helm.toolkit.fluxcd.io",
          "-n",
          namespaceName,
          "--no-headers",
          "--ignore-not-found",
        ]);

        if (fluxCheck.success && fluxCheck.output.trim()) {
          hasFluxResources = true;
        }
      }

      // Get pod count and health for this namespace
      const podResult = await this.runKubectl([
        "get",
        "pods",
        "-n",
        namespaceName,
        "-o",
        "json",
      ]);
      if (podResult.success) {
        const podData = JSON.parse(podResult.output);
        podCount = podData.items?.length || 0;

        for (const pod of podData.items || []) {
          const containerStatuses = pod.status?.containerStatuses || [];
          const readyCount = containerStatuses.filter((c: any) =>
            c.ready
          ).length;
          const totalCount = containerStatuses.length;
          const isHealthy = pod.status?.phase === "Running" ||
            pod.status?.phase === "Succeeded";

          if (isHealthy && readyCount === totalCount) {
            healthyPods++;
          }
        }
      }

      // Include namespace if it has pods or Flux resources, or is a critical system namespace
      const criticalNamespaces = [
        "kube-system",
        "flux-system",
        "cert-manager",
        "external-secrets",
        "network",
        "monitoring",
      ];
      if (
        podCount > 0 || hasFluxResources ||
        criticalNamespaces.includes(namespaceName)
      ) {
        namespaces.push({
          name: namespaceName,
          hasFluxResources,
          podCount,
          healthyPods,
        });
      }
    }

    return namespaces;
  }

  async getPods(namespace?: string): Promise<PodInfo[]> {
    this.verboseLog(
      `Fetching pod information${
        namespace ? ` for namespace: ${namespace}` : ""
      }...`,
    );

    const args = ["get", "pods", "-o", "json"];
    if (namespace) {
      args.push("-n", namespace);
    } else {
      args.push("--all-namespaces");
    }

    const result = await this.runKubectl(args);
    if (!result.success) {
      throw new Error(`Failed to get pods: ${result.error}`);
    }

    const data = JSON.parse(result.output);
    const pods: PodInfo[] = [];

    for (const pod of data.items || []) {
      const containerStatuses = pod.status?.containerStatuses || [];
      const readyCount = containerStatuses.filter((c: any) => c.ready).length;
      const totalCount = containerStatuses.length;
      const restarts = containerStatuses.reduce(
        (sum: number, c: any) => sum + (c.restartCount || 0),
        0,
      );

      const isHealthy = pod.status?.phase === "Running" ||
        pod.status?.phase === "Succeeded";

      pods.push({
        name: pod.metadata?.name || "unknown",
        namespace: pod.metadata?.namespace || "default",
        status: pod.status?.phase || "unknown",
        ready: `${readyCount}/${totalCount}`,
        restarts,
        age: this.calculateAge(pod.metadata?.creationTimestamp),
        node: pod.spec?.nodeName,
        healthy: isHealthy && readyCount === totalCount,
      });
    }

    return pods;
  }

  async getFluxComponents(): Promise<FluxComponentInfo[]> {
    this.verboseLog("Checking Flux component health...");

    const components: FluxComponentInfo[] = [];

    // Check Flux system pods
    const result = await this.runKubectl([
      "get",
      "pods",
      "-n",
      "flux-system",
      "-o",
      "json",
    ]);

    if (!result.success) {
      this.log(`Failed to get Flux components: ${result.error}`, "WARN");
      return components;
    }

    const data = JSON.parse(result.output);

    for (const pod of data.items || []) {
      const containerStatuses = pod.status?.containerStatuses || [];
      const readyCount = containerStatuses.filter((c: any) => c.ready).length;
      const totalCount = containerStatuses.length;
      const isReady = pod.status?.phase === "Running" &&
        readyCount === totalCount;

      // Extract version from image tag if available
      const version = containerStatuses[0]?.image?.split(":")[1] || "unknown";

      components.push({
        name: pod.metadata?.name || "unknown",
        namespace: pod.metadata?.namespace || "flux-system",
        ready: isReady,
        status: pod.status?.phase || "unknown",
        version,
        conditions: pod.status?.conditions?.map((c: any) => ({
          type: c.type,
          status: c.status,
          reason: c.reason,
          message: c.message,
        })) || [],
      });
    }

    return components;
  }

  private calculateAge(creationTimestamp?: string): string {
    if (!creationTimestamp) return "unknown";

    const created = new Date(creationTimestamp);
    const now = new Date();
    const diffMs = now.getTime() - created.getTime();

    const days = Math.floor(diffMs / (1000 * 60 * 60 * 24));
    const hours = Math.floor(
      (diffMs % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60),
    );
    const minutes = Math.floor((diffMs % (1000 * 60 * 60)) / (1000 * 60));

    if (days > 0) return `${days}d${hours}h`;
    if (hours > 0) return `${hours}h${minutes}m`;
    return `${minutes}m`;
  }

  private convertAgeToDays(ageString: string): number {
    if (ageString === "unknown") return 0;
    
    // Parse age string like "25d4h", "4h30m", "45m"
    const dayMatch = ageString.match(/(\d+)d/);
    const hourMatch = ageString.match(/(\d+)h/);
    const minuteMatch = ageString.match(/(\d+)m/);
    
    let totalDays = 0;
    if (dayMatch) totalDays += parseInt(dayMatch[1]);
    if (hourMatch) totalDays += parseInt(hourMatch[1]) / 24;
    if (minuteMatch) totalDays += parseInt(minuteMatch[1]) / (24 * 60);
    
    return totalDays;
  }

  async checkNodeHealth(): Promise<boolean> {
    this.log("🔍 Checking node health...");

    const nodes = await this.getNodes();
    let allHealthy = true;

    for (const node of nodes) {
      const rolesStr = node.roles.join(", ");

      if (node.ready) {
        this.log(`✅ Node ${node.name} (${rolesStr}): Ready - ${node.version}`);

        if (this.verbose) {
          this.verboseLog(`   Internal IP: ${node.internalIP}`);
          this.verboseLog(`   OS: ${node.osImage}`);
        }
      } else {
        this.log(`❌ Node ${node.name} (${rolesStr}): Not Ready`, "ERROR");
        allHealthy = false;

        // Show problematic conditions
        const problemConditions = node.conditions.filter((c) =>
          c.type !== "Ready" && c.status === "True"
        );

        for (const condition of problemConditions) {
          this.log(
            `   Problem: ${condition.type} - ${condition.reason}: ${condition.message}`,
            "WARN",
          );
        }
      }
    }

    this.log(
      `📊 Node Summary: ${
        nodes.filter((n) => n.ready).length
      }/${nodes.length} nodes ready`,
    );
    
    // Update health summary for JSON output
    this.healthSummary.total += nodes.length;
    this.healthSummary.healthy += nodes.filter((n) => n.ready).length;
    this.healthSummary.critical += nodes.filter((n) => !n.ready).length;
    
    return allHealthy;
  }

  async checkFluxHealth(): Promise<boolean> {
    if (!this.includeFlux) return true;

    this.log("🔄 Checking Flux system health...");

    // First check if Flux is installed
    const fluxCheck = await this.runFlux(["check"]);
    if (!fluxCheck.success) {
      this.log("❌ Flux system check failed", "ERROR");
      this.log(`   ${fluxCheck.error}`, "WARN");
      return false;
    }

    // Check Flux components
    const components = await this.getFluxComponents();
    let allHealthy = true;

    const fluxControllers = components.filter((c) =>
      c.name.includes("controller") || c.name.includes("operator")
    );

    if (fluxControllers.length === 0) {
      this.log("⚠️  No Flux controllers found", "WARN");
      return false;
    }

    for (const component of fluxControllers) {
      if (component.ready) {
        this.log(`✅ Flux ${component.name}: Ready`);
        if (this.verbose && component.version !== "unknown") {
          this.verboseLog(`   Version: ${component.version}`);
        }
      } else {
        this.log(`❌ Flux ${component.name}: ${component.status}`, "ERROR");
        allHealthy = false;

        // Show error conditions
        const errorConditions = component.conditions.filter((c) =>
          c.status === "False" && c.message
        );

        for (const condition of errorConditions) {
          this.log(
            `   ${condition.type}: ${condition.reason} - ${condition.message}`,
            "WARN",
          );
        }
      }
    }

    this.log(
      `📊 Flux Summary: ${
        fluxControllers.filter((c) => c.ready).length
      }/${fluxControllers.length} controllers ready`,
    );
    
    // Update health summary for JSON output
    this.healthSummary.total += fluxControllers.length;
    this.healthSummary.healthy += fluxControllers.filter((c) => c.ready).length;
    this.healthSummary.critical += fluxControllers.filter((c) => !c.ready).length;
    
    return allHealthy;
  }

  async checkNamespaceHealth(): Promise<boolean> {
    this.log("🔍 Checking namespace and pod health...");

    const namespaces = await this.getNamespacesWithFluxResources();
    let allHealthy = true;

    for (const namespace of namespaces) {
      if (namespace.podCount === 0) {
        this.verboseLog(`📦 Namespace ${namespace.name}: No pods`);
        continue;
      }

      const healthPercentage = Math.round(
        (namespace.healthyPods / namespace.podCount) * 100,
      );

      if (namespace.healthyPods === namespace.podCount) {
        this.log(
          `✅ Namespace ${namespace.name}: All ${namespace.podCount} pods healthy`,
        );
        if (this.verbose && namespace.hasFluxResources) {
          this.verboseLog(`   Has Flux resources`);
        }
      } else {
        this.log(
          `❌ Namespace ${namespace.name}: ${namespace.healthyPods}/${namespace.podCount} pods healthy (${healthPercentage}%)`,
          "ERROR",
        );
        allHealthy = false;

        // Get detailed pod information for failed namespace
        if (this.verbose) {
          try {
            const pods = await this.getPods(namespace.name);
            const unhealthyPods = pods.filter((pod) => !pod.healthy);

            for (const pod of unhealthyPods.slice(0, 5)) { // Limit to first 5 unhealthy pods
              this.log(
                `   ${pod.name}: ${pod.status} (${pod.ready}) - ${pod.restarts} restarts`,
                "WARN",
              );
            }

            if (unhealthyPods.length > 5) {
              this.log(
                `   ... and ${unhealthyPods.length - 5} more unhealthy pods`,
                "WARN",
              );
            }
          } catch (error) {
            this.verboseLog(`   Failed to get detailed pod info: ${error}`);
          }
        }
      }

      // Check for high restart counts with time-based analysis
      try {
        const pods = await this.getPods(namespace.name);
        const concerningPods: Array<{ pod: PodInfo; rate: number; age: number }> = [];

        for (const pod of pods) {
          if (pod.restarts > 0) {
            // Calculate pod age in days from the age string
            const ageInDays = this.convertAgeToDays(pod.age);
            const restartRate = pod.restarts / Math.max(ageInDays, 0.1);
            
            // Determine if restart count is concerning based on context
            const isHighRate = restartRate > 5; // More than 5 restarts per day
            const isNewPodWithRestarts = ageInDays < 1 && pod.restarts > 3;
            const isOldPodWithHighRate = ageInDays > 7 && restartRate > 1;
            
            if (isHighRate || isNewPodWithRestarts || isOldPodWithHighRate) {
              concerningPods.push({ pod, rate: restartRate, age: ageInDays });
            }
          }
        }

        if (concerningPods.length > 0) {
          this.log(`⚠️  Concerning restart patterns in ${namespace.name}:`, "WARN");
          
          // Sort by restart rate to show worst offenders first
          concerningPods.sort((a, b) => b.rate - a.rate);
          
          for (const { pod, rate, age } of concerningPods.slice(0, 3)) { // Limit to first 3
            if (age < 1) {
              this.log(`   ${pod.name}: ${pod.restarts} restarts in <1 day (new pod)`, "WARN");
            } else {
              this.log(`   ${pod.name}: ${pod.restarts} restarts (${rate.toFixed(1)}/day over ${age.toFixed(0)}d)`, "WARN");
            }
          }
          
          if (concerningPods.length > 3) {
            this.log(`   ... and ${concerningPods.length - 3} more pods with concerning restart patterns`, "WARN");
          }
        }
      } catch (error) {
        this.verboseLog(
          `Failed to check restart counts for ${namespace.name}: ${error}`,
        );
      }
    }

    const totalPods = namespaces.reduce((sum, ns) => sum + ns.podCount, 0);
    const totalHealthy = namespaces.reduce(
      (sum, ns) => sum + ns.healthyPods,
      0,
    );

    this.log(
      `📊 Overall Pod Summary: ${totalHealthy}/${totalPods} pods healthy across ${namespaces.length} namespaces`,
    );
    
    // Update health summary for JSON output
    this.healthSummary.total += namespaces.length;
    this.healthSummary.healthy += namespaces.filter(ns => ns.healthyPods === ns.podCount && ns.podCount > 0).length;
    this.healthSummary.warnings += namespaces.filter(ns => ns.healthyPods < ns.podCount && ns.healthyPods > 0).length;
    this.healthSummary.critical += namespaces.filter(ns => ns.healthyPods === 0 && ns.podCount > 0).length;
    
    return allHealthy;
  }

  getJsonResult(overallHealthy: boolean): MonitoringResult {
    const status: MonitoringResult["status"] = 
      this.healthSummary.critical > 0 ? "critical" :
      this.healthSummary.warnings > 0 ? "warning" :
      overallHealthy ? "healthy" : "error";

    return {
      status,
      timestamp: new Date().toISOString(),
      summary: this.healthSummary,
      details: {
        includeFlux: this.includeFlux,
        checks: {
          nodes: this.healthSummary.total > 0,
          flux: this.includeFlux,
          namespaces: true,
          storage: true,
          networking: true
        }
      },
      issues: this.issues
    };
  }

  async checkStorageClasses(): Promise<void> {
    this.verboseLog("Checking storage classes...");

    const result = await this.runKubectl(["get", "storageclass", "-o", "json"]);
    if (!result.success) {
      this.log(`⚠️  Could not check storage classes: ${result.error}`, "WARN");
      return;
    }

    const data = JSON.parse(result.output);
    const storageClasses = data.items || [];
    const defaultSC = storageClasses.find((sc: any) =>
      sc.metadata?.annotations
        ?.["storageclass.kubernetes.io/is-default-class"] === "true"
    );

    if (defaultSC) {
      this.verboseLog(`✅ Default storage class: ${defaultSC.metadata?.name}`);
    } else {
      this.log("⚠️  No default storage class found", "WARN");
    }

    this.verboseLog(`📊 Total storage classes: ${storageClasses.length}`);
  }

  async checkNetworking(): Promise<void> {
    this.verboseLog("Checking networking components...");

    // Check for common networking components
    const networkingComponents = [
      {
        name: "CoreDNS",
        namespace: "kube-system",
        selector: "k8s-app=kube-dns",
      },
      {
        name: "CNI (Cilium)",
        namespace: "kube-system",
        selector: "k8s-app=cilium",
      },
      { name: "Ingress Controllers", namespace: "network", selector: "" },
    ];

    for (const component of networkingComponents) {
      try {
        const args = ["get", "pods", "-n", component.namespace];
        if (component.selector) {
          args.push("-l", component.selector);
        }
        args.push("--no-headers");

        const result = await this.runKubectl(args);
        if (result.success && result.output.trim()) {
          const lines = result.output.trim().split("\n");
          const runningPods = lines.filter((line) =>
            line.includes("Running")
          ).length;
          this.verboseLog(
            `✅ ${component.name}: ${runningPods}/${lines.length} pods running`,
          );
        } else {
          this.verboseLog(`⚠️  ${component.name}: No pods found`);
        }
      } catch (error) {
        this.verboseLog(`⚠️  Failed to check ${component.name}: ${error}`);
      }
    }
  }

  async performFullHealthCheck(): Promise<boolean> {
    // Reset counters for JSON output
    this.issues = [];
    this.healthSummary = {
      total: 0,
      healthy: 0,
      warnings: 0,
      critical: 0
    };

    this.log("🚀 Starting comprehensive cluster health check...");

    // Check cluster access first
    if (!(await this.checkClusterAccess())) {
      this.healthSummary.critical++;
      this.healthSummary.total++;
      return false;
    }

    let overallHealthy = true;

    // Check nodes
    const nodesHealthy = await this.checkNodeHealth();
    if (!nodesHealthy) {
      overallHealthy = false;
    }

    // Check Flux system health
    if (this.includeFlux) {
      const fluxHealthy = await this.checkFluxHealth();
      if (!fluxHealthy) {
        overallHealthy = false;
      }
    }

    // Check namespace and pod health
    const namespacesHealthy = await this.checkNamespaceHealth();
    if (!namespacesHealthy) {
      overallHealthy = false;
    }

    // Check storage and networking (informational)
    await this.checkStorageClasses();
    await this.checkNetworking();

    // Final summary
    if (overallHealthy) {
      this.log("🎉 Cluster health check PASSED - All systems operational!");
    } else {
      this.log("⚠️  Cluster health check FAILED - Issues detected", "ERROR");
      this.log(
        "💡 Consider checking individual component logs for more details",
        "INFO",
      );

      if (this.includeFlux) {
        this.log("💡 Run 'flux get all -A' for detailed Flux status", "INFO");
      }
    }

    return overallHealthy;
  }
}

function showHelp(): void {
  console.log(`
🏥 Kubernetes Cluster Health Checker (Optimized)

Usage: deno run --allow-all k8s-health-check.ts [options]

Options:
  -v, --verbose         Verbose output with detailed information
  -n, --namespace <ns>  Check pods in specific namespace only
  -c, --continuous      Run continuously (use with --interval)
  -i, --interval <sec>  Interval between checks in seconds (default: 30)
  --no-flux            Skip Flux-specific health checks
  --json               Output results in JSON format
  -h, --help           Show this help message

Examples:
  deno run --allow-all k8s-health-check.ts                    # Basic health check with Flux
  deno run --allow-all k8s-health-check.ts --verbose          # Detailed output
  deno run --allow-all k8s-health-check.ts --no-flux          # Skip Flux checks
  deno run --allow-all k8s-health-check.ts -n flux-system     # Check only flux-system
  deno run --allow-all k8s-health-check.ts -c -i 60           # Monitor every 60 seconds

Key Improvements:
  ✅ Dynamic namespace discovery based on Flux resources
  ✅ Integrated Flux component health checking
  ✅ Better pod health criteria and error reporting
  ✅ Networking and storage component checks
  ✅ Comprehensive health scoring and recommendations
  ✅ Optimized for GitOps environments
  `);
}

async function main(): Promise<void> {
  const parsedArgs = parseArgs(Deno.args, {
    string: ["namespace", "interval"],
    boolean: ["verbose", "continuous", "help", "no-flux", "json"],
    alias: {
      v: "verbose",
      n: "namespace",
      c: "continuous",
      i: "interval",
      h: "help",
    },
    default: {
      verbose: false,
      continuous: false,
      "no-flux": false,
      json: false,
      interval: "30",
    },
  });

  const args = {
    verbose: Boolean(parsedArgs.verbose),
    namespace: parsedArgs.namespace as string | undefined,
    continuous: Boolean(parsedArgs.continuous),
    help: Boolean(parsedArgs.help),
    includeFlux: !Boolean(parsedArgs["no-flux"]),
    json: Boolean(parsedArgs.json),
    interval: String(parsedArgs.interval || "30"),
  };

  if (args.help) {
    showHelp();
    return;
  }

  const interval = parseInt(args.interval) * 1000; // Convert to milliseconds
  const checker = new KubernetesHealthChecker(args.verbose, args.includeFlux, args.json);

  try {
    if (args.continuous && args.json) {
      console.error("JSON output is not supported with continuous monitoring");
      Deno.exit(ExitCode.ERROR);
    }

    if (args.continuous) {
      console.log(
        `🔄 Starting continuous monitoring (interval: ${args.interval}s, Ctrl+C to stop)...`,
      );

      while (true) {
        const healthy = await checker.performFullHealthCheck();

        if (!healthy) {
          console.log("⏳ Waiting before next check due to issues...");
        }

        await delay(interval);
        console.log("\n" + "=".repeat(80) + "\n");
      }
    } else {
      const healthy = await checker.performFullHealthCheck();
      
      if (args.json) {
        const result = checker.getJsonResult(healthy);
        console.log(JSON.stringify(result, null, 2));
        
        // Exit with appropriate code
        switch (result.status) {
          case "healthy":
            Deno.exit(ExitCode.SUCCESS);
            break;
          case "warning":
            Deno.exit(ExitCode.WARNING);
            break;
          case "critical":
            Deno.exit(ExitCode.CRITICAL);
            break;
          case "error":
            Deno.exit(ExitCode.ERROR);
            break;
        }
      } else {
        Deno.exit(healthy ? ExitCode.SUCCESS : ExitCode.CRITICAL);
      }
    }
  } catch (error) {
    if (args.json) {
      const result: MonitoringResult = {
        status: "error",
        timestamp: new Date().toISOString(),
        summary: {
          total: 0,
          healthy: 0,
          warnings: 0,
          critical: 0,
        },
        details: {},
        issues: [`Health check failed: ${error instanceof Error ? error.message : String(error)}`],
      };
      console.log(JSON.stringify(result, null, 2));
      Deno.exit(ExitCode.ERROR);
    } else {
      const errorMessage = error instanceof Error ? error.message : String(error);
      console.error(`❌ Health check failed: ${errorMessage}`);
      Deno.exit(ExitCode.ERROR);
    }
  }
}

if (import.meta.main) {
  await main();
}
