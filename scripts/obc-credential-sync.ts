#!/usr/bin/env -S deno run --allow-all

/**
 * Automated ObjectBucketClaim credential synchronization to 1Password
 * 
 * This script watches for ObjectBucketClaim resources and automatically:
 * 1. Extracts generated credentials from OBC secrets/configmaps
 * 2. Stores them in 1Password
 * 3. Creates ExternalSecret resources for Kubernetes consumption
 */

import { $, CommandBuilder } from "jsr:@david/dax@0.42.0";
import { parse as parseYaml } from "jsr:@std/yaml@1.0.5";
import { stringify as stringifyYaml } from "jsr:@std/yaml@1.0.5";

interface ObjectBucketClaim {
  metadata: {
    name: string;
    namespace: string;
    uid: string;
  };
  status?: {
    phase?: string;
  };
}

interface BucketCredentials {
  accessKeyId: string;
  secretAccessKey: string;
  bucketName: string;
  bucketHost: string;
  bucketPort: string;
  bucketRegion?: string;
}

async function getObjectBucketClaims(): Promise<ObjectBucketClaim[]> {
  const result = await $`kubectl get objectbucketclaims -A -o json`.json();
  return result.items || [];
}

async function getSecretData(name: string, namespace: string): Promise<Record<string, string>> {
  try {
    const secret = await $`kubectl get secret ${name} -n ${namespace} -o json`.json();
    const data: Record<string, string> = {};
    
    for (const [key, value] of Object.entries(secret.data || {})) {
      data[key] = atob(value as string);
    }
    
    return data;
  } catch {
    return {};
  }
}

async function getConfigMapData(name: string, namespace: string): Promise<Record<string, string>> {
  try {
    const configMap = await $`kubectl get configmap ${name} -n ${namespace} -o json`.json();
    return configMap.data || {};
  } catch {
    return {};
  }
}

async function extractBucketCredentials(obc: ObjectBucketClaim): Promise<BucketCredentials | null> {
  const { name, namespace } = obc.metadata;
  
  // Get secret and configmap created by OBC
  const secretData = await getSecretData(name, namespace);
  const configMapData = await getConfigMapData(name, namespace);
  
  if (!secretData.AWS_ACCESS_KEY_ID || !secretData.AWS_SECRET_ACCESS_KEY) {
    return null;
  }
  
  return {
    accessKeyId: secretData.AWS_ACCESS_KEY_ID,
    secretAccessKey: secretData.AWS_SECRET_ACCESS_KEY,
    bucketName: configMapData.BUCKET_NAME || "",
    bucketHost: configMapData.BUCKET_HOST || "",
    bucketPort: configMapData.BUCKET_PORT || "80",
    bucketRegion: configMapData.BUCKET_REGION,
  };
}

async function syncTo1Password(obc: ObjectBucketClaim, credentials: BucketCredentials): Promise<void> {
  const { name, namespace } = obc.metadata;
  const itemName = `obc-${namespace}-${name}`;
  
  console.log(`Syncing credentials for ${namespace}/${name} to 1Password...`);
  
  // Create JSON payload for 1Password
  const fields = [
    { type: "STRING", label: "Access Key ID", value: credentials.accessKeyId },
    { type: "CONCEALED", label: "Secret Access Key", value: credentials.secretAccessKey },
    { type: "STRING", label: "Bucket Name", value: credentials.bucketName },
    { type: "STRING", label: "Bucket Host", value: credentials.bucketHost },
    { type: "STRING", label: "Bucket Port", value: credentials.bucketPort },
    { type: "STRING", label: "Endpoint", value: `http://${credentials.bucketHost}:${credentials.bucketPort}` },
  ];
  
  if (credentials.bucketRegion) {
    fields.push({ type: "STRING", label: "Region", value: credentials.bucketRegion });
  }
  
  // TODO: Implement actual 1Password CLI integration
  // For now, we'll create the ExternalSecret manifest
  console.log(`Would sync to 1Password item: ${itemName}`);
}

