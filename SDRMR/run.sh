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
function scmplus_parse {
  STATE="$(jq -rc '.Message.Consumption' <<<"$line" | tr -s ' ' '_')"
  EPT="$(jq -rc '.Message.EndpointType' <<<"$line" | tr -s ' ' '_')"

  if [[ "$EPT" == "null" ]]; then
    EPT="$(jq -rc '.Message.Type' <<<"$line" | tr -s ' ' '_')"
  fi
  scmUID="${DEVICEID}-sdrmr"
  if is_gas "$EPT"; then
    STATE=$(bc <<< "$STATE*$GMP")
    RESTDATA=$(jq -nrc --arg state "$STATE" --arg uid "$scmUID" --arg uom "$GUOM" '{"state": $state, "attributes": {"unique_id": $uid, "state_class": "total_increasing", "device_class": "gas",  "unit_of_measurement": $uom }}')
  elif is_electric "$EPT"; then
    STATE=$(bc <<< "$STATE*$EMP")
    RESTDATA=$(jq -nrc --arg state "$STATE" --arg uid "$scmUID" --arg uom "$EUOM" '{"state": $state, "attributes": {"unique_id": $uid, "device_class": "energy", "unit_of_measurement": $uom, "state_class": "total_increasing" }}')
  elif is_water "$EPT"; then
    STATE=$(bc <<< "$STATE*$WMP")
    RESTDATA=$(jq -nrc --arg state "$STATE" --arg uid "$scmUID" --arg uom "$WUOM" '{"state": $state, "attributes": {"unique_id": $uid, "device_class": "water", "unit_of_measurement": $uom, "state_class": "total_increasing" }}')
  else
    RESTDATA=$(jq -nrc --arg state "$STATE" --arg uid "$scmUID" '{"state": $state, "attributes": {"unique_id": $uid}}')
  fi
  }

# Function, parses R900 data
function r900_parse {
  STATE="$(jq -rc '.Message.Consumption' <<<"$line" | tr -s ' ' '_')"
  STATE=$(bc <<< "$STATE*$WMP")
  LEAK="$(jq -rc '.Message.Leak' <<<"$line" | tr -s ' ' '_')"
  LEAKNOW="$(jq -rc '.Message.LeakNow' <<<"$line" | tr -s ' ' '_')"
  BACKFLOW="$(jq -rc '.Message.BackFlow' <<<"$line" | tr -s ' ' '_')"
  UNKN1="$(jq -rc '.Message.Unkn1' <<<"$line" | tr -s ' ' '_')"
  UNKN3="$(jq -rc '.Message.Unkn3' <<<"$line" | tr -s ' ' '_')"
  NOUSE="$(jq -rc '.Message.NoUse' <<<"$line" | tr -s ' ' '_')"
  RESTDATA=$(jq -nrc \
  --arg st "$STATE" \
  --arg le "$LEAK" \
  --arg ln "$LEAKNOW" \
  --arg uid "${DEVICEID}-sdrmr" \
  --arg bf "$BACKFLOW" \
  --arg unkn1 "$UNKN1" \
  --arg unkn3 "$UNKN3" \
  --arg nouse "$NOUSE" \
  '{"state": $st, "extra_state_attributes": {"unique_id": $uid}, "attributes": { "entity_id": $uid, "device_class": "water", "unit_of_measurement": "gal", "state_class": "total_increasing", "leak": $le, "leak_now": $ln, "BackFlow": $bf, "NoUse": $nouse, "Unknown1": $unkn1, "Unknown3": $unkn3 }}')
}

# Function, posts data to home assistant that is gathered by the rtlamr script
function postto {
  if [[ "$DEBUG" == "true" ]]; then
    echo -e "\n\nRTLAMR JSON Output\n"
    echo "$line"
  fi
  DEVICEID="$(jq -rc '.Message.ID' <<<"$line" | tr -s ' ' '_')"
  TYPE="$(jq -rc '.Type' <<<"$line" | tr -s ' ' '_')"
  if [ "$DEVICEID" = "null" ]; then
    DEVICEID="$(jq -rc '.Message.EndpointID' <<<"$line" | tr -s ' ' '_')"
  fi

  if [ "$TYPE" = "R900" ]; then
    r900_parse
  elif [ "$TYPE" = "SCM+" ] || [ "$TYPE" = "SCM" ]; then
    scmplus_parse
  else
    VAL="$(jq -rc '.Message.Consumption' <<<"$line" | tr -s ' ' '_')" # replace ' ' with '_'
    RESTDATA=$(jq -nrc --arg state "$VAL" '{"state": $state}')
  fi

  if [[ "$DEBUG" == "true" ]]; then
    echo -e "\n\nJSON Output to HA REST API\n"
    echo "$RESTDATA"
  fi


  # shellcheck disable=SC2154 # Provided by the Supervisor at runtime
  curl -s -o /dev/null -w "%{http_code}" -X POST -H "Authorization: Bearer $SUPERVISOR_TOKEN" \
  -H "Content-Type: application/json" \
  -d "$RESTDATA" \
  "http://supervisor/core/api/states/sensor.$DEVICEID"
  echo -e "\n"
}

# Set flags if variables are set
declare -a RTLAMR_ARGS=(-format json "-msgtype=$AMR_MSGTYPE")

if [[ -n "$AMR_IDS" && "$AMR_IDS" != "null" ]]; then
  RTLAMR_ARGS+=("-filterid=$AMR_IDS")
fi

if [[ "$DURATION" != "0" ]]; then
  RTLAMR_ARGS+=("-duration=${DURATION}s")
fi
# Function, runs a rtlamr listen event
function listener {
  /go/bin/rtlamr "${RTLAMR_ARGS[@]}" | while IFS= read -r line
  do
    postto
  done
}

# Main Event Loop, will restart if buffer runs out
while true; do
  listener
  sleep "$PT"
done
