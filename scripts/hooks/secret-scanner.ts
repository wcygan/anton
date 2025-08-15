#!/usr/bin/env deno run --allow-all
/**
 * Secret Scanner Hook
 * Prevents accidentally committing secrets, API keys, and credentials
 * Enforces proper SOPS encryption for sensitive data
 */

import {
  HookLogger,
  HookResult,
  createHookResult,
  exitHook,
  hasOverride,
  runCommand,
} from "./hook-utils.ts";

const logger = new HookLogger("secret-scanner");

interface SecretDetection {
  line: number;
  content: string;
  type: string;
  severity: "high" | "medium" | "low";
  confidence: number; // 0-100
}

const SECRET_PATTERNS = [
  // API Keys and tokens
  { regex: /sk-[a-zA-Z0-9]{32,}/, type: "OpenAI API Key", severity: "high" as const, confidence: 95 },
  { regex: /xoxb-[a-zA-Z0-9-]+/, type: "Slack Bot Token", severity: "high" as const, confidence: 95 },
  { regex: /ghp_[a-zA-Z0-9]{36}/, type: "GitHub Personal Access Token", severity: "high" as const, confidence: 95 },
  { regex: /gho_[a-zA-Z0-9]{36}/, type: "GitHub OAuth Token", severity: "high" as const, confidence: 95 },
  { regex: /github_pat_[a-zA-Z0-9_]{82}/, type: "GitHub Fine-grained PAT", severity: "high" as const, confidence: 95 },
  
  // AWS Credentials
  { regex: /AKIA[0-9A-Z]{16}/, type: "AWS Access Key", severity: "high" as const, confidence: 90 },
  { regex: /[0-9a-zA-Z/+]{40}/, type: "AWS Secret Key (possible)", severity: "medium" as const, confidence: 60 },
  
  // Common password patterns
  { regex: /password\s*[:=]\s*['"][^'"]{8,}['"]/, type: "Password in config", severity: "high" as const, confidence: 80 },
  { regex: /passwd\s*[:=]\s*['"][^'"]{8,}['"]/, type: "Password in config", severity: "high" as const, confidence: 80 },
  { regex: /secret\s*[:=]\s*['"][^'"]{16,}['"]/, type: "Secret in config", severity: "high" as const, confidence: 75 },
  
  // Base64 patterns (potential secrets)
  { regex: /[A-Za-z0-9+/]{32,}={0,2}/, type: "Base64 encoded data (possible secret)", severity: "medium" as const, confidence: 40 },
  
  // Kubernetes secret data
  { regex: /data:\s*\n\s+[a-zA-Z0-9-_]+:\s+[A-Za-z0-9+/]+=*/, type: "Kubernetes Secret data", severity: "high" as const, confidence: 85 },
  
  // Private keys
  { regex: /-----BEGIN [A-Z ]*PRIVATE KEY-----/, type: "Private Key", severity: "high" as const, confidence: 100 },
  { regex: /-----BEGIN OPENSSH PRIVATE KEY-----/, type: "SSH Private Key", severity: "high" as const, confidence: 100 },
  
  // Database connection strings
  { regex: /[a-zA-Z][a-zA-Z0-9+.-]*:\/\/[^:\/\s]+:[^@\/\s]+@/, type: "Database connection string", severity: "high" as const, confidence: 85 },
  
  // JWT tokens
  { regex: /eyJ[a-zA-Z0-9_-]*\.eyJ[a-zA-Z0-9_-]*\.[a-zA-Z0-9_-]*/, type: "JWT Token", severity: "medium" as const, confidence: 90 },
];

const ALLOWED_PATTERNS = [
  // Example/template values that are safe
  /example[._-]?com/i,
  /localhost/i,
  /127\.0\.0\.1/,
  /\$\{[^}]+\}/, // Environment variable references
  /\{\{[^}]+\}\}/, // Template variables
  /<[^>]+>/, // Placeholder values
  /xxxxx+/i,
  /password/i, // Just the word password without actual value
  /secret/i, // Just the word secret without actual value
];

function isAllowedPattern(content: string): boolean {
  return ALLOWED_PATTERNS.some(pattern => pattern.test(content));
}

function isSOPSEncrypted(filePath: string, content: string): boolean {
  // Check if file is SOPS encrypted
  return (
    filePath.includes(".sops.") ||
    content.includes("sops:") ||
    content.includes("mac: ENC[") ||
    content.includes("pgp:") ||
    content.includes("age:")
  );
}

function shouldSkipFile(filePath: string): boolean {
  const skipPatterns = [
    ".git/",
    "node_modules/",
    ".cache/",
    "/tmp/",
    ".log",
    ".lock",
    "package-lock.json",
    "yarn.lock",
    ".md", // Markdown files (documentation)
  ];

  return skipPatterns.some(pattern => filePath.includes(pattern));
}

