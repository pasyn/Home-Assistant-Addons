#!/usr/bin/with-contenv bashio
# shellcheck shell=bash

export LD_LIBRARY_PATH=/usr/local/lib64
export LANG=C
PATH="/usr/local/bin:/usr/local/sbin:/usr/bin:/usr/sbin:/bin:/sbin"

# Parse the variables
DEBUG=$(bashio::config 'debug')

AMR_MSGTYPE=$(bashio::config 'msgType')
AMR_IDS=$(bashio::config 'ids')
DURATION=$(bashio::config 'duration')
PT=$(bashio::config 'pause_time')
GUOM=$(bashio::config 'gas_unit_of_measurement')
EUOM=$(bashio::config 'electric_unit_of_measurement')
WUOM=$(bashio::config 'water_unit_of_measurement')

GMP=$(bashio::config 'gas_multiplier')
EMP=$(bashio::config 'electric_multiplier')
WMP=$(bashio::config 'water_multiplier')

if bashio::var.is_empty "${AMR_MSGTYPE}" || [[ "${AMR_MSGTYPE}" == "null" ]]; then
  AMR_MSGTYPE="scm"
fi

if bashio::var.is_empty "${DURATION}" || [[ "${DURATION}" == "null" ]]; then
  DURATION="0"
fi

if bashio::var.is_empty "${PT}" || [[ "${PT}" == "null" ]]; then
  PT="30"
fi

# Print the set variables to the log
bashio::log.info "Starting RTLAMR with parameters:"
bashio::log.info "AMR Message Type = ${AMR_MSGTYPE}"
bashio::log.info "AMR Device IDs = ${AMR_IDS}"
bashio::log.info "Time Between Readings = ${PT}"
bashio::log.info "Duration = ${DURATION}"
bashio::log.info "Electric Unit of measurement = ${EUOM}"
bashio::log.info "Gas Unit of measurement = ${GUOM}"
bashio::log.info "Water Unit of measurement = ${WUOM}"
bashio::log.info "Gas Multiplier = ${GMP}"
bashio::log.info "Electric Multiplier = ${EMP}"
bashio::log.info "Water Multiplier = ${WMP}"
bashio::log.info "Debug is ${DEBUG}"

# Starts the RTL_TCP Application
if bashio::config.true 'rtltcpdebug'; then
  /usr/local/bin/rtl_tcp &
else
  /usr/local/bin/rtl_tcp > /dev/null &
fi

# Sleep to fill buffer a bit
sleep 5

function is_gas() {
    local value=$1
    local list=(0 1 2 9 12 156 188)

    for candidate in "${list[@]}"; do
        if [[ "$candidate" == "$value" ]]; then
            return 0
        fi
    done

    return 1
}
function is_electric() {
    local value=$1
    local list=(4 5 7 8)

    for candidate in "${list[@]}"; do
        if [[ "$candidate" == "$value" ]]; then
            return 0
        fi
    done

    return 1
}
function is_water() {
    local value=$1
    local list=(3 11 13 171)

    for candidate in "${list[@]}"; do
        if [[ "$candidate" == "$value" ]]; then
            return 0
        fi
    done

    return 1
}

# Function, parses scm and scmplus data
scmplus_parse() {
  local payload="$1"
  local device_id="$2"
  local state
  local endpoint
  local uid
  local restdata

  state="$(jq -rc '.Message.Consumption' <<<"$payload" | tr -s ' ' '_')"
  endpoint="$(jq -rc '.Message.EndpointType' <<<"$payload" | tr -s ' ' '_')"

  if [[ "$endpoint" == "null" ]]; then
    endpoint="$(jq -rc '.Message.Type' <<<"$payload" | tr -s ' ' '_')"
  fi

  uid="${device_id}-sdrmr"

  if is_gas "$endpoint"; then
    state=$(bc <<< "$state*$GMP")
    restdata=$(jq -nrc --arg state "$state" --arg uid "$uid" --arg uom "$GUOM" '{"state": $state, "attributes": {"unique_id": $uid, "state_class": "total_increasing", "device_class": "gas", "unit_of_measurement": $uom }}')
  elif is_electric "$endpoint"; then
    state=$(bc <<< "$state*$EMP")
    restdata=$(jq -nrc --arg state "$state" --arg uid "$uid" --arg uom "$EUOM" '{"state": $state, "attributes": {"unique_id": $uid, "device_class": "energy", "unit_of_measurement": $uom, "state_class": "total_increasing" }}')
  elif is_water "$endpoint"; then
    state=$(bc <<< "$state*$WMP")
    restdata=$(jq -nrc --arg state "$state" --arg uid "$uid" --arg uom "$WUOM" '{"state": $state, "attributes": {"unique_id": $uid, "device_class": "water", "unit_of_measurement": $uom, "state_class": "total_increasing" }}')
  else
    restdata=$(jq -nrc --arg state "$state" --arg uid "$uid" '{"state": $state, "attributes": {"unique_id": $uid}}')
  fi

  printf '%s' "$restdata"
}

