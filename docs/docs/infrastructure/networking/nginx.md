---
sidebar_position: 4
---

# NGINX Ingress

NGINX Ingress Controllers provide high-performance HTTP/HTTPS load balancing and routing for the Anton cluster, with separate controllers for external and internal traffic patterns.

## Architecture

```mermaid
flowchart TD
    subgraph external_traffic[External Traffic Path]
        cloudflare[Cloudflare Tunnel]
        nginx_ext[NGINX External<br/>Ingress Controller]
        ext_services[External Services<br/>Public Applications]
    end
    
    subgraph internal_traffic[Internal Traffic Path]  
        local_net[Local Network<br/>192.168.1.0/24]
        nginx_int[NGINX Internal<br/>Ingress Controller]
        int_services[Internal Services<br/>Private Applications]
    end
    
    subgraph backend[Backend Services]
        pods[Application Pods<br/>Workloads]
        services[Kubernetes Services<br/>Load Balancing]
    end
    
    subgraph config[Configuration]
        ingress_ext[External Ingress<br/>Resources]
        ingress_int[Internal Ingress<br/>Resources] 
        configmaps[ConfigMaps<br/>NGINX Configuration]
        secrets[TLS Secrets<br/>SSL Certificates]
    end
    
    cloudflare --> nginx_ext
    nginx_ext --> ext_services
    
    local_net --> nginx_int
    nginx_int --> int_services
    
    ext_services --> services
    int_services --> services
    services --> pods
    
    ingress_ext --> nginx_ext
    ingress_int --> nginx_int
    configmaps --> nginx_ext
    configmaps --> nginx_int
    secrets --> nginx_ext
    secrets --> nginx_int
    
    classDef external fill:#3498db,color:white
    classDef internal fill:#e74c3c,color:white
    classDef backend_comp fill:#f39c12,color:white
    classDef config_comp fill:#9b59b6,color:white
    
    class cloudflare,nginx_ext,ext_services external
    class local_net,nginx_int,int_services internal
    class pods,services backend_comp
    class ingress_ext,ingress_int,configmaps,secrets config_comp
```

## Dual Controller Setup

### External Ingress Controller
- **Purpose**: Handle traffic from Cloudflare tunnel
- **IngressClass**: `external`
- **Load Balancer**: ClusterIP (internal routing)
- **TLS**: Let's Encrypt certificates
- **Access**: Public internet via Cloudflare

### Internal Ingress Controller
- **Purpose**: Handle local network traffic
- **IngressClass**: `internal`
- **Load Balancer**: NodePort or LoadBalancer
- **TLS**: Internal CA certificates
- **Access**: Local network only

## Controller Configuration

### External Controller

```yaml
# NGINX External Ingress Controller
apiVersion: apps/v1
kind: Deployment
metadata:
  name: nginx-ingress-external
  namespace: network
spec:
  replicas: 2
  selector:
    matchLabels:
      app: nginx-ingress-external
  template:
    spec:
      containers:
        - name: controller
          image: registry.k8s.io/ingress-nginx/controller:v1.8.1
          args:
            - /nginx-ingress-controller
            - --ingress-class=external
            - --configmap=network/nginx-external-config
            - --default-ssl-certificate=network/external-tls-secret
            - --enable-ssl-passthrough
            - --metrics-bind-address=0.0.0.0:10254
          ports:
            - name: http
              containerPort: 80
            - name: https
              containerPort: 443
            - name: metrics
              containerPort: 10254
```

### Internal Controller

```yaml
# NGINX Internal Ingress Controller
apiVersion: apps/v1
kind: Deployment
metadata:
  name: nginx-ingress-internal
  namespace: network
spec:
  replicas: 2
  template:
    spec:
      containers:
        - name: controller
          image: registry.k8s.io/ingress-nginx/controller:v1.8.1
          args:
            - /nginx-ingress-controller
            - --ingress-class=internal
            - --configmap=network/nginx-internal-config
            - --default-backend-service=network/default-backend
            - --publish-service=network/nginx-internal-lb
```

## Ingress Resource Examples

### External Service Ingress

```yaml
# Public service accessible via Cloudflare
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: grafana-external
  namespace: monitoring
  annotations:
    kubernetes.io/ingress.class: external
    cert-manager.io/cluster-issuer: letsencrypt-prod
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
    nginx.ingress.kubernetes.io/force-ssl-redirect: "true"
spec:
  tls:
    - hosts:
        - grafana.example.com
      secretName: grafana-tls
  rules:
    - host: grafana.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: kube-prometheus-stack-grafana
                port:
                  number: 80
```

### Internal Service Ingress

