#!/usr/bin/env -S deno run --allow-all

/**
 * Comprehensive Trino Integration Test Suite
 * 
 * Validates all aspects of Trino functionality including:
 * - Web UI accessibility (HTTP 406 fix verification)
 * - Query engine functionality
 * - Catalog integration
 * - Performance benchmarks
 * - Configuration validation
 */

import { Command } from "@cliffy/command";
import { Table } from "@cliffy/table";
import { colors } from "@cliffy/ansi/colors";
import { $ } from "@david/dax";

interface TestResult {
  name: string;
  category: string;
  status: "pass" | "warning" | "fail" | "error";
  duration: number;
  details?: string;
  error?: string;
  metrics?: Record<string, any>;
}

interface TestSummary {
  totalTests: number;
  passed: number;
  warnings: number;
  failed: number;
  errors: number;
  totalDuration: number;
  criticalIssues: string[];
  performanceMetrics: Record<string, number>;
}

class TrinoIntegrationTester {
  private results: TestResult[] = [];
  private verbose = false;
  private jsonOutput = false;
  private quick = false;
  private namespace = "data-platform";
  private coordinatorPod = "";
  private trinoService = "trino";
  private webUIUrl = "https://trino.walleye-monster.ts.net";

  constructor(options: { verbose?: boolean; json?: boolean; quick?: boolean } = {}) {
    this.verbose = options.verbose || false;
    this.jsonOutput = options.json || false;
    this.quick = options.quick || false;
  }

  private log(message: string): void {
    if (!this.jsonOutput) {
      console.log(message);
    }
  }

  private async findCoordinatorPod(): Promise<boolean> {
    try {
      const result = await $`kubectl get pods -n ${this.namespace} -l app.kubernetes.io/component=coordinator -o jsonpath='{.items[0].metadata.name}'`.text();
      this.coordinatorPod = result.trim();
      if (!this.coordinatorPod) {
        throw new Error("No coordinator pod found");
      }
      this.log(`📍 Found coordinator pod: ${this.coordinatorPod}`);
      return true;
    } catch (error) {
      this.log(`❌ Failed to find coordinator pod: ${error}`);
      return false;
    }
  }

  private async executeTrinoQuery(sql: string, timeout = 30): Promise<{ success: boolean; output: string; duration: number }> {
    const startTime = Date.now();
    try {
      const result = await $`timeout ${timeout}s kubectl exec -n ${this.namespace} ${this.coordinatorPod} -- trino --execute ${sql}`.text();
      const duration = Date.now() - startTime;
      return { success: true, output: result.trim(), duration };
    } catch (error) {
      const duration = Date.now() - startTime;
      return { success: false, output: String(error), duration };
    }
  }

  private async testWebUIAccess(): Promise<TestResult> {
    const startTime = Date.now();
    try {
      this.log("🌐 Testing Web UI accessibility...");
      
      // Test main UI page
      const response = await fetch(this.webUIUrl + "/ui/", {
        method: "HEAD",
        redirect: "follow"
      });
      
      const duration = Date.now() - startTime;
      
      if (response.status === 200) {
        return {
          name: "Web UI Access",
          category: "connectivity",
          status: "pass",
          duration,
          details: `HTTP ${response.status} - UI accessible`,
          metrics: { httpStatus: response.status, responseTime: duration }
        };
      } else if (response.status === 406) {
        return {
          name: "Web UI Access",
          category: "connectivity", 
          status: "fail",
          duration,
          details: "HTTP 406 - X-Forwarded-For header rejection (fix not applied)",
          error: "The HTTP 406 fix for forwarded headers is not working"
        };
      } else {
        return {
          name: "Web UI Access",
          category: "connectivity",
          status: "warning", 
          duration,
          details: `HTTP ${response.status} - Unexpected response`,
          error: `Expected 200, got ${response.status}`
        };
      }
    } catch (error) {
      return {
        name: "Web UI Access",
        category: "connectivity",
        status: "error",
        duration: Date.now() - startTime,
        error: String(error)
      };
    }
  }

