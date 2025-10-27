default:
	@kubectl get nodes

doc:
	@cd docs && bun run start

monitor-talos:
	@talosctl --nodes 192.168.1.98,192.168.1.99,192.168.1.100 dashboard
