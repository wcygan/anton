default:
	@kubectl get nodes

doc:
	@cd docs && bun run start

monitor-talos:
	@talosctl --nodes 192.168.1.98,192.168.1.99,192.168.1.100 dashboard

hubble:
	@echo "Starting Hubble UI on http://localhost:12000"
	@open http://localhost:12000 &
	@kubectl port-forward -n kube-system svc/hubble-ui 12000:80
