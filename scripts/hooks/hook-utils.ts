#!/usr/bin/env deno run --allow-all
/**
 * Hook Utilities for Claude Code Kubernetes Homelab
 * Shared utilities for all hooks
 */

export interface HookResult {
  success: boolean;
  message: string;
  exitCode: 0 | 1 | 2;
  details?: any;
}

export class HookLogger {
  private hookName: string;
  private logFile: string;

  constructor(hookName: string) {
    this.hookName = hookName;
    this.logFile = `/tmp/claude-hooks-${hookName}.log`;
  }

  log(level: "INFO" | "WARN" | "ERROR", message: string, details?: any) {
    const timestamp = new Date().toISOString();
    const logEntry = {
      timestamp,
      hook: this.hookName,
      level,
      message,
      details,
    };

    // Write to log file
    const logLine = JSON.stringify(logEntry) + "\n";
    try {
      Deno.writeTextFileSync(this.logFile, logLine, { append: true });
    } catch {
      // Ignore log write failures
    }

    // Also output for debugging if verbose
    if (Deno.env.get("CLAUDE_HOOK_VERBOSE") === "true") {
      console.error(`[${level}] ${this.hookName}: ${message}`);
      if (details) {
        console.error(JSON.stringify(details, null, 2));
      }
    }
  }

  info(message: string, details?: any) {
    this.log("INFO", message, details);
  }

  warn(message: string, details?: any) {
    this.log("WARN", message, details);
  }

  error(message: string, details?: any) {
    this.log("ERROR", message, details);
  }
}

export function createHookResult(
  success: boolean,
  message: string,
  exitCode: 0 | 1 | 2 = success ? 0 : 2,
  details?: any
): HookResult {
  return { success, message, exitCode, details };
}

export function isKubernetesFile(filePath: string): boolean {
  // Check if file is in kubernetes/ directory or has k8s-related content
  return (
    filePath.includes("kubernetes/") ||
    filePath.endsWith(".yaml") ||
    filePath.endsWith(".yml")
  );
}

export function isProtectedPath(filePath: string): boolean {
  const protectedPaths = [
    "kubernetes/apps/kube-system/",
    "kubernetes/apps/flux-system/",
    "kubernetes/apps/storage/rook-ceph",
    "kubernetes/flux/",
  ];

  return protectedPaths.some((path) => filePath.includes(path));
}

export function hasOverride(overrideVar: string): boolean {
  return Deno.env.get(overrideVar) === "true";
}

export function formatHookMessage(result: HookResult): string {
  const prefix = result.success ? "✅" : result.exitCode === 1 ? "⚠️" : "❌";
  return `${prefix} ${result.message}`;
}

export async function runCommand(cmd: string[]): Promise<{ success: boolean; output: string; error: string }> {
  try {
    const process = new Deno.Command(cmd[0], {
      args: cmd.slice(1),
      stdout: "piped",
      stderr: "piped",
    });

    const result = await process.output();
    const output = new TextDecoder().decode(result.stdout);
    const error = new TextDecoder().decode(result.stderr);

    return {
      success: result.code === 0,
      output,
      error,
    };
  } catch (err) {
    return {
      success: false,
      output: "",
      error: err.message,
    };
  }
}

export function getModifiedFiles(): string[] {
  // Get list of files that might be modified by checking CLAUDE_* environment variables
  const claudeFiles = Object.keys(Deno.env.toObject())
    .filter((key) => key.startsWith("CLAUDE_") && key.includes("FILE"))
    .map((key) => Deno.env.get(key))
    .filter((file): file is string => file !== undefined);

  return claudeFiles;
}

// Validation utilities
export function isValidYaml(content: string): { valid: boolean; error?: string } {
  try {
    // Use a simple YAML parser check
    const yamlLines = content.split("\n");
    let indentLevel = 0;
    
    for (const line of yamlLines) {
      const trimmed = line.trim();
      if (trimmed === "" || trimmed.startsWith("#")) continue;
      
      // Basic YAML structure validation
      if (trimmed.includes(":") && !trimmed.startsWith("-")) {
        // Key-value pair
        const currentIndent = line.length - line.trimStart().length;
        if (currentIndent < 0) {
          return { valid: false, error: "Invalid indentation" };
        }
      }
    }
    
    return { valid: true };
  } catch (error) {
    return { valid: false, error: error.message };
  }
}

export function hasKubernetesApiVersion(content: string): boolean {
  return content.includes("apiVersion:") && content.includes("kind:");
}

// Exit with appropriate code and message
export function exitHook(result: HookResult): never {
  if (!result.success && result.exitCode > 0) {
    console.error(formatHookMessage(result));
    if (result.details) {
      console.error(JSON.stringify(result.details, null, 2));
    }
  } else if (result.exitCode === 1) {
    console.warn(formatHookMessage(result));
  } else if (result.success) {
    console.log(formatHookMessage(result));
  }

  Deno.exit(result.exitCode);
}