  private async testBasicConnectivity(): Promise<TestResult[]> {
    const tests: TestResult[] = [];
    
    // Test 1: Pod health
    try {
      this.log("🔍 Testing coordinator pod health...");
      const startTime = Date.now();
      const podStatus = await $`kubectl get pod ${this.coordinatorPod} -n ${this.namespace} -o jsonpath='{.status.phase}'`.text();
      const duration = Date.now() - startTime;
      
      tests.push({
        name: "Coordinator Pod Health",
        category: "connectivity",
        status: podStatus.trim() === "Running" ? "pass" : "fail",
        duration,
        details: `Pod status: ${podStatus}`,
        error: podStatus.trim() !== "Running" ? "Coordinator pod not running" : undefined
      });
    } catch (error) {
      tests.push({
        name: "Coordinator Pod Health", 
        category: "connectivity",
        status: "error",
        duration: 0,
        error: String(error)
      });
    }

    // Test 2: Service connectivity  
    try {
      this.log("🔗 Testing service connectivity...");
      const startTime = Date.now();
      const serviceCheck = await $`kubectl get service ${this.trinoService} -n ${this.namespace} -o jsonpath='{.spec.clusterIP}'`.text();
      const duration = Date.now() - startTime;
      
      tests.push({
        name: "Service Connectivity",
        category: "connectivity", 
        status: serviceCheck.trim() ? "pass" : "fail",
        duration,
        details: `Service IP: ${serviceCheck}`,
        error: !serviceCheck.trim() ? "Service not found or no ClusterIP" : undefined
      });
    } catch (error) {
      tests.push({
        name: "Service Connectivity",
        category: "connectivity",
        status: "error", 
        duration: 0,
        error: String(error)
      });
    }

    return tests;
  }

  private async testBasicQueries(): Promise<TestResult[]> {
    const tests: TestResult[] = [];
    
    const basicQueries = [
      { name: "Simple SELECT", sql: "SELECT 1 as test", expectedRows: 1 },
      { name: "Current Timestamp", sql: "SELECT current_timestamp", expectedRows: 1 },
      { name: "Show Catalogs", sql: "SHOW CATALOGS", expectedRows: 3 }, // iceberg, system, tpch, tpcds expected
      { name: "System Nodes", sql: "SELECT * FROM system.runtime.nodes", expectedRows: 1 }
    ];

    for (const query of basicQueries) {
      this.log(`🧪 Testing: ${query.name}...`);
      const result = await this.executeTrinoQuery(query.sql);
      
      const lines = result.output.split('\n').filter(line => line.trim() && !line.includes('WARNING'));
      const dataLines = lines.filter(line => !line.includes('org.jline.utils.Log'));
      
      tests.push({
        name: query.name,
        category: "basic-queries",
        status: result.success && dataLines.length >= query.expectedRows ? "pass" : "fail",
        duration: result.duration,
        details: result.success ? `Returned ${dataLines.length} rows` : undefined,
        error: !result.success ? result.output : undefined,
        metrics: { executionTime: result.duration, resultRows: dataLines.length }
      });
    }

    return tests;
  }

  private async testCatalogFunctionality(): Promise<TestResult[]> {
    const tests: TestResult[] = [];

    // Test TPCH catalog
    const tpchQueries = [
      { name: "TPCH Schemas", sql: "SHOW SCHEMAS IN tpch", expectedMinRows: 2 },
      { name: "TPCH Tables", sql: "SHOW TABLES FROM tpch.tiny", expectedMinRows: 8 },
      { name: "Customer Count", sql: "SELECT COUNT(*) FROM tpch.tiny.customer", expectedMinRows: 1 },
      { name: "Nation Data", sql: "SELECT COUNT(*) FROM tpch.tiny.nation", expectedMinRows: 1 }
    ];

    for (const query of tpchQueries) {
      this.log(`📊 Testing TPCH: ${query.name}...`);
      const result = await this.executeTrinoQuery(query.sql);
      
      const lines = result.output.split('\n').filter(line => line.trim() && !line.includes('WARNING') && !line.includes('org.jline.utils.Log'));
      
      tests.push({
        name: `TPCH - ${query.name}`,
        category: "catalog-functionality",
        status: result.success && lines.length >= query.expectedMinRows ? "pass" : "fail",
        duration: result.duration,
        details: result.success ? `Query executed successfully` : undefined,
        error: !result.success ? result.output : undefined,
        metrics: { executionTime: result.duration }
      });
    }

    // Test Iceberg catalog (may not have data yet)
    this.log(`🧊 Testing Iceberg catalog...`);
    const icebergResult = await this.executeTrinoQuery("SHOW SCHEMAS IN iceberg");
    tests.push({
      name: "Iceberg Catalog Access",
      category: "catalog-functionality", 
      status: icebergResult.success ? "pass" : "warning",
      duration: icebergResult.duration,
      details: icebergResult.success ? "Iceberg catalog accessible" : "Iceberg catalog may not be configured",
      error: !icebergResult.success ? icebergResult.output : undefined,
      metrics: { executionTime: icebergResult.duration }
    });

    return tests;
  }

