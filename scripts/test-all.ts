#!/usr/bin/env -S deno run --allow-all

import { Command } from "@cliffy/command";
import { Table } from "@cliffy/table";
import { colors } from "@cliffy/ansi/colors";
import { $ } from "@david/dax";

interface TestResult {
  name: string;
  category: string;
  status: "pass" | "warning" | "fail" | "error";
  exitCode: number;
  duration: number; // milliseconds
  output?: string;
  issues?: string[];
}

interface TestSuite {
  name: string;
  script: string;
  category: "flux" | "hardware" | "health" | "network" | "storage";
  args?: string[];
  timeout?: number; // seconds
  critical?: boolean; // If true, failure blocks other tests
}

interface TestSummary {
  totalTests: number;
  passed: number;
  warnings: number;
  failed: number;
  errors: number;
  totalDuration: number;
  criticalIssues: string[];
}

class UnifiedTestRunner {
  private results: TestResult[] = [];
  private verbose = false;
  private quick = false;
  private ci = false;
  private failFast = false;

  // Define all available test suites
  private readonly testSuites: TestSuite[] = [
    // Flux/GitOps Tests
    {
      name: "Flux Configuration",
      script: "check-flux-config.ts",
      category: "flux",
      critical: true,
    },
    {
      name: "Flux Deployment Status",
      script: "flux-deployment-check.ts", 
      category: "flux",
      args: ["--timeout", "30"],
      critical: true,
    },
    
    // Hardware Tests
    {
      name: "Hardware Inventory",
      script: "hardware-inventory.ts",
      category: "hardware",
      timeout: 60,
    },
    {
      name: "Talos Configuration Validation",
      script: "validate-talos-config.ts",
      category: "hardware",
      critical: true,
    },
    {
      name: "Hardware Change Detection",
      script: "detect-hardware-changes.ts",
      category: "hardware",
    },
    
    // Health Tests
    {
      name: "Cluster Health Monitor",
      script: "cluster-health-monitor.ts",
      category: "health",
      args: ["--critical-only"],
      critical: true,
    },
    {
      name: "Kubernetes Health Check",
      script: "k8s-health-check.ts",
      category: "health",
      args: ["--verbose"],
      critical: true,
    },
    
    // Storage Tests
    {
      name: "Storage Health Check",
      script: "storage-health-check.ts",
      category: "storage",
      args: ["--growth-analysis"],
      critical: true,
    },
    
    // Network Tests
    {
      name: "Network Basic Check",
      script: "network-monitor.ts",
      category: "network",
      critical: true,
    },
    {
      name: "Network Full Check",
      script: "network-monitor.ts",
      category: "network",
      args: ["--check-dns", "--check-endpoints"],
    },
  ];

  constructor(verbose = false, quick = false, ci = false, failFast = false) {
    this.verbose = verbose;
    this.quick = quick;
    this.ci = ci;
    this.failFast = failFast;
  }

  async runAllTests(): Promise<void> {
    console.log(colors.bold.blue("🧪 Unified Homelab Test Suite"));
    console.log("=" . repeat(50));
    
    const suitesToRun = this.quick 
      ? this.testSuites.filter(s => s.critical)
      : this.testSuites;

    if (this.quick) {
      console.log(colors.yellow("📋 Running critical tests only (quick mode)"));
    } else {
      console.log(`📋 Running ${suitesToRun.length} test suites`);
    }
    
    console.log("");

    const startTime = Date.now();
    
    for (let i = 0; i < suitesToRun.length; i++) {
      const suite = suitesToRun[i];
      const result = await this.runTest(suite, i + 1, suitesToRun.length);
      this.results.push(result);
      
      // Fail fast on critical test failures
      if (this.failFast && suite.critical && result.status === "fail") {
        console.log(colors.bold.red(`💥 Critical test failed: ${suite.name}`));
        console.log(colors.red("   Stopping execution due to --fail-fast"));
        break;
      }
      
      // Add spacing between tests in verbose mode
      if (this.verbose && i < suitesToRun.length - 1) {
        console.log("");
      }
    }
    
    const totalDuration = Date.now() - startTime;
    
    // Display summary
    this.displaySummary(totalDuration);
    
    // Exit with appropriate code
    const summary = this.calculateSummary();
    if (summary.failed > 0 || summary.criticalIssues.length > 0) {
      Deno.exit(1);
    } else if (summary.warnings > 0) {
      Deno.exit(this.ci ? 1 : 0); // Warnings fail in CI
    }
  }

