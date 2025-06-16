#!/usr/bin/env -S deno run --allow-all

/**
 * Quick Integration Test for Spark History Server
 * 
 * This test:
 * 1. Submits a Spark Pi job
 * 2. Waits for completion
 * 3. Verifies the job appears in History Server
 * 4. Cleans up resources
 */

import { $ } from "https://deno.land/x/dax@0.35.0/mod.ts";

const NAMESPACE = "data-platform";
const SPARK_APP_PATH = "kubernetes/apps/data-platform/spark-applications/app/test-spark-pi/spark-pi.yaml";
const HISTORY_SERVER_URL = "http://localhost:18080";

async function portForwardHistoryServer() {
  console.log("🔌 Setting up port-forward to History Server...");
  
  // Start port-forward in background
  const portForward = $`kubectl port-forward -n ${NAMESPACE} svc/spark-history-server 18080:18080`.spawn();
  
  // Wait a moment for port-forward to establish
  await new Promise(resolve => setTimeout(resolve, 3000));
  
  return portForward;
}

async function checkHistoryServerAPI(maxAttempts = 5) {
  console.log("🔍 Checking History Server API for completed job...");
  
  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    try {
      const response = await fetch(`${HISTORY_SERVER_URL}/api/v1/applications`);
      
      if (!response.ok) {
        console.log(`  Attempt ${attempt}/${maxAttempts}: API returned ${response.status}`);
      } else {
        const apps = await response.json();
        console.log(`  Found ${apps.length} application(s) in History Server`);
        
        // Look for our Spark Pi job
        const sparkPiJob = apps.find((app: any) => 
          app.name === "SparkPi" || app.name.includes("spark-pi")
        );
        
        if (sparkPiJob) {
          console.log("✅ Spark Pi job found in History Server!");
          console.log(`   Application ID: ${sparkPiJob.id}`);
          console.log(`   Status: ${sparkPiJob.attempts[0]?.completed ? 'Completed' : 'Running'}`);
          console.log(`   Start Time: ${new Date(sparkPiJob.attempts[0]?.startTime).toLocaleString()}`);
          console.log(`   Duration: ${sparkPiJob.attempts[0]?.duration ? sparkPiJob.attempts[0].duration + 'ms' : 'N/A'}`);
          return true;
        }
      }
    } catch (error) {
      console.log(`  Attempt ${attempt}/${maxAttempts}: ${error.message}`);
    }
    
    if (attempt < maxAttempts) {
      console.log(`  Waiting 10 seconds before retry...`);
      await new Promise(resolve => setTimeout(resolve, 10000));
    }
  }
  
  return false;
}

async function main() {
  console.log("🚀 Spark History Server Quick Integration Test");
  console.log("===========================================\n");
  
  let portForwardProcess = null;
  
  try {
    // Step 1: Clean up any existing spark-pi job
    console.log("🧹 Cleaning up any existing spark-pi job...");
    try {
      await $`kubectl delete sparkapplication spark-pi -n ${NAMESPACE}`.quiet();
    } catch {
      // Ignore if doesn't exist
    }
    
    // Step 2: Apply the spark-pi job
    console.log("\n📦 Submitting Spark Pi job...");
    await $`kubectl apply -f ${SPARK_APP_PATH}`;
    console.log("✅ Job submitted");
    
    // Step 3: Wait for job to start
    console.log("\n⏳ Waiting for job to start...");
    await $`kubectl wait --for=condition=Running sparkapplication/spark-pi -n ${NAMESPACE} --timeout=60s`;
    console.log("✅ Job is running");
    
    // Step 4: Wait for job completion
    console.log("\n⏳ Waiting for job to complete (this may take 1-2 minutes)...");
    try {
      await $`kubectl wait --for=condition=Completed sparkapplication/spark-pi -n ${NAMESPACE} --timeout=180s`;
      console.log("✅ Job completed successfully");
    } catch (error) {
      console.log("⚠️  Job may still be running or failed. Checking status...");
      const status = await $`kubectl get sparkapplication spark-pi -n ${NAMESPACE} -o jsonpath='{.status.applicationState.state}'`.text();
      console.log(`   Current status: ${status}`);
    }
    
    // Step 5: Set up port-forward and check History Server
    console.log("\n");
    portForwardProcess = await portForwardHistoryServer();
    
    // Step 6: Check History Server API
    console.log("\n");
    const found = await checkHistoryServerAPI();
    
    if (found) {
      console.log("\n🎉 Integration test PASSED!");
      console.log("   ✓ Spark Operator is working");
      console.log("   ✓ S3 event logging is configured correctly");
      console.log("   ✓ History Server can read event logs");
      console.log("   ✓ History Server API is accessible");
      
      console.log("\n📊 You can view the Spark UI at: http://localhost:18080");
      console.log("   (Keep this script running to maintain port-forward)");
      console.log("   Press Ctrl+C to exit and cleanup");
      
      // Keep running to maintain port-forward
      await new Promise(() => {});
    } else {
      console.log("\n❌ Integration test FAILED!");
      console.log("   Job completed but was not found in History Server");
      console.log("   Check S3 bucket and History Server logs for issues");
      Deno.exit(1);
    }
    
  } catch (error) {
    console.error("\n❌ Test failed with error:", error.message);
    Deno.exit(1);
  } finally {
    // Cleanup on exit
    Deno.addSignalListener("SIGINT", async () => {
      console.log("\n\n🧹 Cleaning up...");
      
      if (portForwardProcess) {
        portForwardProcess.kill();
      }
      
      try {
        await $`kubectl delete sparkapplication spark-pi -n ${NAMESPACE}`.quiet();
        console.log("✅ Cleaned up spark-pi job");
      } catch {
        // Ignore cleanup errors
      }
      
      Deno.exit(0);
    });
  }
}

if (import.meta.main) {
  main();
}