  private async testAdvancedQueries(): Promise<TestResult[]> {
    if (this.quick) {
      return []; // Skip advanced tests in quick mode
    }

    const tests: TestResult[] = [];

    const advancedQueries = [
      {
        name: "Complex Join Query",
        sql: `SELECT c.c_mktsegment, COUNT(*) as customers, AVG(o.o_totalprice) as avg_order_value 
              FROM tpch.tiny.customer c 
              LEFT JOIN tpch.tiny.orders o ON c.c_custkey = o.o_custkey 
              GROUP BY c.c_mktsegment 
              ORDER BY customers DESC`,
        timeout: 15
      },
      {
        name: "Window Function",
        sql: `SELECT c_name, o_totalprice, 
              ROW_NUMBER() OVER (ORDER BY o_totalprice DESC) as price_rank
              FROM tpch.tiny.customer c
              JOIN tpch.tiny.orders o ON c.c_custkey = o.o_custkey
              ORDER BY o_totalprice DESC LIMIT 5`,
        timeout: 10
      },
      {
        name: "JSON Operations", 
        sql: `SELECT CAST(ROW(c_custkey, c_name, c_mktsegment) AS JSON) as customer_json
              FROM tpch.tiny.customer LIMIT 3`,
        timeout: 10
      },
      {
        name: "Date Functions",
        sql: `SELECT EXTRACT(YEAR FROM o_orderdate) as year, COUNT(*) as orders
              FROM tpch.tiny.orders 
              GROUP BY EXTRACT(YEAR FROM o_orderdate) 
              ORDER BY year`,
        timeout: 10
      }
    ];

    for (const query of advancedQueries) {
      this.log(`🎯 Testing Advanced: ${query.name}...`);
      const result = await this.executeTrinoQuery(query.sql, query.timeout);
      
      tests.push({
        name: `Advanced - ${query.name}`,
        category: "advanced-queries",
        status: result.success ? "pass" : "warning",
        duration: result.duration,
        details: result.success ? "Complex query executed successfully" : undefined,
        error: !result.success ? result.output : undefined,
        metrics: { executionTime: result.duration, complexity: "high" }
      });
    }

    return tests;
  }

  private async testPerformanceBenchmarks(): Promise<TestResult[]> {
    const tests: TestResult[] = [];

    const benchmarks = [
      { name: "Quick SELECT", sql: "SELECT 1", maxTime: 1000 },
      { name: "Catalog Listing", sql: "SHOW CATALOGS", maxTime: 2000 },
      { name: "Small Aggregation", sql: "SELECT COUNT(*) FROM tpch.tiny.nation", maxTime: 3000 },
      { name: "Medium Aggregation", sql: "SELECT c_mktsegment, COUNT(*) FROM tpch.tiny.customer GROUP BY c_mktsegment", maxTime: 5000 }
    ];

    for (const benchmark of benchmarks) {
      this.log(`⚡ Performance test: ${benchmark.name}...`);
      const result = await this.executeTrinoQuery(benchmark.sql);
      
      const status = result.success && result.duration <= benchmark.maxTime ? "pass" : 
                    result.success ? "warning" : "fail";
      
      tests.push({
        name: `Performance - ${benchmark.name}`,
        category: "performance",
        status,
        duration: result.duration,
        details: `Executed in ${result.duration}ms (target: <${benchmark.maxTime}ms)`,
        error: !result.success ? result.output : undefined,
        metrics: { executionTime: result.duration, targetTime: benchmark.maxTime, performanceRatio: result.duration / benchmark.maxTime }
      });
    }

    return tests;
  }

