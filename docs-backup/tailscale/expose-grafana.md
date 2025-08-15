# Expose Grafana

We can use Tailscale to expose Grafana to the Tailnet.

Reference: https://tailscale.com/kb/1439/kubernetes-operator-cluster-ingress

## Cluster Details

```bash
k get svc -n monitoring

NAME                                             TYPE        CLUSTER-IP      EXTERNAL-IP   PORT(S)                      AGE
kube-prometheus-stack-grafana                    ClusterIP   10.43.170.101   <none>        80/TCP                       23h
```

Username: `admin` Password: `prom-operator`

## Access URL

Once configured, Grafana is accessible at: `https://grafana.walleye-monster.ts.net`

## Troubleshooting

If you cannot access Grafana or other Tailscale-exposed services, see the [Tailscale Troubleshooting Guide](./troubleshooting.md) for common issues and solutions.
