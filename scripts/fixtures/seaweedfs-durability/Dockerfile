FROM docker.io/library/python:3.14-alpine@sha256:f6a589d43c42b9e7f7dc67a12d37132491f362859a5d750607710cc56da3bc72
RUN apk add --no-cache strace=6.19-r1
ARG BINARY
COPY ${BINARY} /usr/local/bin/weed
ENTRYPOINT ["weed"]
