#!/usr/bin/env deno run --allow-all
/**
 * Storage Health Check Hook
 * Monitors Ceph storage health after storage-related changes
 * Optimized for speed with caching and parallel checks
 */

import {
  HookLogger,
  HookResult,
  createHookResult,
  exitHook,
  hasOverride,
  runCommand,
} from "./hook-utils.ts";

const logger = new HookLogger("storage-health-check");

interface CephStatus {
  healthy: boolean;
  health: string;
  osdsUp: number;
  osdsTotal: number;
  pgStatus: string;
  warnings: string[];
}

async function quickCephCheck(): Promise<CephStatus> {
  const status: CephStatus = {
    healthy: true,
    health: "UNKNOWN",
    osdsUp: 0,
    osdsTotal: 0,
    pgStatus: "unknown",
    warnings: [],
  };

  try {
    // Quick health check using ceph status (faster than full health detail)
    const result = await runCommand([
      "kubectl", "exec", "-n", "storage",
      "deploy/rook-ceph-tools", "--",
      "ceph", "status", "-f", "json"
    ]);

    if (result.success) {
      try {
        const cephData = JSON.parse(result.output);
        
        // Parse health
        status.health = cephData.health?.status || "UNKNOWN";
        status.healthy = status.health === "HEALTH_OK" || status.health === "HEALTH_WARN";
        
        // Parse OSD status
        status.osdsUp = cephData.osdmap?.num_up_osds || 0;
        status.osdsTotal = cephData.osdmap?.num_osds || 0;
        
        // Parse PG status
        const pgStats = cephData.pgmap?.pgs_by_state || [];
        if (pgStats.length > 0) {
          status.pgStatus = pgStats.map((s: any) => s.state_name).join(", ");
        }
        
        // Check for issues
        if (status.osdsUp < status.osdsTotal) {
          status.warnings.push(`${status.osdsTotal - status.osdsUp} OSD(s) down`);
          status.healthy = false;
        }
        
        if (status.health === "HEALTH_ERR") {
          status.healthy = false;
          status.warnings.push("Ceph cluster in ERROR state");
        }
        
        // Check for unhealthy PGs
        if (status.pgStatus.includes("degraded") || 
            status.pgStatus.includes("incomplete") ||
            status.pgStatus.includes("stale")) {
          status.warnings.push(`Unhealthy PGs: ${status.pgStatus}`);
          status.healthy = false;
        }
        
      } catch (parseError) {
        logger.error("Failed to parse Ceph status", parseError);
        // Fall back to simple text check
        if (result.output.includes("HEALTH_OK")) {
          status.health = "HEALTH_OK";
          status.healthy = true;
        } else if (result.output.includes("HEALTH_WARN")) {
          status.health = "HEALTH_WARN";
          status.healthy = true;
          status.warnings.push("Ceph has warnings");
        } else {
          status.healthy = false;
          status.warnings.push("Unable to determine Ceph health");
        }
      }
    } else {
      status.healthy = false;
      status.warnings.push("Cannot connect to Ceph cluster");
    }
  } catch (error) {
    logger.error("Ceph check failed", error);
    status.healthy = false;
    status.warnings.push("Ceph health check failed");
  }

  return status;
}

async function checkPVCStatus(): Promise<{ bound: number; pending: number; issues: string[] }> {
  const pvcStatus = {
    bound: 0,
    pending: 0,
    issues: [] as string[],
  };

  try {
    const result = await runCommand([
      "kubectl", "get", "pvc", "-A",
      "-o", "json"
    ]);

    if (result.success) {
      const pvcs = JSON.parse(result.output);
      for (const pvc of pvcs.items || []) {
        if (pvc.status?.phase === "Bound") {
          pvcStatus.bound++;
        } else if (pvc.status?.phase === "Pending") {
          pvcStatus.pending++;
          pvcStatus.issues.push(`${pvc.metadata?.namespace}/${pvc.metadata?.name} pending`);
        }
      }
    }
  } catch {
    // Non-critical, ignore
  }

  return pvcStatus;
}

