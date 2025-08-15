#!/usr/bin/env deno run --allow-all
/**
 * Namespace Protector Hook
 * Prevents modifications to critical Kubernetes namespaces and infrastructure
 * Protects core cluster components from accidental damage
 */

import {
  HookLogger,
  HookResult,
  createHookResult,
  exitHook,
  hasOverride,
  isProtectedPath,
} from "./hook-utils.ts";

const logger = new HookLogger("namespace-protector");

const PROTECTED_PATHS = [
  "kubernetes/apps/kube-system/",
  "kubernetes/apps/flux-system/", 
  "kubernetes/apps/storage/rook-ceph",
  "kubernetes/flux/",
  "kubernetes/bootstrap/",
  "talos/",
];

const CRITICAL_FILES = [
  ".sops.yaml",
  "age.key",
  "kubeconfig",
];

function isFileCritical(filePath: string): boolean {
  return CRITICAL_FILES.some(criticalFile => filePath.includes(criticalFile));
}

function getProtectedPathDetails(filePath: string): { protected: boolean; reason: string; severity: "critical" | "high" } {
  for (const protectedPath of PROTECTED_PATHS) {
    if (filePath.includes(protectedPath)) {
      let reason = "";
      let severity: "critical" | "high" = "high";

      switch (true) {
        case protectedPath.includes("kube-system"):
          reason = "kube-system contains critical Kubernetes system components";
          severity = "critical";
          break;
        case protectedPath.includes("flux-system"):
          reason = "flux-system contains GitOps controllers - changes here can break deployments";
          severity = "critical";
          break;
        case protectedPath.includes("rook-ceph"):
          reason = "Rook-Ceph storage system - changes can cause data loss";
          severity = "critical";
          break;
        case protectedPath.includes("kubernetes/flux/"):
          reason = "Core Flux configuration - changes affect entire GitOps system";
          severity = "critical";
          break;
        case protectedPath.includes("bootstrap"):
          reason = "Bootstrap configuration affects cluster initialization";
          severity = "high";
          break;
        case protectedPath.includes("talos"):
          reason = "Talos OS configuration affects node operating system";
          severity = "critical";
          break;
        default:
          reason = "Protected infrastructure component";
          severity = "high";
      }

      return { protected: true, reason, severity };
    }
  }

  return { protected: false, reason: "", severity: "high" };
}

function analyzeOperation(): { operation: string; file: string } {
  // Try to determine what operation is being performed
  const operation = Deno.env.get("CLAUDE_OPERATION") || "modify";
  const targetFile = Deno.env.get("CLAUDE_TARGET_FILE") || Deno.args[0] || "";

  return { operation, file: targetFile };
}

function generateSafeAlternatives(filePath: string, operation: string): string[] {
  const alternatives: string[] = [];

  if (filePath.includes("flux-system")) {
    alternatives.push("Consider suspending the resource first: flux suspend hr <name> -n <namespace>");
    alternatives.push("Test changes in a development branch first");
    alternatives.push("Use 'flux reconcile' after changes to verify deployment");
  }

  if (filePath.includes("rook-ceph")) {
    alternatives.push("Check Ceph cluster health before changes: kubectl -n storage exec deploy/rook-ceph-tools -- ceph status");
    alternatives.push("Ensure no ongoing rebalancing operations");
    alternatives.push("Consider maintenance mode for storage cluster");
  }

  if (operation.toLowerCase().includes("delete")) {
    alternatives.push("Use 'suspend' instead of 'delete' for Flux resources");
    alternatives.push("Consider scaling to 0 replicas instead of deletion");
  }

  if (alternatives.length === 0) {
    alternatives.push("Review the change carefully and ensure it follows established patterns");
    alternatives.push("Test in a non-production environment first");
  }

  return alternatives;
}

async function main(): Promise<void> {
  const { operation, file: targetFile } = analyzeOperation();

  // Check for override
  if (hasOverride("FORCE_NAMESPACE_EDIT")) {
    logger.warn(`Protected namespace edit bypassed via override: ${targetFile}`);
    exitHook(createHookResult(true, "Protected namespace edit bypassed", 0));
  }

  if (!targetFile) {
    logger.info("No target file specified");
    exitHook(createHookResult(true, "No file to check", 0));
  }

  logger.info(`Checking protection for: ${targetFile} (operation: ${operation})`);

  // Check if file is critical
  if (isFileCritical(targetFile)) {
    const message = `🚨 CRITICAL FILE DETECTED: ${targetFile}
This file contains sensitive configuration that can break the cluster.
Set FORCE_NAMESPACE_EDIT=true if you're certain about this change.`;
    
    logger.error("Critical file modification attempt", { file: targetFile, operation });
    exitHook(createHookResult(false, message, 2));
  }

  // Check if path is protected
  const protection = getProtectedPathDetails(targetFile);
  
  if (protection.protected) {
    const alternatives = generateSafeAlternatives(targetFile, operation);
    
    const message = `🛡️  PROTECTED NAMESPACE: ${targetFile}
    
⚠️  Risk Level: ${protection.severity.toUpperCase()}
📋 Reason: ${protection.reason}

🔧 Safe alternatives:
${alternatives.map(alt => `   • ${alt}`).join('\n')}

💡 To proceed anyway, set: FORCE_NAMESPACE_EDIT=true

🔄 Remember the golden rule: "Think before you delete. Suspend, don't delete."`;

    logger.warn("Protected namespace access attempt", { 
      file: targetFile, 
      operation, 
      severity: protection.severity,
      reason: protection.reason 
    });

    exitHook(createHookResult(false, message, 2, {
      protectedPath: targetFile,
      severity: protection.severity,
      alternatives,
    }));
  }

  // File is safe to modify
  logger.info(`File cleared for modification: ${targetFile}`);
  exitHook(createHookResult(true, "Path is safe to modify", 0));
}

if (import.meta.main) {
  main().catch((error) => {
    const logger = new HookLogger("namespace-protector");
    logger.error("Hook execution failed", error);
    exitHook(createHookResult(false, `Hook execution failed: ${error.message}`, 2));
  });
}