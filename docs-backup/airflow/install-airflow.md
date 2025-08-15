# Airflow

References:

1. https://airflow.apache.org/docs/helm-chart/stable/index.html
2. https://airflow.apache.org/docs/apache-airflow/stable/administration-and-deployment/kubernetes.html

## Testing Locally

```bash
# Start the port forward
kubectl port-forward svc/airflow-webserver 8080:8080 -n airflow

open http://localhost:8080/home

# Kill the port forward
pkill -f "kubectl port-forward.*airflow-webserver"
```

Visit http://localhost:8080/home

- username: `admin`
- password: `admin`