```yaml
# Internal service for local network access
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: grafana-internal
  namespace: monitoring
  annotations:
    kubernetes.io/ingress.class: internal
    cert-manager.io/cluster-issuer: ca-issuer
    nginx.ingress.kubernetes.io/auth-type: basic
    nginx.ingress.kubernetes.io/auth-secret: basic-auth
spec:
  tls:
    - hosts:
        - grafana.local
      secretName: grafana-internal-tls
  rules:
    - host: grafana.local
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: kube-prometheus-stack-grafana
                port:
                  number: 80
```

## Performance Tuning

### Global Configuration

```yaml
# NGINX performance configuration
apiVersion: v1
kind: ConfigMap
metadata:
  name: nginx-external-config
  namespace: network
data:
  # Worker processes and connections
  worker-processes: "auto"
  worker-connections: "1024"
  worker-rlimit-nofile: "65535"
  
  # Performance tuning
  keepalive-timeout: "65"
  keepalive-requests: "100"
  client-body-buffer-size: "128k"
  client-max-body-size: "50m"
  proxy-buffer-size: "4k"
  proxy-buffers: "8 4k"
  
  # Compression
  enable-gzip: "true"
  gzip-level: "6"
  gzip-types: "text/plain application/json application/javascript text/css application/xml text/xml application/xml+rss text/javascript"
  
  # SSL optimization
  ssl-protocols: "TLSv1.2 TLSv1.3"
  ssl-ciphers: "ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384"
  ssl-session-cache: "shared:SSL:10m"
  ssl-session-timeout: "10m"
```

### Per-Service Optimization

```yaml
# Service-specific NGINX annotations
metadata:
  annotations:
    # Rate limiting
    nginx.ingress.kubernetes.io/rate-limit: "100"
    nginx.ingress.kubernetes.io/rate-limit-window: "1m"
    
    # Connection limits
    nginx.ingress.kubernetes.io/limit-connections: "20"
    
    # Proxy timeouts
    nginx.ingress.kubernetes.io/proxy-connect-timeout: "5"
    nginx.ingress.kubernetes.io/proxy-send-timeout: "60"
    nginx.ingress.kubernetes.io/proxy-read-timeout: "60"
    
    # Buffer sizes
    nginx.ingress.kubernetes.io/proxy-buffer-size: "16k"
    nginx.ingress.kubernetes.io/proxy-buffers-number: "8"
    
    # Enable caching
    nginx.ingress.kubernetes.io/proxy-cache-valid: "200 302 10m"
    nginx.ingress.kubernetes.io/proxy-cache-valid: "404 1m"
```

## Load Balancing

### Backend Selection

```yaml
# Load balancing algorithm configuration
metadata:
  annotations:
    # Round-robin (default)
    nginx.ingress.kubernetes.io/upstream-hash-by: ""
    
    # IP hash for session persistence
    nginx.ingress.kubernetes.io/upstream-hash-by: "$remote_addr"
    
    # Cookie-based persistence
    nginx.ingress.kubernetes.io/affinity: "cookie"
    nginx.ingress.kubernetes.io/session-cookie-name: "nginx-ingress"
    nginx.ingress.kubernetes.io/session-cookie-expires: "86400"
    nginx.ingress.kubernetes.io/session-cookie-max-age: "86400"
    nginx.ingress.kubernetes.io/session-cookie-path: "/"
```

### Health Checks

```yaml
# Backend health monitoring
metadata:
  annotations:
    # Health check path
    nginx.ingress.kubernetes.io/backend-protocol: "HTTP"
    nginx.ingress.kubernetes.io/upstream-vhost: "$service_name.$namespace.svc.cluster.local"
    
    # Custom health check
    nginx.ingress.kubernetes.io/custom-http-errors: "404,503"
    nginx.ingress.kubernetes.io/default-backend: "network/custom-default-backend"
```

## Security Features

### Authentication

```yaml
# Basic authentication
metadata:
  annotations:
    nginx.ingress.kubernetes.io/auth-type: basic
    nginx.ingress.kubernetes.io/auth-secret: basic-auth-secret
    nginx.ingress.kubernetes.io/auth-realm: "Restricted Area"

---
# OAuth2 authentication with external provider
metadata:
  annotations:
    nginx.ingress.kubernetes.io/auth-url: "https://auth.example.com/oauth2/auth"
    nginx.ingress.kubernetes.io/auth-signin: "https://auth.example.com/oauth2/start"
    nginx.ingress.kubernetes.io/auth-response-headers: "X-Auth-Request-User,X-Auth-Request-Email"
```

### SSL/TLS Configuration