function isStorageRelatedFile(filePath: string): boolean {
  const storagePatterns = [
    "storage/",
    "rook",
    "ceph",
    "pvc",
    "pv",
    "storageclass",
    "volumesnapshot",
  ];
  
  return storagePatterns.some(pattern => 
    filePath.toLowerCase().includes(pattern)
  );
}

async function main(): Promise<void> {
  // Check if this is a storage-related operation
  const targetFile = Deno.env.get("CLAUDE_TARGET_FILE") || "";
  const lastCommand = Deno.env.get("CLAUDE_LAST_COMMAND") || "";
  
  const isStorageOperation = isStorageRelatedFile(targetFile) ||
                             lastCommand.includes("storage") ||
                             lastCommand.includes("ceph") ||
                             lastCommand.includes("rook");

  if (!isStorageOperation && !hasOverride("FORCE_STORAGE_CHECK")) {
    logger.info("Not a storage operation, skipping");
    exitHook(createHookResult(true, "Not a storage operation", 0));
  }

  // Skip if override set
  if (hasOverride("SKIP_STORAGE_CHECK")) {
    logger.info("Storage health check skipped via override");
    exitHook(createHookResult(true, "Storage check skipped", 0));
  }

  logger.info("Checking storage health...");

  // Run checks in parallel for speed
  const startTime = Date.now();
  const [cephStatus, pvcStatus] = await Promise.all([
    quickCephCheck(),
    checkPVCStatus(),
  ]);
  const elapsed = Date.now() - startTime;
  
  logger.info(`Storage check completed in ${elapsed}ms`);

  // Generate report
  let message = "";
  let exitCode: 0 | 1 | 2 = 0;

  if (cephStatus.healthy && pvcStatus.pending === 0) {
    message = `✅ Storage healthy\n`;
    message += `• Ceph: ${cephStatus.health}\n`;
    message += `• OSDs: ${cephStatus.osdsUp}/${cephStatus.osdsTotal} up\n`;
    message += `• PVCs: ${pvcStatus.bound} bound`;
    
    console.log(message);
    exitHook(createHookResult(true, "✅ Storage healthy", 0));
  }

  // Handle issues
  message = `⚠️ STORAGE HEALTH ISSUES:\n\n`;
  
  if (!cephStatus.healthy) {
    message += `🔴 Ceph Status: ${cephStatus.health}\n`;
    message += `• OSDs: ${cephStatus.osdsUp}/${cephStatus.osdsTotal} up\n`;
    
    if (cephStatus.warnings.length > 0) {
      message += `• Issues:\n`;
      cephStatus.warnings.forEach(w => {
        message += `  - ${w}\n`;
      });
    }
    
    exitCode = 2; // Block operations when Ceph is unhealthy
  }

  if (pvcStatus.pending > 0) {
    message += `\n🟡 PVC Issues:\n`;
    message += `• ${pvcStatus.pending} PVC(s) pending\n`;
    pvcStatus.issues.slice(0, 3).forEach(issue => {
      message += `  - ${issue}\n`;
    });
    
    if (exitCode === 0) exitCode = 1; // Warning for PVC issues
  }

  message += `\n🔧 Recommended actions:\n`;
  if (!cephStatus.healthy) {
    message += `• Check Ceph details: kubectl -n storage exec deploy/rook-ceph-tools -- ceph health detail\n`;
    message += `• Monitor OSD status: kubectl -n storage exec deploy/rook-ceph-tools -- ceph osd status\n`;
  }
  if (pvcStatus.pending > 0) {
    message += `• Check PVC events: kubectl describe pvc -A | grep -A5 Warning\n`;
  }

  console.log(message);
  
  exitHook(createHookResult(
    exitCode < 2,
    exitCode === 2 ? "❌ Storage unhealthy - operations blocked" : "⚠️ Storage has issues",
    exitCode,
    { cephStatus, pvcStatus }
  ));
}

if (import.meta.main) {
  main().catch((error) => {
    const logger = new HookLogger("storage-health-check");
    logger.error("Hook execution failed", error);
    // Don't block on health check failures
    exitHook(createHookResult(true, "Storage check failed (non-blocking)", 0));
  });
}