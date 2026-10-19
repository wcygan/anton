FROM grafana/loki@sha256:81a6802ec4bd1b88c564494f06376889ed022998a188826190d26d2754ac2aae
ARG PATCH_SHA256
LABEL org.opencontainers.image.version="3.7.8-anton.wal.1" \
      org.opencontainers.image.revision="09e6ce2ff1bdc19763a10265b870c86f51c98655" \
      io.anton.loki.patch.sha256="${PATCH_SHA256}"
COPY --chmod=0755 loki-linux-amd64 /usr/bin/loki