async function createExternalSecret(obc: ObjectBucketClaim): Promise<void> {
  const { name, namespace } = obc.metadata;
  
  const externalSecret = {
    apiVersion: "external-secrets.io/v1",
    kind: "ExternalSecret",
    metadata: {
      name: `${name}-sync`,
      namespace: namespace,
      labels: {
        "app.kubernetes.io/managed-by": "obc-credential-sync",
        "objectbucket.io/claim-name": name,
      },
    },
    spec: {
      refreshInterval: "1h",
      secretStoreRef: {
        name: "onepassword-connect",
        kind: "ClusterSecretStore",
      },
      target: {
        name: `${name}-1password`,
        creationPolicy: "Owner",
      },
      data: [
        {
          secretKey: "AWS_ACCESS_KEY_ID",
          remoteRef: {
            key: `obc-${namespace}-${name}`,
            property: "Access Key ID",
          },
        },
        {
          secretKey: "AWS_SECRET_ACCESS_KEY",
          remoteRef: {
            key: `obc-${namespace}-${name}`,
            property: "Secret Access Key",
          },
        },
        {
          secretKey: "BUCKET_NAME",
          remoteRef: {
            key: `obc-${namespace}-${name}`,
            property: "Bucket Name",
          },
        },
        {
          secretKey: "BUCKET_HOST",
          remoteRef: {
            key: `obc-${namespace}-${name}`,
            property: "Bucket Host",
          },
        },
        {
          secretKey: "BUCKET_PORT",
          remoteRef: {
            key: `obc-${namespace}-${name}`,
            property: "Bucket Port",
          },
        },
        {
          secretKey: "BUCKET_ENDPOINT",
          remoteRef: {
            key: `obc-${namespace}-${name}`,
            property: "Endpoint",
          },
        },
      ],
    },
  };
  
  const yaml = stringifyYaml(externalSecret);
  await Deno.writeTextFile(`/tmp/obc-${namespace}-${name}-externalsecret.yaml`, yaml);
  
  console.log(`Created ExternalSecret manifest: /tmp/obc-${namespace}-${name}-externalsecret.yaml`);
  console.log("Apply with: kubectl apply -f /tmp/obc-${namespace}-${name}-externalsecret.yaml");
}

async function processObjectBucketClaim(obc: ObjectBucketClaim): Promise<void> {
  if (obc.status?.phase !== "Bound") {
    console.log(`Skipping ${obc.metadata.namespace}/${obc.metadata.name} - not bound yet`);
    return;
  }
  
  const credentials = await extractBucketCredentials(obc);
  if (!credentials) {
    console.log(`No credentials found for ${obc.metadata.namespace}/${obc.metadata.name}`);
    return;
  }
  
  await syncTo1Password(obc, credentials);
  await createExternalSecret(obc);
}

async function watchMode(): Promise<void> {
  console.log("Starting OBC credential sync in watch mode...");
  
  const processedOBCs = new Set<string>();
  
  while (true) {
    const obcs = await getObjectBucketClaims();
    
    for (const obc of obcs) {
      const key = `${obc.metadata.namespace}/${obc.metadata.name}`;
      if (!processedOBCs.has(key)) {
        await processObjectBucketClaim(obc);
        processedOBCs.add(key);
      }
    }
    
    await new Promise(resolve => setTimeout(resolve, 10000)); // Check every 10 seconds
  }
}

async function syncAll(): Promise<void> {
  console.log("Syncing all ObjectBucketClaim credentials...");
  
  const obcs = await getObjectBucketClaims();
  console.log(`Found ${obcs.length} ObjectBucketClaims`);
  
  for (const obc of obcs) {
    await processObjectBucketClaim(obc);
  }
}

// Main execution
if (import.meta.main) {
  const args = Deno.args;
  
  if (args.includes("--watch")) {
    await watchMode();
  } else {
    await syncAll();
  }
}