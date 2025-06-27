#!/usr/bin/env -S deno run --allow-all

/**
 * Test script for ObjectBucketClaim automated provisioning
 * 
 * This script:
 * 1. Creates a test OBC
 * 2. Waits for provisioning
 * 3. Verifies credentials and bucket access
 * 4. Cleans up test resources
 */

import { $ } from "jsr:@david/dax@0.42.0";
import { parse as parseYaml } from "jsr:@std/yaml@1.0.5";

const TEST_NAMESPACE = "default";
const TEST_OBC_NAME = "test-obc-provisioning";

// Test OBC manifest
const testOBC = {
  apiVersion: "objectbucket.io/v1alpha1",
  kind: "ObjectBucketClaim",
  metadata: {
    name: TEST_OBC_NAME,
    namespace: TEST_NAMESPACE,
    labels: {
      "app.kubernetes.io/name": "test-obc",
      "test": "automated-provisioning",
    },
  },
  spec: {
    storageClassName: "ceph-bucket",
    additionalConfig: {
      lifecycleConfiguration: {
        rules: [{
          id: "delete-test-data",
          status: "Enabled",
          prefix: "test/",
          expiration: { days: 1 },
        }],
      },
    },
  },
};

async function createOBC(): Promise<void> {
  console.log("📦 Creating test ObjectBucketClaim...");
  const manifest = JSON.stringify(testOBC);
  
  await $`kubectl apply -f -`.stdin(manifest);
  console.log("✅ OBC created");
}

async function waitForProvisioning(timeout = 60): Promise<boolean> {
  console.log("⏳ Waiting for OBC provisioning...");
  const startTime = Date.now();
  
  while ((Date.now() - startTime) / 1000 < timeout) {
    try {
      const obc = await $`kubectl get obc ${TEST_OBC_NAME} -n ${TEST_NAMESPACE} -o json`.json();
      
      if (obc.status?.phase === "Bound") {
        console.log("✅ OBC is bound!");
        return true;
      }
      
      console.log(`⏳ Current phase: ${obc.status?.phase || "Unknown"}`);
    } catch (error) {
      console.log("⏳ OBC not found yet...");
    }
    
    await new Promise(resolve => setTimeout(resolve, 5000));
  }
  
  console.error("❌ Timeout waiting for OBC provisioning");
  return false;
}

async function verifyResources(): Promise<boolean> {
  console.log("\n🔍 Verifying created resources...");
  
  try {
    // Check Secret
    const secret = await $`kubectl get secret ${TEST_OBC_NAME} -n ${TEST_NAMESPACE} -o json`.json();
    console.log("✅ Secret created");
    
    // Check ConfigMap
    const configMap = await $`kubectl get configmap ${TEST_OBC_NAME} -n ${TEST_NAMESPACE} -o json`.json();
    console.log("✅ ConfigMap created");
    
    // Extract credentials
    const accessKeyId = atob(secret.data.AWS_ACCESS_KEY_ID);
    const secretAccessKey = atob(secret.data.AWS_SECRET_ACCESS_KEY);
    const bucketName = configMap.data.BUCKET_NAME;
    const bucketHost = configMap.data.BUCKET_HOST;
    const bucketPort = configMap.data.BUCKET_PORT || "80";
    
    console.log("\n📋 Bucket Details:");
    console.log(`  Name: ${bucketName}`);
    console.log(`  Endpoint: http://${bucketHost}:${bucketPort}`);
    console.log(`  Access Key: ${accessKeyId.substring(0, 10)}...`);
    
    return true;
  } catch (error) {
    console.error("❌ Failed to verify resources:", error.message);
    return false;
  }
}

