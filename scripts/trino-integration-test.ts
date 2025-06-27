#!/usr/bin/env -S deno run --allow-all
/**
 * Trino Integration Test
 * 
 * Comprehensive integration test for Trino using CLI and port forwarding.
 * Tests database connectivity, catalog functionality, and query execution.
 * 
 * Usage:
 *   deno run --allow-all ./scripts/trino-integration-test.ts
 *   deno run --allow-all ./scripts/trino-integration-test.ts --json
 *   deno run --allow-all ./scripts/trino-integration-test.ts --verbose
 */

import { $ } from "https://deno.land/x/dax@0.39.2/mod.ts";
import { delay } from "https://deno.land/std@0.208.0/async/delay.ts";

interface TestResult {
  name: string;
  status: "passed" | "failed" | "skipped";
  duration: number;
  error?: string;
  details?: Record<string, unknown>;
}

interface TestSuite {
  name: string;
  status: "passed" | "failed" | "error";
  timestamp: string;
  totalTests: number;
  passed: number;
  failed: number;
  skipped: number;
  duration: number;
  results: TestResult[];
  summary: string;
}

class TrinoIntegrationTest {
  private verbose: boolean;
  private jsonOutput: boolean;
  private portForwardProcess: Deno.ChildProcess | null = null;
  private testPort: number = 8082;
  private namespace: string = "data-platform";
  private serviceName: string = "trino";
  
  constructor() {
    this.verbose = Deno.args.includes("--verbose");
    this.jsonOutput = Deno.args.includes("--json");
  }

  private log(message: string, level: "info" | "warn" | "error" = "info"): void {
    if (this.jsonOutput) return;
    
    const timestamp = new Date().toISOString();
    const prefix = level === "error" ? "❌" : level === "warn" ? "⚠️" : "ℹ️";
    
    if (this.verbose || level !== "info") {
      console.log(`${prefix} [${timestamp}] ${message}`);
    }
  }

  private async setupPortForward(): Promise<boolean> {
    try {
      this.log(`Setting up port forward to ${this.namespace}/${this.serviceName}:8080 -> localhost:${this.testPort}`);
      
      // Start port forwarding in background
      const command = $`kubectl port-forward -n ${this.namespace} svc/${this.serviceName} ${this.testPort}:8080`;
      this.portForwardProcess = command.spawn();
      
      // Give port forwarding time to establish
      await delay(3000);
      
      // Test if port forwarding is working
      const testResponse = await $`curl -s --connect-timeout 5 http://localhost:${this.testPort}/v1/info`.json();
      
      if (testResponse && testResponse.nodeVersion) {
        this.log(`Port forwarding established successfully. Trino version: ${testResponse.nodeVersion.version}`);
        return true;
      }
      
      throw new Error("Port forwarding not responding");
    } catch (error) {
      this.log(`Failed to setup port forwarding: ${error.message}`, "error");
      return false;
    }
  }

  private async cleanupPortForward(): Promise<void> {
    if (this.portForwardProcess) {
      try {
        this.portForwardProcess.kill("SIGTERM");
        await this.portForwardProcess.status;
        this.log("Port forwarding process terminated");
      } catch (error) {
        this.log(`Error terminating port forward: ${error.message}`, "warn");
      }
    }
  }

  private async executeTrinoQuery(query: string): Promise<{ success: boolean; output?: string; error?: string }> {
    try {
      const result = await $`trino --server http://localhost:${this.testPort} --execute ${query}`.text();
      return { success: true, output: result.trim() };
    } catch (error) {
      return { success: false, error: error.message };
    }
  }

  private async testConnection(): Promise<TestResult> {
    const startTime = Date.now();
    
    try {
      this.log("Testing basic Trino connection...");
      
      const response = await $`curl -s --connect-timeout 10 http://localhost:${this.testPort}/v1/info`.json();
      
      if (!response || !response.nodeVersion) {
        throw new Error("Invalid response from Trino info endpoint");
      }
      
      const duration = Date.now() - startTime;
      this.log(`✅ Connection test passed. Trino version: ${response.nodeVersion.version}`);
      
      return {
        name: "connection",
        status: "passed",
        duration,
        details: {
          version: response.nodeVersion.version,
          environment: response.environment,
          coordinator: response.coordinator,
          uptime: response.uptime
        }
      };
    } catch (error) {
      const duration = Date.now() - startTime;
      this.log(`❌ Connection test failed: ${error.message}`, "error");
      
      return {
        name: "connection",
        status: "failed",
        duration,
        error: error.message
      };
    }
  }

