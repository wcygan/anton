---
sidebar_position: 4
sidebar_label: RedPanda (Streaming)
---

# RedPanda

[RedPanda](https://redpanda.com/) is a Kafka-compatible streaming data platform optimized for low-latency, high-throughput event pipelines.

## Kubernetes Deployment

I use [RedPanda Operator](https://github.com/redpanda-data/redpanda-operator) on Kubernetes:

> The Redpanda Operator is designed for production-grade Redpanda deployments, offering enhanced lifecycle management, automation, and GitOps compatibility.
> 
> The Redpanda Operator directly reconciles Redpanda resources, performing tasks such as installations, updates, and cleanup.

Docs: https://docs.redpanda.com/current/deploy/redpanda/kubernetes/k-deployment-overview/#helm-and-redpanda-operator