  private async runTest(suite: TestSuite, index: number, total: number): Promise<TestResult> {
    const startTime = Date.now();
    const prefix = `[${index}/${total}]`;
    
    if (!this.ci) {
      process.stdout.write(`${prefix} ${suite.name}... `);
    }

    try {
      // Build command
      const args = ["deno", "run", "--allow-all", `scripts/${suite.script}`];
      if (suite.args) {
        args.push(...suite.args);
      }

      // Run with timeout
      const timeout = (suite.timeout || 120) * 1000; // Convert to ms
      const cmd = $`${args}`.timeout(timeout);
      
      let output = "";
      let exitCode = 0;
      
      try {
        if (this.verbose) {
          // Stream output in verbose mode
          const result = await cmd.text();
          output = result;
          exitCode = 0;
        } else {
          // Capture output silently
          const proc = cmd.noThrow();
          output = await proc.text();
          exitCode = proc.code || 0;
        }
      } catch (error) {
        exitCode = 1;
        output = error.message;
        if (error.message.includes("No such file")) {
          output = `Script not found: scripts/${suite.script}`;
        }
      }

      const duration = Date.now() - startTime;
      const status = this.determineStatus(exitCode, output);
      const issues = this.extractIssues(output);

      const result: TestResult = {
        name: suite.name,
        category: suite.category,
        status,
        exitCode,
        duration,
        output: this.verbose ? output : undefined,
        issues,
      };

      // Display result
      if (!this.ci) {
        this.displayTestResult(result, duration);
      } else {
        // CI mode: compact output
        const statusIcon = this.getStatusIcon(status);
        console.log(`${prefix} ${statusIcon} ${suite.name} (${duration}ms)`);
      }

      if (this.verbose && output) {
        console.log(colors.gray("   Output:"));
        console.log(colors.gray(output.split('\n').map(line => `   ${line}`).join('\n')));
      }

      return result;
    } catch (error) {
      const duration = Date.now() - startTime;
      const result: TestResult = {
        name: suite.name,
        category: suite.category,
        status: "error",
        exitCode: -1,
        duration,
        output: error.message,
      };

      if (!this.ci) {
        this.displayTestResult(result, duration);
      }

      return result;
    }
  }

  private determineStatus(exitCode: number, output: string): TestResult["status"] {
    if (exitCode === 0) {
      // Check for warnings in output
      if (output.toLowerCase().includes("warning") || output.includes("⚠️")) {
        return "warning";
      }
      return "pass";
    } else if (exitCode === 1) {
      // Exit code 1 could be warnings or failures
      if (output.toLowerCase().includes("critical") || output.toLowerCase().includes("error")) {
        return "fail";
      }
      return "warning";
    } else {
      return "fail";
    }
  }

