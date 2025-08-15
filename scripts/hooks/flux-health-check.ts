#!/usr/bin/env deno run --allow-all
/**
 * Flux Health Check Hook
 * Quickly monitors Flux deployment health after reconciliation
 * Runs after flux reconcile commands to ensure successful deployment
 */

import {
  HookLogger,
  HookResult,
  createHookResult,
  exitHook,
  hasOverride,
  runCommand,
} from "./hook-utils.ts";

const logger = new HookLogger("flux-health-check");

interface FluxResourceStatus {
  ready: boolean;
  type: string;
  name: string;
  namespace: string;
  message?: string;
}

async function quickFluxCheck(): Promise<{ healthy: boolean; issues: string[] }> {
  const issues: string[] = [];
  
  try {
    // Quick check - just get failing resources
    const result = await runCommand([
      "flux", "get", "all", "-A", 
      "--status-selector", "ready=false",
      "--no-header"
    ]);

    if (result.output && result.output.trim()) {
      // Parse failed resources
      const lines = result.output.trim().split('\n');
      lines.forEach(line => {
        if (line.includes("False") || line.includes("Unknown")) {
          const parts = line.split(/\s+/);
          if (parts.length >= 3) {
            issues.push(`${parts[1]}/${parts[2]} not ready`);
          }
        }
      });
    }

    return { healthy: issues.length === 0, issues };
  } catch (error) {
    logger.error("Failed to check Flux status", error);
    return { healthy: false, issues: ["Unable to check Flux status"] };
  }
}

async function getRecentReconciliations(): Promise<string[]> {
  const reconciliations: string[] = [];
  
  try {
    // Get recent Flux events (last 2 minutes)
    const result = await runCommand([
      "kubectl", "get", "events",
      "-n", "flux-system",
      "--field-selector", "reason=ReconciliationSucceeded",
      "--no-headers",
      "-o", "custom-columns=:message"
    ]);

    if (result.success && result.output) {
      const lines = result.output.trim().split('\n').slice(0, 3); // Last 3 reconciliations
      reconciliations.push(...lines.filter(l => l.length > 0));
    }
  } catch {
    // Ignore errors - this is supplementary info
  }

  return reconciliations;
}

async function suggestRollback(issues: string[]): Promise<string[]> {
  const suggestions: string[] = [];

  for (const issue of issues.slice(0, 3)) { // Limit to first 3 issues
    if (issue.includes("helmrelease")) {
      const parts = issue.split('/');
      if (parts.length >= 2) {
        const name = parts[1].split(' ')[0];
        suggestions.push(`flux suspend hr ${name} && flux resume hr ${name}`);
      }
    } else if (issue.includes("kustomization")) {
      const parts = issue.split('/');
      if (parts.length >= 2) {
        const name = parts[1].split(' ')[0];
        suggestions.push(`flux suspend ks ${name} && flux resume ks ${name}`);
      }
    }
  }

  return suggestions;
}

async function main(): Promise<void> {
  // Check if this is triggered after a flux reconcile command
  const lastCommand = Deno.env.get("CLAUDE_LAST_COMMAND") || "";
  const isFluxReconcile = lastCommand.includes("flux reconcile") || 
                          lastCommand.includes("task reconcile");

  if (!isFluxReconcile && !hasOverride("FORCE_FLUX_CHECK")) {
    logger.info("Not a Flux reconcile operation, skipping");
    exitHook(createHookResult(true, "Not a Flux operation", 0));
  }

  // Skip if override set
  if (hasOverride("SKIP_FLUX_CHECK")) {
    logger.info("Flux health check skipped via override");
    exitHook(createHookResult(true, "Flux check skipped", 0));
  }

  logger.info("Checking Flux deployment health...");

  // Quick health check (optimized for speed)
  const startTime = Date.now();
  const { healthy, issues } = await quickFluxCheck();
  const elapsed = Date.now() - startTime;
  
  logger.info(`Flux check completed in ${elapsed}ms`, { healthy, issueCount: issues.length });

  if (healthy) {
    // Get recent successful reconciliations for context
    const recent = await getRecentReconciliations();
    
    let message = "✅ Flux deployments healthy";
    if (recent.length > 0) {
      message += `\nRecent reconciliations:\n${recent.map(r => `  • ${r}`).join('\n')}`;
    }
    
    console.log(message);
    exitHook(createHookResult(true, "✅ Flux healthy", 0));
  }

  // Handle unhealthy state
  const suggestions = await suggestRollback(issues);
  
  let message = `⚠️ FLUX DEPLOYMENT ISSUES DETECTED:\n\n`;
  message += `Failed resources:\n`;
  issues.slice(0, 5).forEach(issue => {
    message += `  ❌ ${issue}\n`;
  });
  
  if (issues.length > 5) {
    message += `  ... and ${issues.length - 5} more\n`;
  }

  if (suggestions.length > 0) {
    message += `\n🔧 Suggested fixes:\n`;
    suggestions.forEach(s => {
      message += `  • ${s}\n`;
    });
  }

  message += `\n💡 Check details: flux get all -A --status-selector ready=false`;
  
  console.log(message);
  
  exitHook(createHookResult(false, "⚠️ Flux has unhealthy resources", 1, { issues }));
}

if (import.meta.main) {
  main().catch((error) => {
    const logger = new HookLogger("flux-health-check");
    logger.error("Hook execution failed", error);
    // Don't block on health check failures
    exitHook(createHookResult(true, "Health check failed (non-blocking)", 0));
  });
}