async function testBucketAccess(): Promise<boolean> {
  console.log("\n🧪 Testing bucket access...");
  
  try {
    // Get credentials
    const secret = await $`kubectl get secret ${TEST_OBC_NAME} -n ${TEST_NAMESPACE} -o json`.json();
    const configMap = await $`kubectl get configmap ${TEST_OBC_NAME} -n ${TEST_NAMESPACE} -o json`.json();
    
    const accessKeyId = atob(secret.data.AWS_ACCESS_KEY_ID);
    const secretAccessKey = atob(secret.data.AWS_SECRET_ACCESS_KEY);
    const bucketName = configMap.data.BUCKET_NAME;
    const endpoint = `http://${configMap.data.BUCKET_HOST}:${configMap.data.BUCKET_PORT || "80"}`;
    
    // Create test pod with s3cmd
    const testPodManifest = {
      apiVersion: "v1",
      kind: "Pod",
      metadata: {
        name: "s3-test-pod",
        namespace: TEST_NAMESPACE,
      },
      spec: {
        restartPolicy: "Never",
        containers: [{
          name: "s3cmd",
          image: "alpine/s3cmd:latest",
          command: ["sleep", "300"],
          env: [
            { name: "AWS_ACCESS_KEY_ID", value: accessKeyId },
            { name: "AWS_SECRET_ACCESS_KEY", value: secretAccessKey },
          ],
        }],
      },
    };
    
    console.log("🚀 Creating test pod...");
    await $`kubectl apply -f -`.stdin(JSON.stringify(testPodManifest));
    
    // Wait for pod to be ready
    await $`kubectl wait --for=condition=ready pod/s3-test-pod -n ${TEST_NAMESPACE} --timeout=30s`;
    
    // Test bucket operations
    console.log("📝 Writing test file...");
    await $`kubectl exec -n ${TEST_NAMESPACE} s3-test-pod -- sh -c "echo 'Hello OBC!' > /tmp/test.txt"`;
    
    console.log("⬆️  Uploading to bucket...");
    await $`kubectl exec -n ${TEST_NAMESPACE} s3-test-pod -- s3cmd --host=${endpoint} --host-bucket=${endpoint} --no-ssl put /tmp/test.txt s3://${bucketName}/`;
    
    console.log("📋 Listing bucket contents...");
    const listOutput = await $`kubectl exec -n ${TEST_NAMESPACE} s3-test-pod -- s3cmd --host=${endpoint} --host-bucket=${endpoint} --no-ssl ls s3://${bucketName}/`.text();
    console.log(listOutput);
    
    console.log("⬇️  Downloading from bucket...");
    await $`kubectl exec -n ${TEST_NAMESPACE} s3-test-pod -- s3cmd --host=${endpoint} --host-bucket=${endpoint} --no-ssl get s3://${bucketName}/test.txt /tmp/downloaded.txt`;
    
    const content = await $`kubectl exec -n ${TEST_NAMESPACE} s3-test-pod -- cat /tmp/downloaded.txt`.text();
    console.log(`📄 Downloaded content: ${content.trim()}`);
    
    console.log("✅ Bucket access successful!");
    return true;
  } catch (error) {
    console.error("❌ Bucket access test failed:", error.message);
    return false;
  } finally {
    // Cleanup test pod
    try {
      await $`kubectl delete pod s3-test-pod -n ${TEST_NAMESPACE} --ignore-not-found=true`;
    } catch {}
  }
}

async function testCredentialSync(): Promise<void> {
  console.log("\n🔐 Testing credential sync...");
  
  try {
    // Run the sync script
    console.log("Running obc-credential-sync.ts...");
    await $`./scripts/obc-credential-sync.ts`;
    
    // Check if ExternalSecret was created
    const externalSecretPath = `/tmp/obc-${TEST_NAMESPACE}-${TEST_OBC_NAME}-externalsecret.yaml`;
    if (await Deno.stat(externalSecretPath).catch(() => null)) {
      console.log("✅ ExternalSecret manifest created");
      console.log(`📄 Manifest location: ${externalSecretPath}`);
      
      // Show the manifest
      const content = await Deno.readTextFile(externalSecretPath);
      console.log("\n--- ExternalSecret Manifest ---");
      console.log(content.substring(0, 500) + "...");
    } else {
      console.log("⚠️  ExternalSecret manifest not found");
    }
  } catch (error) {
    console.error("❌ Credential sync test failed:", error.message);
  }
}

async function cleanup(): Promise<void> {
  console.log("\n🧹 Cleaning up test resources...");
  
  try {
    await $`kubectl delete obc ${TEST_OBC_NAME} -n ${TEST_NAMESPACE} --ignore-not-found=true`;
    console.log("✅ OBC deleted");
    
    // Wait for cleanup
    await new Promise(resolve => setTimeout(resolve, 5000));
    
    // Verify cleanup
    try {
      await $`kubectl get secret ${TEST_OBC_NAME} -n ${TEST_NAMESPACE}`.quiet();
      console.log("⚠️  Secret still exists");
    } catch {
      console.log("✅ Secret cleaned up");
    }
    
    try {
      await $`kubectl get configmap ${TEST_OBC_NAME} -n ${TEST_NAMESPACE}`.quiet();
      console.log("⚠️  ConfigMap still exists");
    } catch {
      console.log("✅ ConfigMap cleaned up");
    }
  } catch (error) {
    console.error("❌ Cleanup failed:", error.message);
  }
}

async function main(): Promise<void> {
  console.log("🚀 ObjectBucketClaim Automated Provisioning Test\n");
  
  try {
    // Step 1: Create OBC
    await createOBC();
    
    // Step 2: Wait for provisioning
    const provisioned = await waitForProvisioning();
    if (!provisioned) {
      console.error("❌ Provisioning failed");
      await cleanup();
      Deno.exit(1);
    }
    
    // Step 3: Verify resources
    const verified = await verifyResources();
    if (!verified) {
      console.error("❌ Resource verification failed");
      await cleanup();
      Deno.exit(1);
    }
    
    // Step 4: Test bucket access
    const accessible = await testBucketAccess();
    if (!accessible) {
      console.error("❌ Bucket access test failed");
    }
    
    // Step 5: Test credential sync
    await testCredentialSync();
    
    console.log("\n✅ All tests completed!");
    
    // Optional: Keep resources for manual inspection
    if (Deno.args.includes("--keep")) {
      console.log("\n📌 Resources kept for manual inspection");
      console.log(`   kubectl get obc ${TEST_OBC_NAME} -n ${TEST_NAMESPACE}`);
      console.log(`   kubectl get secret ${TEST_OBC_NAME} -n ${TEST_NAMESPACE}`);
      console.log(`   kubectl get configmap ${TEST_OBC_NAME} -n ${TEST_NAMESPACE}`);
    } else {
      await cleanup();
    }
  } catch (error) {
    console.error("❌ Test failed:", error.message);
    await cleanup();
    Deno.exit(1);
  }
}

if (import.meta.main) {
  await main();
}