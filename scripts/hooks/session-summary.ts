#!/usr/bin/env deno run --allow-all
/**
 * Session Summary Hook
 * Generates a quick summary of changes made during the session
 * Runs on Stop event - optimized for speed
 */

import {
  HookLogger,
  HookResult,
  createHookResult,
  exitHook,
  hasOverride,
  runCommand,
} from "./hook-utils.ts";

const logger = new HookLogger("session-summary");

interface SessionSummary {
  filesModified: string[];
  gitChanges: { added: number; modified: number; deleted: number };
  fluxResources: string[];
  warnings: string[];
  rollbackCommands: string[];
}

async function getGitChanges(): Promise<SessionSummary["gitChanges"]> {
  const changes = { added: 0, modified: 0, deleted: 0 };
  
  try {
    const result = await runCommand(["git", "status", "--porcelain"]);
    if (result.success) {
      const lines = result.output.split('\n').filter(l => l.trim());
      lines.forEach(line => {
        if (line.startsWith("A") || line.startsWith("??")) changes.added++;
        else if (line.startsWith("M")) changes.modified++;
        else if (line.startsWith("D")) changes.deleted++;
      });
    }
  } catch {
    // Ignore git errors
  }
  
  return changes;
}

async function getModifiedFiles(): Promise<string[]> {
  const files: string[] = [];
  
  try {
    const result = await runCommand(["git", "diff", "--name-only", "HEAD"]);
    if (result.success && result.output) {
      files.push(...result.output.split('\n').filter(f => f.trim()));
    }
    
    // Also check untracked files
    const untrackedResult = await runCommand(["git", "ls-files", "--others", "--exclude-standard"]);
    if (untrackedResult.success && untrackedResult.output) {
      files.push(...untrackedResult.output.split('\n').filter(f => f.trim()));
    }
  } catch {
    // Ignore errors
  }
  
  return files.slice(0, 10); // Limit to first 10 files
}

async function getFluxResources(files: string[]): Promise<string[]> {
  const resources: string[] = [];
  
  for (const file of files) {
    if (file.includes("kubernetes/") && (file.endsWith(".yaml") || file.endsWith(".yml"))) {
      // Extract resource type from path
      if (file.includes("/apps/")) {
        const parts = file.split('/');
        const namespace = parts[parts.indexOf("apps") + 1];
        const app = parts[parts.indexOf("apps") + 2];
        if (namespace && app) {
          resources.push(`${namespace}/${app}`);
        }
      }
    }
  }
  
  return [...new Set(resources)]; // Remove duplicates
}

function generateRollbackCommands(summary: SessionSummary): string[] {
  const commands: string[] = [];
  
  // Git rollback
  if (summary.gitChanges.added + summary.gitChanges.modified + summary.gitChanges.deleted > 0) {
    commands.push("git restore --staged . && git restore .");
  }
  
  // Flux rollback for each resource
  for (const resource of summary.fluxResources) {
    const [namespace, app] = resource.split('/');
    commands.push(`flux suspend hr ${app} -n ${namespace} && flux resume hr ${app} -n ${namespace}`);
  }
  
  return commands;
}

function generateWarnings(summary: SessionSummary): string[] {
  const warnings: string[] = [];
  
  // Check for critical file modifications
  for (const file of summary.filesModified) {
    if (file.includes("flux-system") || file.includes("kube-system")) {
      warnings.push(`Critical namespace modified: ${file}`);
    }
    if (file.includes("storage") || file.includes("rook") || file.includes("ceph")) {
      warnings.push(`Storage configuration modified: ${file}`);
    }
    if (file.includes("secret") || file.includes(".sops.")) {
      warnings.push(`Secret file modified: ${file}`);
    }
  }
  
  // Warn about uncommitted changes
  const totalChanges = summary.gitChanges.added + summary.gitChanges.modified + summary.gitChanges.deleted;
  if (totalChanges > 0) {
    warnings.push(`${totalChanges} uncommitted changes - remember to commit or discard`);
  }
  
  return warnings;
}

