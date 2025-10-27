ARG BUILD_FROM
FROM $BUILD_FROM

ARG NETCLIENT_VERSION=v0.24.2
ARG TARGETPLATFORM

ENV NETCLIENT_VERSION=${NETCLIENT_VERSION}

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN set -eux; \
    apk add --no-cache bash curl wireguard-tools iproute2 ca-certificates tar; \
    mkdir -p /etc/netclient

RUN set -eux; \
    case "${TARGETPLATFORM}" in \
        "linux/amd64") NETCLIENT_ARCH="amd64" ;; \
        "linux/arm64") NETCLIENT_ARCH="arm64" ;; \
        "linux/arm/v7") NETCLIENT_ARCH="armv7" ;; \
        *) echo "Unsupported architecture: ${TARGETPLATFORM}" >&2; exit 1 ;; \
    esac; \
    BASE_URL="https://github.com/gravitl/netmaker/releases/download/${NETCLIENT_VERSION}"; \
    FOUND=0; \
    for SUFFIX in "linux-${NETCLIENT_ARCH}" "${NETCLIENT_ARCH}"; do \
        for EXT in "" ".tar.gz"; do \
            NETCLIENT_URL="${BASE_URL}/netclient-${SUFFIX}${EXT}"; \
            if curl -fsSL "${NETCLIENT_URL}" -o /tmp/netclient${EXT}; then \
                if [ "${EXT}" = ".tar.gz" ]; then \
                    tar -xzf /tmp/netclient${EXT} -C /usr/local/bin netclient; \
                    rm -f /tmp/netclient${EXT}; \
                else \
                    mv /tmp/netclient /usr/local/bin/netclient; \
                fi; \
                chmod +x /usr/local/bin/netclient; \
                FOUND=1; \
                break 2; \
            fi; \
        done; \
    done; \
    if [ "${FOUND}" -ne 1 ]; then \
        echo "Failed to download netclient for ${TARGETPLATFORM}" >&2; \
        exit 1; \
    fi

COPY run.sh /run.sh
RUN chmod 0755 /run.sh

CMD ["/run.sh"]
