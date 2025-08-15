#!/usr/bin/env deno run --allow-all
/**
 * Comprehensive Hook Testing Script
 * Tests all Phase 1 hooks to ensure proper integration
 */

import { runCommand } from "./hook-utils.ts";

interface TestCase {
  name: string;
  hook: string;
  args: string[];
  expectedExitCode: number;
  description: string;
}

const testCases: TestCase[] = [
  // Namespace Protector Tests
  {
    name: "namespace-protector-safe",
    hook: "./scripts/hooks/namespace-protector.ts",
    args: ["kubernetes/apps/test/app.yaml"],
    expectedExitCode: 0,
    description: "Safe path should be allowed",
  },
  {
    name: "namespace-protector-protected",
    hook: "./scripts/hooks/namespace-protector.ts", 
    args: ["kubernetes/apps/flux-system/test.yaml"],
    expectedExitCode: 2,
    description: "Protected path should be blocked",
  },
  
  // Secret Scanner Tests
  {
    name: "secret-scanner-safe",
    hook: "./scripts/hooks/secret-scanner.ts",
    args: ["/tmp/test-safe.yaml"],
    expectedExitCode: 0,
    description: "File with no secrets should pass",
  },
  
  // Manifest Validator Tests
  {
    name: "manifest-validator-non-k8s",
    hook: "./scripts/hooks/manifest-validator.ts",
    args: ["/tmp/test-readme.md"],
    expectedExitCode: 0,
    description: "Non-Kubernetes file should be skipped",
  },
];

async function createTestFiles(): Promise<void> {
  // Create safe YAML file
  await Deno.writeTextFile("/tmp/test-safe.yaml", `
apiVersion: apps/v1
kind: Deployment
metadata:
  name: test-app
spec:
  replicas: 1
  template:
    spec:
      containers:
      - name: app
        image: nginx:latest
        env:
        - name: DATABASE_URL
          value: \${DATABASE_URL}
`);

  // Create non-k8s file
  await Deno.writeTextFile("/tmp/test-readme.md", `
# Test README
This is just documentation.
`);
}

async function cleanupTestFiles(): Promise<void> {
  try {
    await Deno.remove("/tmp/test-safe.yaml");
    await Deno.remove("/tmp/test-readme.md");
  } catch {
    // Ignore cleanup errors
  }
}

async function runTest(testCase: TestCase): Promise<{ success: boolean; message: string }> {
  console.log(`\n🧪 Running test: ${testCase.name}`);
  console.log(`   Description: ${testCase.description}`);
  console.log(`   Command: ${testCase.hook} ${testCase.args.join(' ')}`);

  const result = await runCommand([testCase.hook, ...testCase.args]);
  
  const success = result.success ? 
    (testCase.expectedExitCode === 0) : 
    (testCase.expectedExitCode !== 0);

  const message = success 
    ? `✅ PASS - Exit code ${result.success ? 0 : 'non-zero'} as expected`
    : `❌ FAIL - Expected exit code ${testCase.expectedExitCode}, got ${result.success ? 0 : 'non-zero'}`;

  console.log(`   Result: ${message}`);
  if (result.output) console.log(`   Output: ${result.output.substring(0, 200)}...`);
  if (result.error) console.log(`   Error: ${result.error.substring(0, 200)}...`);

  return { success, message };
}

async function main(): Promise<void> {
  console.log("🚀 Starting comprehensive hook testing...\n");
  
  try {
    await createTestFiles();
    
    let totalTests = 0;
    let passedTests = 0;
    
    for (const testCase of testCases) {
      totalTests++;
      const result = await runTest(testCase);
      if (result.success) passedTests++;
    }
    
    console.log(`\n📊 Test Results:`);
    console.log(`   Total tests: ${totalTests}`);
    console.log(`   Passed: ${passedTests}`);
    console.log(`   Failed: ${totalTests - passedTests}`);
    
    if (passedTests === totalTests) {
      console.log(`\n🎉 All tests passed! Phase 1 hooks are working correctly.`);
    } else {
      console.log(`\n⚠️  Some tests failed. Please check the output above.`);
    }
    
    // Test override mechanisms
    console.log(`\n🔓 Testing override mechanisms...`);
    
    const overrideTests = [
      {
        env: "FORCE_NAMESPACE_EDIT=true",
        hook: "./scripts/hooks/namespace-protector.ts",
        args: ["kubernetes/apps/flux-system/test.yaml"],
        description: "Namespace protection override",
      },
      {
        env: "FORCE_SECRET_SCAN=true", 
        hook: "./scripts/hooks/secret-scanner.ts",
        args: ["/tmp/test-safe.yaml"],
        description: "Secret scanning override",
      },
      {
        env: "FORCE_MANIFEST_VALIDATION=true",
        hook: "./scripts/hooks/manifest-validator.ts", 
        args: ["/tmp/test-safe.yaml"],
        description: "Manifest validation override",
      },
    ];
    
    for (const test of overrideTests) {
      console.log(`\n🔓 Testing ${test.description}...`);
      const cmd = new Deno.Command("sh", {
        args: ["-c", `cd $PWD && ${test.env} ${test.hook} ${test.args.join(' ')}`],
        stdout: "piped",
        stderr: "piped",
      });
      
      const result = await cmd.output();
      const success = result.code === 0;
      console.log(`   ${success ? '✅' : '❌'} Override ${success ? 'worked' : 'failed'}`);
    }
    
  } finally {
    await cleanupTestFiles();
  }
  
  console.log(`\n🏁 Hook testing completed!`);
}

if (import.meta.main) {
  main().catch(console.error);
}