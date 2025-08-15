#!/usr/bin/env deno run --allow-all
/**
 * Prompt Guardian Hook
 * Analyzes user prompts for risky operations and injects safety context
 * Runs on UserPromptSubmit to catch dangerous operations early
 */

import {
  HookLogger,
  HookResult,
  createHookResult,
  exitHook,
  hasOverride,
} from "./hook-utils.ts";

const logger = new HookLogger("prompt-guardian");

interface RiskPattern {
  pattern: RegExp;
  risk: "critical" | "high" | "medium";
  category: string;
  warningMessage: string;
  safeAlternatives: string[];
  requiresConfirmation?: boolean;
}

const RISK_PATTERNS: RiskPattern[] = [
  // Critical risks - Destructive operations
  {
    pattern: /delete\s+(all|namespace|pvc|pv|storage|cluster|node)/i,
    risk: "critical",
    category: "Destructive Operation",
    warningMessage: "⚠️ This operation could permanently delete resources and data",
    safeAlternatives: [
      "Consider using 'flux suspend' instead of delete for Flux resources",
      "Scale deployments to 0 replicas instead of deleting",
      "Use 'kubectl cordon' to safely remove nodes from scheduling",
    ],
    requiresConfirmation: true,
  },
  {
    pattern: /wipe|purge|clean\s*(all|everything|cluster)/i,
    risk: "critical",
    category: "Data Loss Risk",
    warningMessage: "🚨 This could result in irreversible data loss",
    safeAlternatives: [
      "Target specific resources instead of bulk operations",
      "Create backups before proceeding",
      "Test in a development environment first",
    ],
    requiresConfirmation: true,
  },
  {
    pattern: /reset\s+(cluster|talos|node|ceph)/i,
    risk: "critical",
    category: "System Reset",
    warningMessage: "⚠️ System reset will destroy all configuration and data",
    safeAlternatives: [
      "Try targeted troubleshooting first",
      "Consider rolling back specific changes",
      "Ensure you have backups and can restore",
    ],
    requiresConfirmation: true,
  },
  
  // High risks - Infrastructure changes
  {
    pattern: /remove|delete.*(rook|ceph|storage|osd)/i,
    risk: "high",
    category: "Storage System",
    warningMessage: "🗄️ Storage system changes can cause data unavailability",
    safeAlternatives: [
      "Check 'ceph health' before making changes",
      "Ensure replication is healthy",
      "Consider maintenance mode for planned changes",
    ],
  },
  {
    pattern: /delete.*(flux|gitops|kustomization)/i,
    risk: "high",
    category: "GitOps System",
    warningMessage: "🔄 GitOps changes affect automated deployments",
    safeAlternatives: [
      "Use 'flux suspend' instead of delete",
      "Verify dependencies before removing",
      "Check 'flux get all -A' for current state",
    ],
  },
  {
    pattern: /scale.*0|stop.*all|shutdown/i,
    risk: "high",
    category: "Service Availability",
    warningMessage: "🛑 This will stop services and affect availability",
    safeAlternatives: [
      "Consider rolling updates instead",
      "Scale down gradually",
      "Ensure other replicas can handle load",
    ],
  },
  
  // Medium risks - Configuration changes
  {
    pattern: /change|modify|update.*(secret|password|key|token)/i,
    risk: "medium",
    category: "Secrets Management",
    warningMessage: "🔐 Changing secrets requires careful coordination",
    safeAlternatives: [
      "Use External Secrets Operator for rotation",
      "Update 1Password first, then sync",
      "Restart affected pods after secret changes",
    ],
  },
  {
    pattern: /upgrade|update.*(talos|kubernetes|k8s)/i,
    risk: "medium",
    category: "Cluster Upgrade",
    warningMessage: "⬆️ Upgrades should follow the documented process",
    safeAlternatives: [
      "Review release notes for breaking changes",
      "Upgrade Talos before Kubernetes",
      "Test with one node first",
    ],
  },
  {
    pattern: /force|--force|-f\s/i,
    risk: "medium",
    category: "Forced Operation",
    warningMessage: "💪 Force operations bypass safety checks",
    safeAlternatives: [
      "Understand why the operation is blocked",
      "Fix the root cause instead of forcing",
      "Document why force was necessary",
    ],
  },
];

interface PromptAnalysis {
  hasRisks: boolean;
  risks: Array<{
    pattern: RiskPattern;
    match: string;
  }>;
  maxRiskLevel: "critical" | "high" | "medium" | "low";
  requiresConfirmation: boolean;
  contextToInject: string;
}

function analyzePrompt(prompt: string): PromptAnalysis {
  const analysis: PromptAnalysis = {
    hasRisks: false,
    risks: [],
    maxRiskLevel: "low",
    requiresConfirmation: false,
    contextToInject: "",
  };

  for (const pattern of RISK_PATTERNS) {
    const matches = prompt.match(pattern.pattern);
    if (matches) {
      analysis.hasRisks = true;
      analysis.risks.push({
        pattern,
        match: matches[0],
      });

      // Update max risk level
      if (pattern.risk === "critical" || 
          (pattern.risk === "high" && analysis.maxRiskLevel !== "critical") ||
          (pattern.risk === "medium" && analysis.maxRiskLevel === "low")) {
        analysis.maxRiskLevel = pattern.risk;
      }

      if (pattern.requiresConfirmation) {
        analysis.requiresConfirmation = true;
      }
    }
  }

  // Generate context to inject
  if (analysis.hasRisks) {
    analysis.contextToInject = generateSafetyContext(analysis);
  }

  return analysis;
}

