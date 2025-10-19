#!/usr/bin/with-contenv bashio
# shellcheck shell=bash

export LD_LIBRARY_PATH=/usr/local/lib64
export LANG=C
PATH="/usr/local/bin:/usr/local/sbin:/usr/bin:/usr/sbin:/bin:/sbin"

CONFIG_PATH=/data/options.json

# Parse the variables
DEBUG="$(jq --raw-output '.debug' "$CONFIG_PATH")"
RTLTCPDEBUG="$(jq --raw-output '.rtltcpdebug' "$CONFIG_PATH")"

AMR_MSGTYPE="$(jq --raw-output '.msgType' "$CONFIG_PATH")"
AMR_IDS="$(jq --raw-output '.ids' "$CONFIG_PATH")"
DURATION="$(jq --raw-output '.duration' "$CONFIG_PATH")"
PT="$(jq --raw-output '.pause_time' "$CONFIG_PATH")"
GUOM="$(jq --raw-output '.gas_unit_of_measurement' "$CONFIG_PATH")"
EUOM="$(jq --raw-output '.electric_unit_of_measurement' "$CONFIG_PATH")"
WUOM="$(jq --raw-output '.water_unit_of_measurement' "$CONFIG_PATH")"

GMP="$(jq --raw-output '.gas_multiplier' "$CONFIG_PATH")"
EMP="$(jq --raw-output '.electric_multiplier' "$CONFIG_PATH")"
WMP="$(jq --raw-output '.water_multiplier' "$CONFIG_PATH")"

if [[ -z "$AMR_MSGTYPE" || "$AMR_MSGTYPE" == "null" ]]; then
  AMR_MSGTYPE="scm"
fi

if [[ -z "$DURATION" || "$DURATION" == "null" ]]; then
  DURATION="0"
fi

if [[ -z "$PT" || "$PT" == "null" ]]; then
  PT="30"
fi

# Print the set variables to the log
echo "Starting RTLAMR with parameters:"
echo "AMR Message Type = $AMR_MSGTYPE"
echo "AMR Device IDs = $AMR_IDS"
echo "Time Between Readings = $PT"
echo "Duration = $DURATION"
echo "Electric Unit of measurement = $EUOM"
echo "Gas Unit of measurement = $GUOM"
echo "Water Unit of measurement = $WUOM"
echo "Gas Multiplier = $GMP"
echo "Electric Multiplier = $EMP"
echo "Water Multiplier = $WMP"
echo "Debug is $DEBUG"

# Starts the RTL_TCP Application
if [[ "$RTLTCPDEBUG" == "true" ]]; then
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
    '{"state": $st, "extra_state_attributes": {"unique_id": $uid}, "attributes": {"entity_id": $uid, "device_class": "water", "unit_of_measurement": "gal", "state_class": "total_increasing", "leak": $le, "leak_now": $ln, "BackFlow": $bf, "NoUse": $nouse, "Unknown1": $unkn1, "Unknown3": $unkn3 }}')

  printf '%s' "$restdata"
}

# Function, posts data to home assistant that is gathered by the rtlamr script
postto() {
  local payload="$1"
  local device_id
  local endpoint_id
  local type
  local restdata

  if [[ "$DEBUG" == "true" ]]; then
    printf $'\n\nRTLAMR JSON Output\n\n'
    printf '%s\n' "$payload"
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

  if [[ "$DEBUG" == "true" ]]; then
    printf $'\n\nJSON Output to HA REST API\n\n'
    printf '%s\n' "$restdata"
  fi

  # shellcheck disable=SC2154 # Provided by the Supervisor at runtime
  curl -s -o /dev/null -w "%{http_code}" -X POST -H "Authorization: Bearer $SUPERVISOR_TOKEN" \
    -H "Content-Type: application/json" \
    -d "$restdata" \
    "http://supervisor/core/api/states/sensor.$device_id"
  printf $'\n'
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