  private async testConfigurationValidation(): Promise<TestResult[]> {
    const tests: TestResult[] = [];

    try {
      this.log("⚙️ Testing configuration validation...");
      
      // Check if http-server.process-forwarded is set
      const configResult = await $`kubectl get configmap trino-coordinator -n ${this.namespace} -o jsonpath='{.data.config\.properties}'`.text();
      
      const hasForwardedConfig = configResult.includes("http-server.process-forwarded=true");
      
      tests.push({
        name: "HTTP Forwarded Headers Config",
        category: "configuration",
        status: hasForwardedConfig ? "pass" : "fail", 
        duration: 0,
        details: hasForwardedConfig ? "http-server.process-forwarded=true is set" : "Missing forwarded headers configuration",
        error: !hasForwardedConfig ? "HTTP 406 fix configuration not found in ConfigMap" : undefined
      });

      // Check coordinator logs for any header rejection errors
      const logResult = await $`kubectl logs ${this.coordinatorPod} -n ${this.namespace} --tail=100`.text();
      const hasHeaderErrors = logResult.includes("X-Forwarded-For") && logResult.includes("reject");
      
      tests.push({
        name: "No Header Rejection Errors",
        category: "configuration",
        status: !hasHeaderErrors ? "pass" : "warning",
        duration: 0,
        details: !hasHeaderErrors ? "No X-Forwarded-For rejection errors in logs" : "Found header rejection errors in logs",
        error: hasHeaderErrors ? "Check coordinator logs for X-Forwarded-For rejection errors" : undefined
      });

    } catch (error) {
      tests.push({
        name: "Configuration Validation",
        category: "configuration",
        status: "error",
        duration: 0,
        error: String(error)
      });
    }

    return tests;
  }

  private generateSummary(): TestSummary {
    const summary: TestSummary = {
      totalTests: this.results.length,
      passed: this.results.filter(r => r.status === "pass").length,
      warnings: this.results.filter(r => r.status === "warning").length,
      failed: this.results.filter(r => r.status === "fail").length,
      errors: this.results.filter(r => r.status === "error").length,
      totalDuration: this.results.reduce((sum, r) => sum + r.duration, 0),
      criticalIssues: this.results.filter(r => r.status === "fail" || r.status === "error").map(r => r.name),
      performanceMetrics: {}
    };

    // Calculate performance metrics
    const perfTests = this.results.filter(r => r.category === "performance" && r.metrics?.executionTime);
    if (perfTests.length > 0) {
      summary.performanceMetrics = {
        avgQueryTime: perfTests.reduce((sum, r) => sum + (r.metrics?.executionTime || 0), 0) / perfTests.length,
        maxQueryTime: Math.max(...perfTests.map(r => r.metrics?.executionTime || 0)),
        minQueryTime: Math.min(...perfTests.map(r => r.metrics?.executionTime || 0))
      };
    }

    return summary;
  }