```yaml
# SSL/TLS security headers
metadata:
  annotations:
    # HSTS
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
    nginx.ingress.kubernetes.io/force-ssl-redirect: "true"
    
    # Security headers
    nginx.ingress.kubernetes.io/configuration-snippet: |
      add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
      add_header X-Frame-Options "SAMEORIGIN" always;
      add_header X-Content-Type-Options "nosniff" always;
      add_header X-XSS-Protection "1; mode=block" always;
      add_header Referrer-Policy "strict-origin-when-cross-origin" always;
```

### Access Control

```yaml
# IP-based access control
metadata:
  annotations:
    nginx.ingress.kubernetes.io/whitelist-source-range: "192.168.1.0/24,10.0.0.0/8"
    nginx.ingress.kubernetes.io/deny-source-range: "192.168.100.0/24"

# Geographic restrictions (requires GeoIP module)
metadata:
  annotations:
    nginx.ingress.kubernetes.io/server-snippet: |
      if ($geoip_country_code != US) {
        return 403;
      }
```

## Monitoring and Observability

### Prometheus Metrics

```yaml
# ServiceMonitor for NGINX metrics
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: nginx-ingress-metrics
spec:
  selector:
    matchLabels:
      app: nginx-ingress
  endpoints:
    - port: metrics
      path: /metrics
      interval: 30s
```

### Key Metrics to Monitor

```promql
# Request rate per ingress
sum(rate(nginx_ingress_controller_requests_total[5m])) by (ingress)

# Response time percentiles
histogram_quantile(0.95, 
  sum(rate(nginx_ingress_controller_request_duration_seconds_bucket[5m])) by (le, ingress)
)

# Error rate
sum(rate(nginx_ingress_controller_requests_total{status!~"2.."}[5m])) by (ingress)

# Active connections
nginx_ingress_controller_nginx_process_connections
```

### Log Analysis

```bash
# View NGINX access logs
kubectl logs -n network -l app=nginx-ingress-external | grep access

# Monitor error logs
kubectl logs -n network -l app=nginx-ingress-external | grep error

# Real-time log streaming
kubectl logs -n network -f deployment/nginx-ingress-external
```

## Management Commands

### Controller Management

```bash
# Check controller status
kubectl get pods -n network -l app=nginx-ingress

# View controller configuration
kubectl get configmap -n network nginx-external-config -o yaml

# Restart controllers
kubectl rollout restart deployment/nginx-ingress-external -n network
kubectl rollout restart deployment/nginx-ingress-internal -n network

# Check ingress resources
kubectl get ingress -A
```

### SSL Certificate Management

```bash
# View TLS certificates
kubectl get certificates -A

# Check certificate status
kubectl describe certificate grafana-tls -n monitoring

# Manual certificate renewal (if needed)
kubectl delete secret grafana-tls -n monitoring
# cert-manager will automatically recreate
```

### Debugging

```bash
# Test ingress connectivity
kubectl run test-client --image=curlimages/curl --rm -it -- \
  curl -H "Host: grafana.example.com" http://nginx-external/

# Check backend service connectivity
kubectl exec -n network deployment/nginx-ingress-external -- \
  curl -I http://kube-prometheus-stack-grafana.monitoring:80

# Validate NGINX configuration
kubectl exec -n network deployment/nginx-ingress-external -- \
  nginx -t
```

## Troubleshooting

### Common Issues

```bash
# Check ingress controller logs for errors
kubectl logs -n network -l app=nginx-ingress-external | grep -i error

# Verify ingress resource configuration
kubectl describe ingress grafana-external -n monitoring

# Test DNS resolution
kubectl run dns-test --image=busybox --rm -it -- \
  nslookup kube-prometheus-stack-grafana.monitoring.svc.cluster.local

# Check service endpoints
kubectl get endpoints -n monitoring kube-prometheus-stack-grafana
```

### Performance Issues

```bash
# Monitor controller resource usage
kubectl top pods -n network -l app=nginx-ingress

# Check connection statistics
kubectl exec -n network deployment/nginx-ingress-external -- \
  curl -s http://localhost:18080/nginx_status

# Analyze request patterns
kubectl logs -n network -l app=nginx-ingress-external | \
  grep "GET\|POST" | head -20
```

### SSL/TLS Issues

```bash
# Test SSL certificate
openssl s_client -connect grafana.example.com:443 -servername grafana.example.com

# Check certificate expiration
kubectl get certificates -A -o wide

# Verify cert-manager status
kubectl get issuers,clusterissuers -A
```

NGINX Ingress Controllers provide robust, high-performance HTTP/HTTPS load balancing with extensive customization options, security features, and comprehensive monitoring capabilities for the Anton cluster's ingress traffic management.