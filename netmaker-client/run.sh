#!/usr/bin/with-contenv bashio
# shellcheck shell=bash

set -euo pipefail

NETCLIENT_BIN="/usr/local/bin/netclient"
CONFIG_DIR="/data/netmaker"
STATE_FILE="${CONFIG_DIR}/.last_options"

# Globals referenced in cleanup
cleanup_done=0
running=1
daemon_pid=0
post_down_cmd=""
leave_on_stop_enabled="false"
network_id=""

cleanup() {
    if [[ "${cleanup_done}" -eq 1 ]]; then
        return
    fi
    cleanup_done=1
    running=0

    if [[ ${daemon_pid} -ne 0 ]] && kill -0 "${daemon_pid}" 2>/dev/null; then
        bashio::log.info "Stopping Netmaker client daemon (PID ${daemon_pid})"
        kill "${daemon_pid}" 2>/dev/null || true
        wait "${daemon_pid}" 2>/dev/null || true
    fi

    if [[ -n "${post_down_cmd}" ]]; then
        bashio::log.info "Running post-down hook"
        if ! bash -c "${post_down_cmd}"; then
            bashio::log.warning "Post-down hook failed"
        fi
    fi

    if [[ "${leave_on_stop_enabled}" == "true" && -n "${network_id}" ]]; then
        bashio::log.info "Leaving Netmaker network ${network_id}"
        if ! "${NETCLIENT_BIN}" leave -n "${network_id}"; then
            bashio::log.warning "Unable to leave network ${network_id}"
        fi
    fi
}

trap cleanup EXIT
trap 'running=0; exit 0' SIGTERM SIGINT

bashio::log.info "Starting Netmaker client add-on"

mkdir -p "${CONFIG_DIR}"
if [[ ! -L /etc/netclient ]]; then
    rm -rf /etc/netclient 2>/dev/null || true
    ln -s "${CONFIG_DIR}" /etc/netclient
fi

server_url="$(bashio::config 'server_url')"
enrollment_token="$(bashio::config 'enrollment_token')"
enrollment_key="$(bashio::config 'enrollment_key')"
network_id="$(bashio::config 'network_id')"
log_level="$(bashio::config 'log_level')"
post_up_cmd="$(bashio::config 'post_up')"
post_down_cmd="$(bashio::config 'post_down')"
reconnect_interval_raw="$(bashio::config 'reconnect_interval')"

if bashio::config.true 'auto_reconnect'; then
    auto_reconnect_enabled="true"
else
    auto_reconnect_enabled="false"
fi

if bashio::config.true 'leave_on_stop'; then
    leave_on_stop_enabled="true"
else
    leave_on_stop_enabled="false"
fi

# Normalise configuration values
normalize_value() {
    local value="$1"
    if [[ -z "${value}" || "${value}" == "null" ]]; then
        value=""
    fi
    printf '%s' "${value}"
}

server_url="$(normalize_value "${server_url}")"
enrollment_token="$(normalize_value "${enrollment_token}")"
enrollment_key="$(normalize_value "${enrollment_key}")"
network_id="$(normalize_value "${network_id}")"
log_level="$(normalize_value "${log_level}")"
post_up_cmd="$(normalize_value "${post_up_cmd}")"
post_down_cmd="$(normalize_value "${post_down_cmd}")"
reconnect_interval_raw="$(normalize_value "${reconnect_interval_raw}")"

if [[ -z "${server_url}" ]]; then
    bashio::exit.nok "The Netmaker server URL must be provided."
fi

if [[ -z "${network_id}" ]]; then
    bashio::exit.nok "A target Netmaker network ID is required."
fi

if [[ -z "${enrollment_token}" && -z "${enrollment_key}" ]]; then
    bashio::exit.nok "Provide either an enrollment token or an enrollment key."
fi

if [[ -z "${log_level}" ]]; then
    log_level="info"
fi

reconnect_interval="${reconnect_interval_raw:-30}"
if [[ -z "${reconnect_interval}" ]]; then
    reconnect_interval=30
fi
if ! [[ "${reconnect_interval}" =~ ^[0-9]+$ ]]; then
    bashio::log.warning "Reconnect interval '${reconnect_interval}' is invalid, defaulting to 30 seconds."
    reconnect_interval=30
fi
if (( reconnect_interval < 1 )); then
    reconnect_interval=1
fi

signature="$(printf '%s\n%s\n%s\n%s' "${server_url}" "${network_id}" "${enrollment_token}" "${enrollment_key}" | sha256sum | awk '{print $1}')"
previous_signature=""
if [[ -f "${STATE_FILE}" ]]; then
    previous_signature="$(cat "${STATE_FILE}")"
fi

rejoin_required=0
if [[ "${signature}" != "${previous_signature}" ]]; then
    rejoin_required=1
fi

check_membership() {
    if "${NETCLIENT_BIN}" status -n "${network_id}" >/dev/null 2>&1; then
        return 0
    fi
    return 1
}

join_network() {
    local join_args=(join "-s" "${server_url}" "-n" "${network_id}")
    if [[ -n "${enrollment_token}" ]]; then
        join_args+=('-t' "${enrollment_token}")
    else
        join_args+=('-k' "${enrollment_key}")
    fi

    bashio::log.info "Joining Netmaker network ${network_id} via ${server_url}"
    if ! "${NETCLIENT_BIN}" "${join_args[@]}"; then
        bashio::exit.nok "Failed to join Netmaker network ${network_id}."
    fi
}

leave_network() {
    if check_membership; then
        bashio::log.info "Leaving Netmaker network ${network_id} prior to rejoin"
        if ! "${NETCLIENT_BIN}" leave -n "${network_id}"; then
            bashio::log.warning "Failed to leave existing Netmaker network ${network_id}"
        fi
    fi
}

joined_now=0
membership_active=0
if (( rejoin_required == 1 )); then
    if [[ -n "${previous_signature}" ]]; then
        leave_network
    fi
    join_network
    joined_now=1
    membership_active=1
else
    if ! check_membership; then
        join_network
        joined_now=1
        membership_active=1
    else
        bashio::log.info "Existing Netmaker membership detected for ${network_id}."
        membership_active=1
    fi
fi

if (( joined_now == 1 )); then
    printf '%s' "${signature}" > "${STATE_FILE}"
fi

if (( membership_active == 1 )) && [[ -n "${post_up_cmd}" ]]; then
    bashio::log.info "Running post-up hook"
    if ! bash -c "${post_up_cmd}"; then
        bashio::log.warning "Post-up hook failed"
    fi
fi

start_daemon() {
    local daemon_args=(daemon)
    if [[ -n "${log_level}" ]]; then
        daemon_args+=("--log-level" "${log_level}")
    fi

    bashio::log.info "Starting Netmaker daemon (log level: ${log_level})"
    "${NETCLIENT_BIN}" "${daemon_args[@]}" &
    daemon_pid=$!
}

start_daemon

if [[ "${auto_reconnect_enabled}" == "true" ]]; then
    while [[ ${running} -eq 1 ]]; do
        if ! wait "${daemon_pid}"; then
            bashio::log.warning "Netmaker daemon exited unexpectedly"
        fi
        [[ ${running} -eq 0 ]] && break
        bashio::log.info "Restarting Netmaker daemon in ${reconnect_interval} second(s)"
        sleep "${reconnect_interval}"
        start_daemon
    done
else
    wait "${daemon_pid}"
fi

bashio::log.info "Netmaker client add-on stopped"