function generateSafetyContext(analysis: PromptAnalysis): string {
  let context = "\n🛡️ SAFETY ANALYSIS DETECTED RISKS:\n\n";

  // Group risks by category
  const risksByCategory = new Map<string, typeof analysis.risks>();
  for (const risk of analysis.risks) {
    const category = risk.pattern.category;
    if (!risksByCategory.has(category)) {
      risksByCategory.set(category, []);
    }
    risksByCategory.get(category)!.push(risk);
  }

  // Generate context for each category
  for (const [category, risks] of risksByCategory) {
    const severityIcon = risks[0].pattern.risk === "critical" ? "🚨" : 
                         risks[0].pattern.risk === "high" ? "⚠️" : "💡";
    
    context += `${severityIcon} ${category}:\n`;
    
    for (const risk of risks) {
      context += `  • Detected: "${risk.match}"\n`;
      context += `  • ${risk.pattern.warningMessage}\n`;
      context += `  • Safe alternatives:\n`;
      for (const alt of risk.pattern.safeAlternatives) {
        context += `    - ${alt}\n`;
      }
    }
    context += "\n";
  }

  // Add golden rules reminder for critical operations
  if (analysis.maxRiskLevel === "critical") {
    context += "📋 GOLDEN RULES REMINDER:\n";
    context += "  1. Think before you delete. Suspend, don't delete.\n";
    context += "  2. All changes MUST go through Git (GitOps)\n";
    context += "  3. Storage resources need special handling\n";
    context += "  4. Test in development first when possible\n\n";
  }

  // Add confirmation requirement
  if (analysis.requiresConfirmation) {
    context += "⚠️ CONFIRMATION REQUIRED:\n";
    context += "This operation requires explicit confirmation due to its risk level.\n";
    context += "Please review the warnings above and confirm you understand the risks.\n\n";
  }

  context += "💡 To proceed with caution, acknowledge these risks in your request.\n";
  context += "🔄 To bypass this analysis: FORCE_PROMPT_GUARDIAN=true\n";

  return context;
}

async function injectContextMessage(context: string): Promise<void> {
  // Output the context as a user message that Claude will see
  console.log(context);
}

async function main(): Promise<void> {
  // Check for override
  if (hasOverride("FORCE_PROMPT_GUARDIAN")) {
    logger.warn("Prompt analysis bypassed via override");
    exitHook(createHookResult(true, "Prompt analysis bypassed", 0));
  }

  // Get the user prompt from environment or stdin
  const userPrompt = Deno.env.get("CLAUDE_USER_PROMPT") || "";
  
  if (!userPrompt) {
    // Try reading from stdin if available
    try {
      const decoder = new TextDecoder();
      const input = await Deno.readAll(Deno.stdin);
      const stdinPrompt = decoder.decode(input);
      if (stdinPrompt) {
        logger.info("Analyzing prompt from stdin");
        const analysis = analyzePrompt(stdinPrompt);
        if (analysis.hasRisks) {
          await processRiskyPrompt(analysis, stdinPrompt);
        }
      }
    } catch {
      // No stdin available
    }
    
    logger.info("No prompt to analyze");
    exitHook(createHookResult(true, "No prompt to analyze", 0));
  }

  logger.info(`Analyzing prompt: ${userPrompt.substring(0, 100)}...`);

  // Analyze the prompt
  const analysis = analyzePrompt(userPrompt);

  if (!analysis.hasRisks) {
    logger.info("No risks detected in prompt");
    exitHook(createHookResult(true, "✅ Prompt appears safe", 0));
  }

  await processRiskyPrompt(analysis, userPrompt);
}

async function processRiskyPrompt(analysis: PromptAnalysis, prompt: string): Promise<void> {
  logger.warn(`Risky prompt detected`, {
    riskLevel: analysis.maxRiskLevel,
    riskCount: analysis.risks.length,
    categories: [...new Set(analysis.risks.map(r => r.pattern.category))],
  });

  // Inject safety context
  await injectContextMessage(analysis.contextToInject);

  // Determine exit code based on risk level
  let exitCode: 0 | 1 | 2 = 0;
  let message = "";

  switch (analysis.maxRiskLevel) {
    case "critical":
      if (analysis.requiresConfirmation) {
        exitCode = 1; // Warning but proceed (context injected)
        message = "⚠️ Critical operation detected - safety context injected";
      } else {
        exitCode = 1;
        message = "⚠️ High-risk operation - proceed with caution";
      }
      break;
    case "high":
      exitCode = 1;
      message = "⚠️ Potentially risky operation - safety guidance provided";
      break;
    case "medium":
      exitCode = 0;
      message = "💡 Operation notes provided for safety";
      break;
    default:
      exitCode = 0;
      message = "✅ Prompt analyzed";
  }

  exitHook(createHookResult(exitCode <= 1, message, exitCode, {
    riskLevel: analysis.maxRiskLevel,
    risksDetected: analysis.risks.length,
  }));
}

if (import.meta.main) {
  main().catch((error) => {
    const logger = new HookLogger("prompt-guardian");
    logger.error("Hook execution failed", error);
    exitHook(createHookResult(false, `Hook execution failed: ${error.message}`, 2));
  });
}