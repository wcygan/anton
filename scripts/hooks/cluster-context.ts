#!/usr/bin/env deno run --allow-all
/**
 * Cluster Context Hook
 * Quickly injects essential cluster state at session start
 * Optimized for speed - runs in parallel and caches results
 */

import {
  HookLogger,
  HookResult,
  createHookResult,
  exitHook,
  hasOverride,
  runCommand,
} from "./hook-utils.ts";

const logger = new HookLogger("cluster-context");

interface ClusterStatus {
  healthy: boolean;
  nodes: number;
  readyNodes: number;
  fluxReady: boolean;
  criticalWorkloads: string[];
  warnings: string[];
}

async function getQuickClusterStatus(): Promise<ClusterStatus> {
  const status: ClusterStatus = {
    healthy: true,
    nodes: 0,
    readyNodes: 0,
    fluxReady: true,
    criticalWorkloads: [],
    warnings: [],
  };

  try {
    // Run all checks in parallel for speed
    const [nodesResult, fluxResult] = await Promise.all([
      runCommand(["kubectl", "get", "nodes", "-o", "json"]),
      runCommand(["flux", "check", "--silent"]),
    ]);

    // Parse node status
    if (nodesResult.success) {
      try {
        const nodes = JSON.parse(nodesResult.output);
        status.nodes = nodes.items?.length || 0;
        status.readyNodes = nodes.items?.filter((n: any) => 
          n.status?.conditions?.find((c: any) => 
            c.type === "Ready" && c.status === "True"
          )
        ).length || 0;
        
        if (status.readyNodes < status.nodes) {
          status.healthy = false;
          status.warnings.push(`${status.nodes - status.readyNodes} node(s) not ready`);
        }
      } catch {
        // JSON parse failed, skip
      }
    }

    // Check Flux status (silent mode is fast)
    status.fluxReady = fluxResult.success;
    if (!fluxResult.success) {
      status.healthy = false;
      status.warnings.push("Flux components not healthy");
    }

    // Quick check for critical workloads (parallel)
    const criticalNamespaces = ["kube-system", "flux-system", "storage"];
    const podChecks = await Promise.all(
      criticalNamespaces.map(ns => 
        runCommand(["kubectl", "get", "pods", "-n", ns, "--no-headers", "-o", "custom-columns=:metadata.name,:status.phase"])
      )
    );

    podChecks.forEach((result, idx) => {
      if (result.success && result.output.includes("Pending") || result.output.includes("Failed")) {
        status.warnings.push(`Issues in ${criticalNamespaces[idx]} namespace`);
        status.healthy = false;
      }
    });

  } catch (error) {
    logger.error("Failed to get cluster status", error);
    status.warnings.push("Unable to determine cluster status");
  }

  return status;
}

function generateContextMessage(status: ClusterStatus): string {
  const icon = status.healthy ? "✅" : "⚠️";
  
  let context = `\n${icon} CLUSTER CONTEXT:\n`;
  context += `• Nodes: ${status.readyNodes}/${status.nodes} ready\n`;
  context += `• Flux: ${status.fluxReady ? "✅ Healthy" : "❌ Issues detected"}\n`;
  
  if (status.warnings.length > 0) {
    context += `• Warnings:\n`;
    status.warnings.forEach(w => {
      context += `  - ${w}\n`;
    });
  }

  if (!status.healthy) {
    context += `\n⚠️ Cluster has issues - proceed with caution\n`;
  }

  return context;
}

async function getCachedContext(): Promise<string | null> {
  // Check if we have recent context (within 5 minutes)
  const cacheFile = "/tmp/claude-cluster-context.cache";
  const maxAge = 5 * 60 * 1000; // 5 minutes

  try {
    const stat = await Deno.stat(cacheFile);
    const age = Date.now() - stat.mtime!.getTime();
    
    if (age < maxAge) {
      const cached = await Deno.readTextFile(cacheFile);
      logger.info("Using cached cluster context");
      return cached;
    }
  } catch {
    // Cache miss or error
  }

  return null;
}

async function cacheContext(context: string): Promise<void> {
  try {
    await Deno.writeTextFile("/tmp/claude-cluster-context.cache", context);
  } catch {
    // Ignore cache write errors
  }
}

async function main(): Promise<void> {
  // Only run on first prompt of session
  const isFirstPrompt = Deno.env.get("CLAUDE_PROMPT_NUMBER") === "1" || 
                       Deno.env.get("CLAUDE_SESSION_START") === "true";
  
  if (!isFirstPrompt && !Deno.env.get("FORCE_CONTEXT_INJECT")) {
    logger.info("Not first prompt, skipping context injection");
    exitHook(createHookResult(true, "Context already injected", 0));
  }

  // Check for override
  if (hasOverride("SKIP_CLUSTER_CONTEXT")) {
    logger.info("Cluster context injection skipped via override");
    exitHook(createHookResult(true, "Context injection skipped", 0));
  }

  // Try to use cached context for speed
  const cached = await getCachedContext();
  if (cached) {
    console.log(cached);
    exitHook(createHookResult(true, "✅ Cached context injected", 0));
  }

  // Get fresh cluster status (optimized for speed)
  logger.info("Gathering cluster context...");
  const startTime = Date.now();
  
  const status = await getQuickClusterStatus();
  
  const elapsed = Date.now() - startTime;
  logger.info(`Context gathered in ${elapsed}ms`);

  // Generate and cache context
  const context = generateContextMessage(status);
  await cacheContext(context);

  // Output context
  console.log(context);

  if (!status.healthy) {
    exitHook(createHookResult(true, "⚠️ Context injected - cluster has issues", 1, status));
  } else {
    exitHook(createHookResult(true, "✅ Context injected", 0, status));
  }
}

if (import.meta.main) {
  main().catch((error) => {
    const logger = new HookLogger("cluster-context");
    logger.error("Hook execution failed", error);
    // Don't block on context injection failures
    exitHook(createHookResult(true, "Context injection failed (non-blocking)", 0));
  });
}