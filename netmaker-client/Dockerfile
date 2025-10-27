ARG BUILD_FROM
FROM $BUILD_FROM

ARG NETCLIENT_VERSION=v0.24.2
ARG TARGETPLATFORM

ENV NETCLIENT_VERSION=${NETCLIENT_VERSION}

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN set -eux; \
    apk add --no-cache bash curl wireguard-tools iproute2 ca-certificates; \
    mkdir -p /etc/netclient

RUN set -eux; \
    case "${TARGETPLATFORM}" in \
        "linux/amd64") NETCLIENT_ARCH="amd64" ;; \
        "linux/arm64") NETCLIENT_ARCH="arm64" ;; \
        "linux/arm/v7") NETCLIENT_ARCH="armv7" ;; \
        *) echo "Unsupported architecture: ${TARGETPLATFORM}" >&2; exit 1 ;; \
    esac; \
    NETCLIENT_URL="https://github.com/gravitl/netmaker/releases/download/${NETCLIENT_VERSION}/netclient-linux-${NETCLIENT_ARCH}"; \
    curl -fsSL "${NETCLIENT_URL}" -o /usr/local/bin/netclient; \
    chmod +x /usr/local/bin/netclient

COPY run.sh /run.sh
RUN chmod 0755 /run.sh

CMD ["/run.sh"]