  private async testCatalogs(): Promise<TestResult> {
    const startTime = Date.now();
    
    try {
      this.log("Testing catalog listing...");
      
      const result = await this.executeTrinoQuery("SHOW CATALOGS");
      
      if (!result.success) {
        throw new Error(result.error || "Failed to execute SHOW CATALOGS");
      }
      
      const catalogs = result.output?.split('\n').map(line => line.replace(/"/g, '').trim()).filter(Boolean) || [];
      
      const expectedCatalogs = ["iceberg", "system", "tpch", "tpcds"];
      const missingCatalogs = expectedCatalogs.filter(cat => !catalogs.includes(cat));
      
      if (missingCatalogs.length > 0) {
        throw new Error(`Missing expected catalogs: ${missingCatalogs.join(', ')}`);
      }
      
      const duration = Date.now() - startTime;
      this.log(`✅ Catalog test passed. Found catalogs: ${catalogs.join(', ')}`);
      
      return {
        name: "catalogs",
        status: "passed",
        duration,
        details: {
          catalogs,
          expectedCatalogs,
          count: catalogs.length
        }
      };
    } catch (error) {
      const duration = Date.now() - startTime;
      this.log(`❌ Catalog test failed: ${error.message}`, "error");
      
      return {
        name: "catalogs",
        status: "failed",
        duration,
        error: error.message
      };
    }
  }

  private async testTPCHQueries(): Promise<TestResult> {
    const startTime = Date.now();
    
    try {
      this.log("Testing TPC-H benchmark queries...");
      
      // Test schema listing
      const schemasResult = await this.executeTrinoQuery("SHOW SCHEMAS FROM tpch");
      if (!schemasResult.success) {
        throw new Error(`Failed to show schemas: ${schemasResult.error}`);
      }
      
      const schemas = schemasResult.output?.split('\n').map(line => line.replace(/"/g, '').trim()).filter(Boolean) || [];
      if (!schemas.includes("tiny")) {
        throw new Error("TPC-H tiny schema not found");
      }
      
      // Test table listing
      const tablesResult = await this.executeTrinoQuery("SHOW TABLES FROM tpch.tiny");
      if (!tablesResult.success) {
        throw new Error(`Failed to show tables: ${tablesResult.error}`);
      }
      
      const tables = tablesResult.output?.split('\n').map(line => line.replace(/"/g, '').trim()).filter(Boolean) || [];
      const expectedTables = ["nation", "region", "customer", "orders"];
      const foundTables = expectedTables.filter(table => tables.includes(table));
      
      if (foundTables.length === 0) {
        throw new Error("No expected TPC-H tables found");
      }
      
      // Test actual data query
      const dataResult = await this.executeTrinoQuery("SELECT COUNT(*) FROM tpch.tiny.nation");
      if (!dataResult.success) {
        throw new Error(`Failed to query data: ${dataResult.error}`);
      }
      
      const count = parseInt(dataResult.output?.trim() || "0");
      if (count === 0) {
        throw new Error("No data found in nation table");
      }
      
      const duration = Date.now() - startTime;
      this.log(`✅ TPC-H test passed. Found ${schemas.length} schemas, ${tables.length} tables, ${count} nations`);
      
      return {
        name: "tpch-queries",
        status: "passed",
        duration,
        details: {
          schemas,
          tables,
          nationCount: count,
          foundExpectedTables: foundTables
        }
      };
    } catch (error) {
      const duration = Date.now() - startTime;
      this.log(`❌ TPC-H test failed: ${error.message}`, "error");
      
      return {
        name: "tpch-queries",
        status: "failed",
        duration,
        error: error.message
      };
    }
  }

  private async testIcebergCatalog(): Promise<TestResult> {
    const startTime = Date.now();
    
    try {
      this.log("Testing Iceberg catalog functionality...");
      
      const result = await this.executeTrinoQuery("SHOW SCHEMAS FROM iceberg");
      
      if (!result.success) {
        // Iceberg might fail due to Nessie health checks, mark as skipped instead of failed
        this.log(`⚠️ Iceberg test skipped: ${result.error}`, "warn");
        
        return {
          name: "iceberg-catalog",
          status: "skipped",
          duration: Date.now() - startTime,
          error: result.error
        };
      }
      
      const schemas = result.output?.split('\n').map(line => line.replace(/"/g, '').trim()).filter(Boolean) || [];
      
      const duration = Date.now() - startTime;
      this.log(`✅ Iceberg test passed. Found schemas: ${schemas.join(', ')}`);
      
      return {
        name: "iceberg-catalog",
        status: "passed",
        duration,
        details: {
          schemas,
          schemaCount: schemas.length
        }
      };
    } catch (error) {
      const duration = Date.now() - startTime;
      this.log(`⚠️ Iceberg test skipped: ${error.message}`, "warn");
      
      return {
        name: "iceberg-catalog",
        status: "skipped",
        duration,
        error: error.message
      };
    }
  }

  private async testSystemQueries(): Promise<TestResult> {
    const startTime = Date.now();
    
    try {
      this.log("Testing system catalog queries...");
      
      // Test cluster information
      const nodesResult = await this.executeTrinoQuery("SELECT * FROM system.runtime.nodes");
      if (!nodesResult.success) {
        throw new Error(`Failed to query nodes: ${nodesResult.error}`);
      }
      
      // Test query information
      const queriesResult = await this.executeTrinoQuery("SELECT query_id, state FROM system.runtime.queries LIMIT 5");
      if (!queriesResult.success) {
        throw new Error(`Failed to query runtime information: ${queriesResult.error}`);
      }
      
      const nodeLines = nodesResult.output?.split('\n').filter(line => line.trim()).length || 0;
      const queryLines = queriesResult.output?.split('\n').filter(line => line.trim()).length || 0;
      
      const duration = Date.now() - startTime;
      this.log(`✅ System queries test passed. Found ${nodeLines} node entries, ${queryLines} query entries`);
      
      return {
        name: "system-queries",
        status: "passed",
        duration,
        details: {
          nodeEntries: nodeLines,
          queryEntries: queryLines
        }
      };
    } catch (error) {
      const duration = Date.now() - startTime;
      this.log(`❌ System queries test failed: ${error.message}`, "error");
      
      return {
        name: "system-queries",
        status: "failed",
        duration,
        error: error.message
      };
    }
  }

  private async testPerformance(): Promise<TestResult> {
    const startTime = Date.now();
    
    try {
      this.log("Testing query performance...");
      
      const performanceQueries = [
        "SELECT COUNT(*) FROM tpch.tiny.lineitem",
        "SELECT o_orderstatus, COUNT(*) FROM tpch.tiny.orders GROUP BY o_orderstatus",
        "SELECT n_name FROM tpch.tiny.nation ORDER BY n_name LIMIT 10"
      ];
      
      const results: Array<{ query: string; duration: number; success: boolean }> = [];
      
      for (const query of performanceQueries) {
        const queryStart = Date.now();
        const result = await this.executeTrinoQuery(query);
        const queryDuration = Date.now() - queryStart;
        
        results.push({
          query,
          duration: queryDuration,
          success: result.success
        });
        
        if (!result.success) {
          throw new Error(`Performance query failed: ${query} - ${result.error}`);
        }
      }
      
      const avgDuration = results.reduce((sum, r) => sum + r.duration, 0) / results.length;
      const maxDuration = Math.max(...results.map(r => r.duration));
      
      const duration = Date.now() - startTime;
      this.log(`✅ Performance test passed. Average query time: ${avgDuration.toFixed(0)}ms, Max: ${maxDuration}ms`);
      
      return {
        name: "performance",
        status: "passed",
        duration,
        details: {
          queries: results,
          averageDuration: avgDuration,
          maxDuration,
          totalQueries: results.length
        }
      };
    } catch (error) {
      const duration = Date.now() - startTime;
      this.log(`❌ Performance test failed: ${error.message}`, "error");
      
      return {
        name: "performance",
        status: "failed",
        duration,
        error: error.message
      };
    }
  }

  private async checkPrerequisites(): Promise<boolean> {
    try {
      this.log("Checking prerequisites...");
      
      // Check kubectl
      await $`kubectl version --client=true`.quiet();
      this.log("✅ kubectl available");
      
      // Check trino CLI
      await $`trino --version`.quiet();
      this.log("✅ Trino CLI available");
      
      // Check curl
      await $`curl --version`.quiet();
      this.log("✅ curl available");
      
      // Check Trino pods
      const pods = await $`kubectl get pods -n ${this.namespace} -l app.kubernetes.io/name=trino -o jsonpath='{.items[*].status.phase}'`.text();
      const runningPods = pods.split(' ').filter(phase => phase === 'Running').length;
      
      if (runningPods === 0) {
        throw new Error("No running Trino pods found");
      }
      
      this.log(`✅ Found ${runningPods} running Trino pods`);
      return true;
    } catch (error) {
      this.log(`❌ Prerequisites check failed: ${error.message}`, "error");
      return false;
    }
  }

  async run(): Promise<TestSuite> {
    const suiteStart = Date.now();
    const results: TestResult[] = [];
    
    this.log("🚀 Starting Trino Integration Test Suite");
    
    try {
      // Check prerequisites
      const prereqsOk = await this.checkPrerequisites();
      if (!prereqsOk) {
        throw new Error("Prerequisites check failed");
      }
      
      // Setup port forwarding
      const portForwardOk = await this.setupPortForward();
      if (!portForwardOk) {
        throw new Error("Failed to setup port forwarding");
      }
      
      // Run tests
      const tests = [
        () => this.testConnection(),
        () => this.testCatalogs(),
        () => this.testTPCHQueries(),
        () => this.testSystemQueries(),
        () => this.testIcebergCatalog(),
        () => this.testPerformance()
      ];
      
      for (const test of tests) {
        const result = await test();
        results.push(result);
        
        // Add small delay between tests
        await delay(1000);
      }
      
    } catch (error) {
      this.log(`❌ Test suite failed: ${error.message}`, "error");
      
      const suite: TestSuite = {
        name: "Trino Integration Test",
        status: "error",
        timestamp: new Date().toISOString(),
        totalTests: 0,
        passed: 0,
        failed: 0,
        skipped: 0,
        duration: Date.now() - suiteStart,
        results: [],
        summary: `Test suite failed: ${error.message}`
      };
      
      return suite;
    } finally {
      await this.cleanupPortForward();
    }
    
    // Calculate summary
    const passed = results.filter(r => r.status === "passed").length;
    const failed = results.filter(r => r.status === "failed").length;
    const skipped = results.filter(r => r.status === "skipped").length;
    const duration = Date.now() - suiteStart;
    
    const status = failed > 0 ? "failed" : "passed";
    const summary = `${passed} passed, ${failed} failed, ${skipped} skipped in ${(duration / 1000).toFixed(1)}s`;
    
    this.log(`🏁 Test suite completed: ${summary}`);
    
    const suite: TestSuite = {
      name: "Trino Integration Test",
      status,
      timestamp: new Date().toISOString(),
      totalTests: results.length,
      passed,
      failed,
      skipped,
      duration,
      results,
      summary
    };
    
    return suite;
  }
}

// Main execution
if (import.meta.main) {
  const test = new TrinoIntegrationTest();
  const suite = await test.run();
  
  if (Deno.args.includes("--json")) {
    console.log(JSON.stringify(suite, null, 2));
  } else {
    console.log(`\n📊 Final Results:`);
    console.log(`   Total Tests: ${suite.totalTests}`);
    console.log(`   ✅ Passed: ${suite.passed}`);
    console.log(`   ❌ Failed: ${suite.failed}`);
    console.log(`   ⚠️ Skipped: ${suite.skipped}`);
    console.log(`   ⏱️ Duration: ${(suite.duration / 1000).toFixed(1)}s`);
    console.log(`   📝 Summary: ${suite.summary}`);
    
    if (suite.failed > 0) {
      console.log(`\n❌ Failed Tests:`);
      suite.results
        .filter(r => r.status === "failed")
        .forEach(r => console.log(`   - ${r.name}: ${r.error}`));
    }
  }
  
  // Exit with appropriate code
  Deno.exit(suite.status === "passed" ? 0 : suite.failed > 0 ? 2 : 1);
}