  private extractIssues(output: string): string[] {
    const issues: string[] = [];
    const lines = output.split('\n');
    
    for (const line of lines) {
      if (line.includes('⚠️') || line.includes('❌') || line.includes('💥')) {
        // Extract issue description, removing ANSI codes
        const cleanLine = line.replace(/\x1b\[[0-9;]*m/g, '').trim();
        if (cleanLine) {
          issues.push(cleanLine);
        }
      }
    }
    
    return issues;
  }

  private displayTestResult(result: TestResult, duration: number): void {
    const statusIcon = this.getStatusIcon(result.status);
    const durationStr = `${duration}ms`;
    console.log(`${statusIcon} ${colors.gray(durationStr)}`);
    
    if (result.issues && result.issues.length > 0) {
      for (const issue of result.issues.slice(0, 3)) { // Show max 3 issues
        console.log(colors.gray(`   ${issue}`));
      }
      if (result.issues.length > 3) {
        console.log(colors.gray(`   ... and ${result.issues.length - 3} more issues`));
      }
    }
  }

  private getStatusIcon(status: TestResult["status"]): string {
    switch (status) {
      case "pass":
        return colors.green("✅");
      case "warning":
        return colors.yellow("⚠️");
      case "fail":
        return colors.red("❌");
      case "error":
        return colors.red("💥");
    }
  }

  private displaySummary(totalDuration: number): void {
    console.log("");
    console.log(colors.bold("📊 Test Summary"));
    console.log("=" . repeat(30));
    
    const summary = this.calculateSummary();
    summary.totalDuration = totalDuration;
    
    // Overall status
    let overallStatus = "PASS";
    let statusColor = colors.green;
    if (summary.failed > 0 || summary.criticalIssues.length > 0) {
      overallStatus = "FAIL";
      statusColor = colors.red;
    } else if (summary.warnings > 0) {
      overallStatus = "WARNINGS";
      statusColor = colors.yellow;
    }
    
    console.log(`Overall Status: ${statusColor(overallStatus)}`);
    console.log(`Total Duration: ${Math.round(totalDuration / 1000)}s`);
    console.log("");
    
    // Results by category
    const byCategory = this.groupByCategory();
    const table = new Table()
      .header(["Category", "Pass", "Warning", "Fail", "Error"])
      .body(
        Object.entries(byCategory).map(([category, results]) => [
          category.charAt(0).toUpperCase() + category.slice(1),
          results.filter(r => r.status === "pass").length.toString(),
          results.filter(r => r.status === "warning").length.toString(),
          results.filter(r => r.status === "fail").length.toString(),
          results.filter(r => r.status === "error").length.toString(),
        ])
      )
      .padding(1)
      .border(true);
      
    console.log(table.toString());
    
    // Critical issues
    if (summary.criticalIssues.length > 0) {
      console.log(colors.bold.red("🚨 Critical Issues:"));
      for (const issue of summary.criticalIssues) {
        console.log(colors.red(`   - ${issue}`));
      }
    }
    
    // Failed tests
    const failedTests = this.results.filter(r => r.status === "fail" || r.status === "error");
    if (failedTests.length > 0) {
      console.log(colors.bold.red("❌ Failed Tests:"));
      for (const test of failedTests) {
        console.log(colors.red(`   - ${test.name}: ${test.status}`));
      }
    }
  }

  private calculateSummary(): TestSummary {
    const passed = this.results.filter(r => r.status === "pass").length;
    const warnings = this.results.filter(r => r.status === "warning").length;
    const failed = this.results.filter(r => r.status === "fail").length;
    const errors = this.results.filter(r => r.status === "error").length;
    
    const criticalIssues: string[] = [];
    for (const result of this.results) {
      if (result.status === "fail" || result.status === "error") {
        criticalIssues.push(`${result.name}: ${result.status}`);
      }
    }
    
    return {
      totalTests: this.results.length,
      passed,
      warnings,
      failed: failed + errors,
      errors,
      totalDuration: 0, // Set by caller
      criticalIssues,
    };
  }

  private groupByCategory(): Record<string, TestResult[]> {
    return this.results.reduce((acc, result) => {
      if (!acc[result.category]) {
        acc[result.category] = [];
      }
      acc[result.category].push(result);
      return acc;
    }, {} as Record<string, TestResult[]>);
  }
}

// CLI setup
const command = new Command()
  .name("test-all")
  .version("1.0.0")
  .description("Run unified homelab test suite covering all monitoring scripts")
  .option("-v, --verbose", "Enable verbose output showing test details")
  .option("-q, --quick", "Run only critical tests for faster feedback")
  .option("--ci", "CI mode: compact output, warnings fail")
  .option("--fail-fast", "Stop on first critical test failure")
  .action(async (options) => {
    const runner = new UnifiedTestRunner(
      options.verbose,
      options.quick,
      options.ci,
      options.failFast,
    );
    await runner.runAllTests();
  });

if (import.meta.main) {
  await command.parse(Deno.args);
}