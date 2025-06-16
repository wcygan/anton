#!/usr/bin/env -S deno run --allow-all

/**
 * Simple test to verify Spark can write event logs to S3
 * This bypasses the Spark Operator and runs Spark directly
 */

import { $ } from "https://deno.land/x/dax@0.35.0/mod.ts";

const NAMESPACE = "data-platform";

async function main() {
  console.log("🚀 Simple Spark S3 Event Log Test");
  console.log("==================================\n");
  
  try {
    // Step 1: Run a simple Spark job in a pod
    console.log("📦 Creating a simple Spark job pod...");
    
    const podYaml = `
apiVersion: v1
kind: Pod
metadata:
  name: spark-test-s3
  namespace: ${NAMESPACE}
spec:
  serviceAccountName: spark-application-sa
  containers:
  - name: spark
    image: apache/spark:3.5.3
    command:
    - /bin/bash
    - -c
    - |
      # Download S3 libraries
      cd /opt/spark/jars
      wget -q https://repo1.maven.org/maven2/org/apache/hadoop/hadoop-aws/3.3.4/hadoop-aws-3.3.4.jar
      wget -q https://repo1.maven.org/maven2/com/amazonaws/aws-java-sdk-bundle/1.12.367/aws-java-sdk-bundle-1.12.367.jar
      
      # Run Spark Pi with event logging
      /opt/spark/bin/spark-submit \
        --class org.apache.spark.examples.SparkPi \
        --master local[2] \
        --conf spark.eventLog.enabled=true \
        --conf spark.eventLog.dir=s3a://iceberg-test/spark-events \
        --conf spark.hadoop.fs.s3a.endpoint=http://rook-ceph-rgw-storage.storage.svc:80 \
        --conf spark.hadoop.fs.s3a.path.style.access=true \
        --conf spark.hadoop.fs.s3a.connection.ssl.enabled=false \
        --conf spark.hadoop.fs.s3a.access.key=\${AccessKey} \
        --conf spark.hadoop.fs.s3a.secret.key=\${SecretKey} \
        /opt/spark/examples/jars/spark-examples_2.12-3.5.3.jar 100
        
      echo "Job completed!"
    envFrom:
    - secretRef:
        name: rook-ceph-object-user-storage-iceberg
  restartPolicy: Never
`;

    // Clean up any existing pod
    try {
      await $`kubectl delete pod spark-test-s3 -n ${NAMESPACE}`.quiet();
    } catch {
      // Ignore if doesn't exist
    }
    
    // Create the pod
    await $`echo ${podYaml} | kubectl apply -f -`;
    console.log("✅ Pod created");
    
    // Wait for pod to complete
    console.log("\n⏳ Waiting for job to complete...");
    await $`kubectl wait --for=condition=Ready pod/spark-test-s3 -n ${NAMESPACE} --timeout=60s || true`;
    
    // Check logs
    console.log("\n📝 Pod logs:");
    const logs = await $`kubectl logs spark-test-s3 -n ${NAMESPACE} --tail=50`.text();
    console.log(logs);
    
    // Check if event log was written to S3
    console.log("\n🔍 Checking S3 for event logs...");
    const s3CheckPod = `
apiVersion: v1
kind: Pod
metadata:
  name: s3-check
  namespace: ${NAMESPACE}
spec:
  containers:
  - name: aws-cli
    image: amazon/aws-cli:2.17.0
    command:
    - /bin/bash
    - -c
    - |
      export AWS_ACCESS_KEY_ID="\${AccessKey}"
      export AWS_SECRET_ACCESS_KEY="\${SecretKey}"
      aws s3 ls s3://iceberg-test/spark-events/ --endpoint-url http://rook-ceph-rgw-storage.storage.svc:80 --recursive | tail -10
    envFrom:
    - secretRef:
        name: rook-ceph-object-user-storage-iceberg
  restartPolicy: Never
`;

    // Clean up and create check pod
    try {
      await $`kubectl delete pod s3-check -n ${NAMESPACE}`.quiet();
    } catch {
      // Ignore
    }
    
    await $`echo ${s3CheckPod} | kubectl apply -f -`;
    await $`kubectl wait --for=condition=Ready pod/s3-check -n ${NAMESPACE} --timeout=30s || true`;
    
    const s3Logs = await $`kubectl logs s3-check -n ${NAMESPACE}`.text();
    console.log("S3 event logs:");
    console.log(s3Logs);
    
    if (s3Logs.includes("spark-events")) {
      console.log("\n✅ SUCCESS! Event logs are being written to S3");
      console.log("   The Spark History Server should be able to read these logs");
    } else {
      console.log("\n❌ No event logs found in S3");
    }
    
    // Cleanup
    console.log("\n🧹 Cleaning up test pods...");
    await $`kubectl delete pod spark-test-s3 s3-check -n ${NAMESPACE}`.quiet();
    
  } catch (error) {
    console.error("❌ Test failed:", error.message);
    Deno.exit(1);
  }
}

if (import.meta.main) {
  main();
}