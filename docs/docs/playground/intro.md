---
sidebar_position: 1
sidebar_label: Data Infrastructure
---

# Data Infrastructure

This folder captures explorations on moving away from the old guard ([Postgres](https://www.postgresql.org/), [MySQL](https://www.mysql.com/), [Redis](https://redis.io/), [Kafka](https://kafka.apache.org/), [Cassandra](https://cassandra.apache.org/_/index.html)) and learning about new technologies such as [TiDB](https://www.pingcap.com/en/products/tidb/),  [Dragonfly](https://www.dragonflydb.io/), [RedPanda](https://redpanda.com/), [ScyllaDB](https://www.scylladb.com/), [ClickHouse](https://clickhouse.com/), etc.

```bash
kubectl get pods -A | rg '...'
databases                   dragonfly-operator-aaaaaaa-bbbbb                        2/2
databases                   redpanda-operator-ccccccc-ddddd                         1/1
databases                   redpanda-playground-instance-a                          2/2
databases                   redpanda-playground-console-eeeeeee-fffff               1/1
databases                   tidb-controller-manager-gggggggg-zzzzz                  1/1
playground                  dragonfly-playground-instance-a                         1/1
playground                  scylla-playground-datacenter1-rack1-instance-a          4/4
playground                  tidb-playground-discovery-hhhhhhhh-iiiii                1/1
playground                  tidb-playground-pd-instance-a                           1/1
playground                  tidb-playground-tidb-instance-a                         2/2
playground                  tidb-playground-tikv-instance-a                         1/1
scylla-manager              scylla-manager-jjjjjjjjj-kkkkk                          1/1
scylla-manager              scylla-manager-scylla-manager-dc1-rack1-instance-a      4/4
scylla-operator             scylla-operator-lllllll-mmmmm                           1/1
scylla-operator             scylla-operator-nnnnnnn-ooooo                           1/1
scylla-operator             webhook-server-pppppppp-qqqqq                           1/1
scylla-operator             webhook-server-rrrrrrrr-sssss                           1/1
```
