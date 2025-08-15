#!/usr/bin/env deno run --allow-all
/**
 * Manifest Validator Hook
 * Validates Kubernetes manifests before write operations
 * Prevents invalid configurations from being written
 */

import {
  HookLogger,
  HookResult,
  createHookResult,
  exitHook,
  hasOverride,
  isKubernetesFile,
  isValidYaml,
  hasKubernetesApiVersion,
  runCommand,
} from "./hook-utils.ts";

const logger = new HookLogger("manifest-validator");

interface ValidationResult {
  file: string;
  valid: boolean;
  errors: string[];
  warnings: string[];
}

async function validateYamlSyntax(filePath: string, content: string): Promise<ValidationResult> {
  const result: ValidationResult = {
    file: filePath,
    valid: true,
    errors: [],
    warnings: [],
  };

  // Check YAML syntax
  const yamlCheck = isValidYaml(content);
  if (!yamlCheck.valid) {
    result.valid = false;
    result.errors.push(`Invalid YAML syntax: ${yamlCheck.error}`);
    return result;
  }

  // Skip non-Kubernetes files
  if (!hasKubernetesApiVersion(content)) {
    logger.info(`Skipping non-Kubernetes file: ${filePath}`);
    return result;
  }

  logger.info(`Validating Kubernetes manifest: ${filePath}`);

  // Check for Flux v2 anti-patterns
  if (content.includes("retryInterval:")) {
    result.valid = false;
    result.errors.push("retryInterval field is not supported in Flux v2 - remove this field");
  }

  // Check for missing namespace in kustomization.yaml
  if (filePath.endsWith("kustomization.yaml") && !content.includes("namespace:")) {
    result.warnings.push("kustomization.yaml should specify a namespace");
  }

  // Check for proper sourceRef namespace
  if (content.includes("sourceRef:") && content.includes("kind: GitRepository")) {
    if (!content.includes("namespace: flux-system")) {
      result.warnings.push("GitRepository sourceRef should reference flux-system namespace");
    }
  }

  // Check HelmRelease dependencies reference correct namespaces
  if (content.includes("dependsOn:")) {
    const lines = content.split("\n");
    let inDependsOn = false;
    for (const line of lines) {
      if (line.trim().startsWith("dependsOn:")) {
        inDependsOn = true;
        continue;
      }
      if (inDependsOn && line.trim().startsWith("namespace: flux-system")) {
        result.warnings.push("dependsOn should reference actual namespace, not flux-system (unless dependency is really in flux-system)");
      }
      if (inDependsOn && line.trim() && !line.trim().startsWith("-") && !line.trim().startsWith("name:") && !line.trim().startsWith("namespace:")) {
        inDependsOn = false;
      }
    }
  }

  return result;
}

async function validateWithKubeconform(filePath: string): Promise<ValidationResult> {
  const result: ValidationResult = {
    file: filePath,
    valid: true,
    errors: [],
    warnings: [],
  };

  try {
    // Check if kubeconform is available
    const kubeconformCheck = await runCommand(["which", "kubeconform"]);
    if (!kubeconformCheck.success) {
      result.warnings.push("kubeconform not found - skipping schema validation");
      return result;
    }

    // Run kubeconform validation
    const kubeconformResult = await runCommand([
      "kubeconform",
      "-strict",
      "-ignore-missing-schemas",
      "-schema-location", "default",
      "-schema-location", "https://raw.githubusercontent.com/fluxcd/flux2/main/manifests/schemas",
      filePath,
    ]);

    if (!kubeconformResult.success) {
      result.valid = false;
      result.errors.push(`Schema validation failed: ${kubeconformResult.error}`);
    }
  } catch (error) {
    result.warnings.push(`kubeconform validation error: ${error.message}`);
  }

  return result;
}

async function validateHelmRelease(filePath: string, content: string): Promise<ValidationResult> {
  const result: ValidationResult = {
    file: filePath,
    valid: true,
    errors: [],
    warnings: [],
  };

  if (!content.includes("kind: HelmRelease")) {
    return result;
  }

  logger.info(`Validating HelmRelease: ${filePath}`);

  // Check for required fields
  if (!content.includes("chart:")) {
    result.errors.push("HelmRelease missing chart specification");
    result.valid = false;
  }

  if (!content.includes("sourceRef:")) {
    result.errors.push("HelmRelease missing sourceRef");
    result.valid = false;
  }

  // Check for resource limits recommendation
  if (!content.includes("resources:")) {
    result.warnings.push("Consider adding resource requests/limits to HelmRelease values");
  }

  // Check for infinite retries (anti-pattern)
  if (content.includes("retries: -1")) {
    result.warnings.push("Infinite retries (retries: -1) can cause resource exhaustion - use finite retries");
  }

  return result;
}