# Function, parses R900 data
r900_parse() {
  local payload="$1"
  local device_id="$2"
  local state
  local restdata
  local uid
  local leak
  local leak_now
  local backflow
  local unknown1
  local unknown3
  local no_use

  state="$(jq -rc '.Message.Consumption' <<<"$payload" | tr -s ' ' '_')"
  state=$(bc <<< "$state*$WMP")
  leak="$(jq -rc '.Message.Leak' <<<"$payload" | tr -s ' ' '_')"
  leak_now="$(jq -rc '.Message.LeakNow' <<<"$payload" | tr -s ' ' '_')"
  backflow="$(jq -rc '.Message.BackFlow' <<<"$payload" | tr -s ' ' '_')"
  unknown1="$(jq -rc '.Message.Unkn1' <<<"$payload" | tr -s ' ' '_')"
  unknown3="$(jq -rc '.Message.Unkn3' <<<"$payload" | tr -s ' ' '_')"
  no_use="$(jq -rc '.Message.NoUse' <<<"$payload" | tr -s ' ' '_')"
  uid="${device_id}-sdrmr"

  restdata=$(jq -nrc \
    --arg st "$state" \
    --arg le "$leak" \
    --arg ln "$leak_now" \
    --arg uid "$uid" \
    --arg bf "$backflow" \
    --arg unkn1 "$unknown1" \
    --arg unkn3 "$unknown3" \
    --arg nouse "$no_use" \
    --arg uom "$WUOM" \
    '{"state": $st, "attributes": {"unique_id": $uid, "device_class": "water", "unit_of_measurement": $uom, "state_class": "total_increasing", "leak": $le, "leak_now": $ln, "BackFlow": $bf, "NoUse": $nouse, "Unknown1": $unkn1, "Unknown3": $unkn3 }}')

  printf '%s' "$restdata"
}

# Function, posts data to home assistant that is gathered by the rtlamr script
postto() {
  local payload="$1"
  local device_id
  local endpoint_id
  local type
  local restdata
  local http_code

  if bashio::config.true 'debug'; then
    bashio::log.debug "RTLAMR JSON Output: ${payload}"
  fi

  device_id="$(jq -rc '.Message.ID' <<<"$payload" | tr -s ' ' '_')"
  type="$(jq -rc '.Type' <<<"$payload" | tr -s ' ' '_')"
  if [[ "$device_id" == "null" ]]; then
    endpoint_id="$(jq -rc '.Message.EndpointID' <<<"$payload" | tr -s ' ' '_')"
    device_id="$endpoint_id"
  fi

  if [[ "$type" == "R900" ]]; then
    restdata=$(r900_parse "$payload" "$device_id")
  elif [[ "$type" == "SCM+" ]] || [[ "$type" == "SCM" ]]; then
    restdata=$(scmplus_parse "$payload" "$device_id")
  else
    local value
    value="$(jq -rc '.Message.Consumption' <<<"$payload" | tr -s ' ' '_')"
    restdata=$(jq -nrc --arg state "$value" '{"state": $state}')
  fi

  if bashio::config.true 'debug'; then
    bashio::log.debug "JSON Output to HA REST API: ${restdata}"
  fi

  # shellcheck disable=SC2154 # Provided by the Supervisor at runtime
  http_code=$(curl -s -o /dev/null -w "%{http_code}" -X POST \
    -H "Authorization: Bearer ${SUPERVISOR_TOKEN}" \
    -H "Content-Type: application/json" \
    -d "$restdata" \
    "http://supervisor/core/api/states/sensor.${device_id}")

  bashio::log.info "Posted to sensor.${device_id} - HTTP ${http_code}"
}

# Set flags if variables are set
declare -a RTLAMR_ARGS=(-format json "-msgtype=$AMR_MSGTYPE")

if [[ -n "$AMR_IDS" && "$AMR_IDS" != "null" ]]; then
  RTLAMR_ARGS+=("-filterid=$AMR_IDS")
fi

if [[ -n "$DURATION" && "$DURATION" != "null" && "$DURATION" != "0" ]]; then
  RTLAMR_ARGS+=("-duration=${DURATION}s")
fi

# Function, runs a rtlamr listen event
listener() {
  while IFS= read -r line
  do
    postto "$line"
  done < <(/go/bin/rtlamr "${RTLAMR_ARGS[@]}")
}

# Main Event Loop, will restart if buffer runs out
while true; do
  listener
  sleep "$PT"
done
