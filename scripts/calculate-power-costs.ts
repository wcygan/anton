#!/usr/bin/env -S deno run --allow-all

interface PowerMetrics {
  idleWatts: number;
  averageWatts: number;
  peakWatts: number;
  electricityRate: number; // $/kWh
  nodes: number;
}

interface CostBreakdown {
  daily: string;
  monthly: string;
  annual: string;
  scenarios: {
    idle: string;
    average: string;
    peak: string;
  };
  perNode: {
    daily: string;
    monthly: string;
  };
}

function calculatePowerCosts(metrics: PowerMetrics): CostBreakdown {
  const hoursPerDay = 24;
  const daysPerMonth = 30;
  const daysPerYear = 365;
  
  // Convert watts to kilowatts
  const idleKw = metrics.idleWatts / 1000;
  const avgKw = metrics.averageWatts / 1000;
  const peakKw = metrics.peakWatts / 1000;
  
  // Calculate costs
  const dailyCost = avgKw * hoursPerDay * metrics.electricityRate;
  const monthlyCost = dailyCost * daysPerMonth;
  const annualCost = dailyCost * daysPerYear;
  
  // Calculate for different scenarios
  const idleCostMonthly = idleKw * hoursPerDay * daysPerMonth * metrics.electricityRate;
  const peakCostMonthly = peakKw * hoursPerDay * daysPerMonth * metrics.electricityRate;
  
  // Per-node costs
  const perNodeDaily = dailyCost / metrics.nodes;
  const perNodeMonthly = monthlyCost / metrics.nodes;
  
  return {
    daily: dailyCost.toFixed(2),
    monthly: monthlyCost.toFixed(2),
    annual: annualCost.toFixed(2),
    scenarios: {
      idle: idleCostMonthly.toFixed(2),
      average: monthlyCost.toFixed(2),
      peak: peakCostMonthly.toFixed(2)
    },
    perNode: {
      daily: perNodeDaily.toFixed(2),
      monthly: perNodeMonthly.toFixed(2)
    }
  };
}

function estimatePowerFromUtilization(cpuPercent: number, nodes: number = 3): number {
  // MS-01 power curve estimation
  const idlePowerPerNode = 30;  // Watts at idle
  const maxPowerPerNode = 100;  // Watts at 100% CPU
  
  // Linear approximation (real curve is non-linear)
  const powerPerNode = idlePowerPerNode + (maxPowerPerNode - idlePowerPerNode) * (cpuPercent / 100);
  return powerPerNode * nodes;
}

// Get current cluster utilization from kubectl
async function getCurrentUtilization() {
  try {
    const { $ } = await import("https://deno.land/x/dax@0.35.0/mod.ts");
    const result = await $`kubectl top nodes --no-headers`.text();
    
    const lines = result.trim().split('\n');
    let totalCpu = 0;
    const nodeCount = lines.length;
    
    for (const line of lines) {
      const parts = line.split(/\s+/);
      const cpuPercent = parseInt(parts[2].replace('%', ''));
      totalCpu += cpuPercent;
    }
    
    return {
      avgCpuPercent: totalCpu / nodeCount,
      nodeCount: nodeCount
    };
  } catch (error) {
    console.log("Unable to get current utilization, using estimates");
    return null;
  }
}

// Main execution
if (import.meta.main) {
  const electricityRate = parseFloat(Deno.args[0] || "0.12"); // Default US average
  
  console.log("=== Anton Homelab Power Cost Calculator ===");
  console.log(`Electricity Rate: $${electricityRate}/kWh`);
  console.log("");
  
  // Try to get current utilization
  const currentUtil = await getCurrentUtilization();
  
  if (currentUtil) {
    const currentPower = estimatePowerFromUtilization(currentUtil.avgCpuPercent, currentUtil.nodeCount);
    console.log(`Current Cluster Status:`);
    console.log(`  Nodes: ${currentUtil.nodeCount}`);
    console.log(`  Average CPU: ${currentUtil.avgCpuPercent.toFixed(1)}%`);
    console.log(`  Estimated Power: ${currentPower.toFixed(0)}W`);
    
    const currentMetrics: PowerMetrics = {
      idleWatts: 30 * currentUtil.nodeCount,
      averageWatts: currentPower,
      peakWatts: 100 * currentUtil.nodeCount,
      electricityRate: electricityRate,
      nodes: currentUtil.nodeCount
    };
    
    const currentCosts = calculatePowerCosts(currentMetrics);
    console.log("");
    console.log("Current Operating Costs:");
    console.log(`  Daily: $${currentCosts.daily}`);
    console.log(`  Monthly: $${currentCosts.monthly}`);
    console.log(`  Annual: $${currentCosts.annual}`);
    console.log(`  Per Node Monthly: $${currentCosts.perNode.monthly}`);
  }
  
  // Standard 3-node cluster estimates
  const clusterMetrics: PowerMetrics = {
    idleWatts: 90,      // 30W × 3 nodes
    averageWatts: 150,  // 50W × 3 nodes (typical ~30% utilization)
    peakWatts: 300,     // 100W × 3 nodes
    electricityRate: electricityRate,
    nodes: 3
  };
  
  const costs = calculatePowerCosts(clusterMetrics);
  
  console.log("");
  console.log("=== 3-Node Cluster Cost Scenarios ===");
  console.log("Scenario Analysis (Monthly):");
  console.log(`  Idle (${clusterMetrics.idleWatts}W): $${costs.scenarios.idle}`);
  console.log(`  Average (${clusterMetrics.averageWatts}W): $${costs.scenarios.average}`);
  console.log(`  Peak (${clusterMetrics.peakWatts}W): $${costs.scenarios.peak}`);
  
  // Expansion scenarios
  console.log("");
  console.log("=== Expansion Cost Impact ===");
  
  const fourNodeMetrics: PowerMetrics = {
    idleWatts: 120,
    averageWatts: 200,
    peakWatts: 400,
    electricityRate: electricityRate,
    nodes: 4
  };
  
  const fourNodeCosts = calculatePowerCosts(fourNodeMetrics);
  const additionalMonthlyCost = (parseFloat(fourNodeCosts.monthly) - parseFloat(costs.monthly)).toFixed(2);
  
  console.log("Adding 4th Node:");
  console.log(`  Additional Monthly Cost: $${additionalMonthlyCost}`);
  console.log(`  New Total Monthly: $${fourNodeCosts.monthly}`);
  
  // Efficiency comparison
  console.log("");
  console.log("=== Cost Efficiency Comparison ===");
  console.log("Homelab vs Cloud (equivalent compute):");
  console.log(`  Homelab: $${costs.monthly}/month (power only)`);
  console.log(`  AWS (3x m5.xlarge): ~$450/month`);
  console.log(`  Savings: ~$${(450 - parseFloat(costs.monthly)).toFixed(2)}/month`);
  console.log(`  Annual Savings: ~$${((450 - parseFloat(costs.monthly)) * 12).toFixed(0)}`);
  
  // Tips
  console.log("");
  console.log("=== Power Saving Tips ===");
  console.log("1. Enable CPU frequency scaling in Talos");
  console.log("2. Use node affinity to consolidate light workloads");
  console.log("3. Consider workload scheduling during off-peak hours");
  console.log("4. Monitor actual consumption with smart plugs for accuracy");
}