async function validateFluxKustomization(filePath: string, content: string): Promise<ValidationResult> {
  const result: ValidationResult = {
    file: filePath,
    valid: true,
    errors: [],
    warnings: [],
  };

  if (!content.includes("kind: Kustomization") || !content.includes("kustomize.toolkit.fluxcd.io")) {
    return result;
  }

  logger.info(`Validating Flux Kustomization: ${filePath}`);

  // Check for required fields
  if (!content.includes("path:")) {
    result.errors.push("Flux Kustomization missing path specification");
    result.valid = false;
  }

  if (!content.includes("sourceRef:")) {
    result.errors.push("Flux Kustomization missing sourceRef");
    result.valid = false;
  }

  // Check for recommended fields
  if (!content.includes("prune: true")) {
    result.warnings.push("Consider enabling pruning (prune: true) for Flux Kustomizations");
  }

  if (!content.includes("wait: true")) {
    result.warnings.push("Consider enabling wait (wait: true) for dependency ordering");
  }

  return result;
}

async function validateManifest(filePath: string): Promise<ValidationResult[]> {
  const results: ValidationResult[] = [];

  try {
    // Read file content
    const content = await Deno.readTextFile(filePath);
    
    // Run all validations
    results.push(await validateYamlSyntax(filePath, content));
    results.push(await validateWithKubeconform(filePath));
    results.push(await validateHelmRelease(filePath, content));
    results.push(await validateFluxKustomization(filePath, content));

  } catch (error) {
    results.push({
      file: filePath,
      valid: false,
      errors: [`Failed to read file: ${error.message}`],
      warnings: [],
    });
  }

  return results;
}

async function main(): Promise<void> {
  // Check for override
  if (hasOverride("FORCE_MANIFEST_VALIDATION")) {
    logger.info("Manifest validation bypassed via FORCE_MANIFEST_VALIDATION");
    exitHook(createHookResult(true, "Validation bypassed", 0));
  }

  // Get target file from environment or args
  const targetFile = Deno.env.get("CLAUDE_TARGET_FILE") || Deno.args[0];
  
  if (!targetFile) {
    logger.warn("No target file specified");
    exitHook(createHookResult(true, "No file to validate", 0));
  }

  logger.info(`Validating file: ${targetFile}`);

  // Skip non-Kubernetes files
  if (!isKubernetesFile(targetFile)) {
    logger.info("Non-Kubernetes file, skipping validation");
    exitHook(createHookResult(true, "Non-Kubernetes file", 0));
  }

  // Validate the manifest
  const validationResults = await validateManifest(targetFile);
  
  // Aggregate results
  let hasErrors = false;
  let hasWarnings = false;
  const allErrors: string[] = [];
  const allWarnings: string[] = [];

  for (const result of validationResults) {
    if (!result.valid) {
      hasErrors = true;
      allErrors.push(...result.errors);
    }
    if (result.warnings.length > 0) {
      hasWarnings = true;
      allWarnings.push(...result.warnings);
    }
  }

  // Log results
  if (hasErrors) {
    logger.error("Validation failed", { file: targetFile, errors: allErrors });
  }
  if (hasWarnings) {
    logger.warn("Validation warnings", { file: targetFile, warnings: allWarnings });
  }

  // Determine exit result
  if (hasErrors) {
    const errorMessage = `Manifest validation failed:\n${allErrors.map(e => `  ❌ ${e}`).join('\n')}`;
    exitHook(createHookResult(false, errorMessage, 2, { errors: allErrors }));
  } else if (hasWarnings) {
    const warningMessage = `Manifest has warnings:\n${allWarnings.map(w => `  ⚠️  ${w}`).join('\n')}`;
    exitHook(createHookResult(true, warningMessage, 1, { warnings: allWarnings }));
  } else {
    exitHook(createHookResult(true, "Manifest validation passed", 0));
  }
}

if (import.meta.main) {
  main().catch((error) => {
    const logger = new HookLogger("manifest-validator");
    logger.error("Hook execution failed", error);
    exitHook(createHookResult(false, `Hook execution failed: ${error.message}`, 2));
  });
}