async function main(): Promise<void> {
  // Skip if override set
  if (hasOverride("SKIP_SESSION_SUMMARY")) {
    logger.info("Session summary skipped via override");
    exitHook(createHookResult(true, "Summary skipped", 0));
  }

  logger.info("Generating session summary...");
  
  const startTime = Date.now();
  
  // Gather data in parallel for speed
  const [gitChanges, modifiedFiles] = await Promise.all([
    getGitChanges(),
    getModifiedFiles(),
  ]);
  
  const fluxResources = await getFluxResources(modifiedFiles);
  
  const summary: SessionSummary = {
    filesModified: modifiedFiles,
    gitChanges,
    fluxResources,
    warnings: [],
    rollbackCommands: [],
  };
  
  summary.warnings = generateWarnings(summary);
  summary.rollbackCommands = generateRollbackCommands(summary);
  
  const elapsed = Date.now() - startTime;
  logger.info(`Summary generated in ${elapsed}ms`);
  
  // Generate output
  let output = "\n📋 SESSION SUMMARY\n";
  output += "═".repeat(50) + "\n\n";
  
  // Git changes
  const totalChanges = summary.gitChanges.added + summary.gitChanges.modified + summary.gitChanges.deleted;
  if (totalChanges > 0) {
    output += `📝 Git Changes:\n`;
    if (summary.gitChanges.added > 0) output += `  • Added: ${summary.gitChanges.added} files\n`;
    if (summary.gitChanges.modified > 0) output += `  • Modified: ${summary.gitChanges.modified} files\n`;
    if (summary.gitChanges.deleted > 0) output += `  • Deleted: ${summary.gitChanges.deleted} files\n`;
    output += "\n";
  }
  
  // Modified files
  if (summary.filesModified.length > 0) {
    output += `📁 Files Modified:\n`;
    summary.filesModified.forEach(file => {
      output += `  • ${file}\n`;
    });
    output += "\n";
  }
  
  // Flux resources
  if (summary.fluxResources.length > 0) {
    output += `🔄 Flux Resources Affected:\n`;
    summary.fluxResources.forEach(resource => {
      output += `  • ${resource}\n`;
    });
    output += "\n";
  }
  
  // Warnings
  if (summary.warnings.length > 0) {
    output += `⚠️ Warnings:\n`;
    summary.warnings.forEach(warning => {
      output += `  • ${warning}\n`;
    });
    output += "\n";
  }
  
  // Rollback commands
  if (summary.rollbackCommands.length > 0) {
    output += `🔄 Rollback Commands (if needed):\n`;
    summary.rollbackCommands.forEach(cmd => {
      output += `  ${cmd}\n`;
    });
    output += "\n";
  }
  
  // Next steps
  output += `📌 Next Steps:\n`;
  if (totalChanges > 0) {
    output += `  1. Review changes: git diff\n`;
    output += `  2. Commit if satisfied: git add . && git commit -m "..."\n`;
    output += `  3. Push to trigger GitOps: git push\n`;
  } else {
    output += `  • No uncommitted changes\n`;
  }
  
  if (summary.fluxResources.length > 0) {
    output += `  • Monitor deployments: flux get all -A\n`;
  }
  
  output += "\n" + "═".repeat(50) + "\n";
  output += "Session complete. All hooks executed successfully.\n";
  
  console.log(output);
  
  // Save summary to file for review
  try {
    const summaryFile = `/tmp/claude-session-${Date.now()}.json`;
    await Deno.writeTextFile(summaryFile, JSON.stringify(summary, null, 2));
    logger.info(`Summary saved to ${summaryFile}`);
  } catch {
    // Ignore save errors
  }
  
  exitHook(createHookResult(true, "✅ Session summary generated", 0, summary));
}

if (import.meta.main) {
  main().catch((error) => {
    const logger = new HookLogger("session-summary");
    logger.error("Hook execution failed", error);
    // Don't block on summary failures
    exitHook(createHookResult(true, "Summary failed (non-blocking)", 0));
  });
}