  private displayResults(summary: TestSummary): void {
    if (this.jsonOutput) {
      console.log(JSON.stringify({
        summary,
        results: this.results,
        timestamp: new Date().toISOString()
      }, null, 2));
      return;
    }

    // Human-readable output
    console.log("\n" + "=".repeat(60));
    console.log(colors.bold("🎯 TRINO INTEGRATION TEST RESULTS"));
    console.log("=".repeat(60));

    // Summary table
    const summaryTable = new Table()
      .header(["Metric", "Value"])
      .body([
        ["Total Tests", summary.totalTests.toString()],
        [colors.green("✅ Passed"), summary.passed.toString()],
        [colors.yellow("⚠️ Warnings"), summary.warnings.toString()],
        [colors.red("❌ Failed"), summary.failed.toString()],
        [colors.red("💥 Errors"), summary.errors.toString()],
        ["Total Duration", `${summary.totalDuration}ms`],
        ["Average Query Time", summary.performanceMetrics.avgQueryTime ? `${Math.round(summary.performanceMetrics.avgQueryTime)}ms` : "N/A"]
      ])
      .border();

    console.log("\n📊 Summary:");
    summaryTable.render();

    // Results by category
    const categories = [...new Set(this.results.map(r => r.category))];
    
    for (const category of categories) {
      const categoryResults = this.results.filter(r => r.category === category);
      console.log(`\n📋 ${category.toUpperCase().replace("-", " ")} Tests:`);
      
      const categoryTable = new Table()
        .header(["Test", "Status", "Duration", "Details"])
        .border();

      for (const result of categoryResults) {
        const statusIcon = result.status === "pass" ? "✅" : 
                          result.status === "warning" ? "⚠️" : 
                          result.status === "fail" ? "❌" : "💥";
        
        categoryTable.body([
          result.name,
          `${statusIcon} ${result.status}`,
          `${result.duration}ms`,
          result.details || result.error || ""
        ]);
      }
      
      categoryTable.render();
    }

    // Critical issues
    if (summary.criticalIssues.length > 0) {
      console.log(`\n🚨 Critical Issues:`);
      for (const issue of summary.criticalIssues) {
        console.log(`   ${colors.red("•")} ${issue}`);
      }
    }

    // Overall status
    const overallStatus = summary.failed === 0 && summary.errors === 0 ? "PASSED" :
                         summary.failed === 0 ? "PASSED (with warnings)" : "FAILED";
    
    const statusColor = summary.failed === 0 && summary.errors === 0 ? colors.green :
                       summary.failed === 0 ? colors.yellow : colors.red;
    
    console.log(`\n🎯 Overall Status: ${statusColor(overallStatus)}`);
    console.log("=".repeat(60));
  }

  async runTests(): Promise<void> {
    this.log(colors.bold("🚀 Starting Trino Integration Tests"));
    this.log("=====================================\n");

    // Initialize
    if (!await this.findCoordinatorPod()) {
      process.exit(3);
    }

    // Run test suites
    const testSuites = [
      { name: "Web UI Access", method: () => this.testWebUIAccess().then(r => [r]) },
      { name: "Basic Connectivity", method: () => this.testBasicConnectivity() },
      { name: "Basic Queries", method: () => this.testBasicQueries() },
      { name: "Catalog Functionality", method: () => this.testCatalogFunctionality() },
      { name: "Advanced Queries", method: () => this.testAdvancedQueries() },
      { name: "Performance Benchmarks", method: () => this.testPerformanceBenchmarks() },
      { name: "Configuration Validation", method: () => this.testConfigurationValidation() }
    ];

    for (const suite of testSuites) {
      this.log(`\n🧪 Running ${suite.name} tests...`);
      try {
        const results = await suite.method();
        this.results.push(...results);
      } catch (error) {
        this.log(`❌ Error in ${suite.name}: ${error}`);
        this.results.push({
          name: suite.name,
          category: "error",
          status: "error",
          duration: 0,
          error: String(error)
        });
      }
    }

    // Generate and display results
    const summary = this.generateSummary();
    this.displayResults(summary);

    // Set exit code
    const exitCode = summary.errors > 0 ? 3 : 
                    summary.failed > 0 ? 2 : 
                    summary.warnings > 0 ? 1 : 0;
    
    process.exit(exitCode);
  }
}

// CLI Interface
const { options } = await new Command()
  .name("test-trino-integration")
  .description("Comprehensive Trino integration test suite")
  .version("1.0.0")
  .option("-v, --verbose", "Enable verbose output")
  .option("-j, --json", "Output results in JSON format")
  .option("-q, --quick", "Run quick tests only (skip advanced queries)")
  .parse(Deno.args);

// Run tests
const tester = new TrinoIntegrationTester({
  verbose: options.verbose,
  json: options.json,
  quick: options.quick
});

await tester.runTests();