async function scanFileForSecrets(filePath: string): Promise<SecretDetection[]> {
  const detections: SecretDetection[] = [];

  try {
    const content = await Deno.readTextFile(filePath);
    const lines = content.split('\n');

    // Skip SOPS encrypted files
    if (isSOPSEncrypted(filePath, content)) {
      logger.info(`Skipping SOPS encrypted file: ${filePath}`);
      return detections;
    }

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      const lineNumber = i + 1;

      // Skip comments and empty lines
      if (line.trim().startsWith('#') || line.trim() === '') {
        continue;
      }

      for (const pattern of SECRET_PATTERNS) {
        const matches = line.match(pattern.regex);
        if (matches) {
          for (const match of matches) {
            // Skip if it's an allowed pattern
            if (isAllowedPattern(match)) {
              continue;
            }

            // Additional filtering for base64 - skip short or obvious non-secrets
            if (pattern.type.includes("Base64") && (
              match.length < 32 || 
              match.includes("=") && match.split("=")[0].length < 24
            )) {
              continue;
            }

            detections.push({
              line: lineNumber,
              content: line.trim(),
              type: pattern.type,
              severity: pattern.severity,
              confidence: pattern.confidence,
            });
          }
        }
      }
    }
  } catch (error) {
    logger.error(`Failed to read file ${filePath}`, error);
  }

  return detections;
}

async function validateSOPSFile(filePath: string): Promise<{ valid: boolean; error?: string }> {
  if (!filePath.includes(".sops.")) {
    return { valid: true }; // Not a SOPS file
  }

  try {
    // Check if sops command is available
    const sopsCheck = await runCommand(["which", "sops"]);
    if (!sopsCheck.success) {
      return { valid: true, error: "SOPS not available for validation" };
    }

    // Try to decrypt the file to validate it
    const decryptResult = await runCommand(["sops", "-d", filePath]);
    return { valid: decryptResult.success, error: decryptResult.error };
  } catch (error) {
    return { valid: false, error: error.message };
  }
}

function generateSecretReport(detections: SecretDetection[]): string {
  if (detections.length === 0) {
    return "✅ No secrets detected";
  }

  const highSeverity = detections.filter(d => d.severity === "high");
  const mediumSeverity = detections.filter(d => d.severity === "medium");

  let report = "🚨 POTENTIAL SECRETS DETECTED:\n\n";

  if (highSeverity.length > 0) {
    report += "🔴 HIGH SEVERITY:\n";
    for (const detection of highSeverity) {
      report += `   Line ${detection.line}: ${detection.type} (${detection.confidence}% confidence)\n`;
      report += `   > ${detection.content.substring(0, 100)}${detection.content.length > 100 ? '...' : ''}\n\n`;
    }
  }

  if (mediumSeverity.length > 0) {
    report += "🟡 MEDIUM SEVERITY:\n";
    for (const detection of mediumSeverity.slice(0, 3)) { // Limit to first 3 to avoid noise
      report += `   Line ${detection.line}: ${detection.type} (${detection.confidence}% confidence)\n`;
    }
    if (mediumSeverity.length > 3) {
      report += `   ... and ${mediumSeverity.length - 3} more medium severity detections\n`;
    }
    report += "\n";
  }

  report += "🔧 RECOMMENDED ACTIONS:\n";
  if (highSeverity.length > 0) {
    report += "   • Remove secrets from the file immediately\n";
    report += "   • Use 1Password + External Secrets Operator for secrets\n";
    report += "   • For legacy secrets, use SOPS encryption (*.sops.yaml)\n";
  } else {
    report += "   • Review detected patterns carefully\n";
    report += "   • Use environment variables or secret management\n";
  }

  report += "\n💡 To bypass (if false positive): FORCE_SECRET_SCAN=true";

  return report;
}

async function main(): Promise<void> {
  // Check for override
  if (hasOverride("FORCE_SECRET_SCAN")) {
    logger.warn("Secret scanning bypassed via override");
    exitHook(createHookResult(true, "Secret scanning bypassed", 0));
  }

  const targetFile = Deno.env.get("CLAUDE_TARGET_FILE") || Deno.args[0];
  
  if (!targetFile) {
    logger.info("No target file specified");
    exitHook(createHookResult(true, "No file to scan", 0));
  }

  // Skip non-relevant files
  if (shouldSkipFile(targetFile)) {
    logger.info(`Skipping file: ${targetFile}`);
    exitHook(createHookResult(true, "File type skipped", 0));
  }

  logger.info(`Scanning for secrets: ${targetFile}`);

  // Validate SOPS files
  const sopsValidation = await validateSOPSFile(targetFile);
  if (!sopsValidation.valid) {
    const message = `❌ SOPS validation failed: ${sopsValidation.error}`;
    logger.error("SOPS validation failed", { file: targetFile, error: sopsValidation.error });
    exitHook(createHookResult(false, message, 2));
  }

  // Scan for secrets
  const detections = await scanFileForSecrets(targetFile);
  const highSeverityDetections = detections.filter(d => d.severity === "high" && d.confidence > 70);
  
  logger.info(`Scan completed: ${detections.length} detections, ${highSeverityDetections.length} high severity`);

  // Generate report
  const report = generateSecretReport(detections);

  if (highSeverityDetections.length > 0) {
    logger.error("High severity secrets detected", { 
      file: targetFile, 
      detections: highSeverityDetections.length 
    });
    exitHook(createHookResult(false, report, 2, { detections }));
  } else if (detections.length > 0) {
    logger.warn("Medium severity patterns detected", { 
      file: targetFile, 
      detections: detections.length 
    });
    exitHook(createHookResult(true, report, 1, { detections }));
  } else {
    exitHook(createHookResult(true, "✅ No secrets detected", 0));
  }
}

if (import.meta.main) {
  main().catch((error) => {
    const logger = new HookLogger("secret-scanner");
    logger.error("Hook execution failed", error);
    exitHook(createHookResult(false, `Hook execution failed: ${error.message}`, 2));
  });
}