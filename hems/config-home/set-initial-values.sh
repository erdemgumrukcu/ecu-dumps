#!/usr/bin/env bash
set -euo pipefail

CORE_COMMAND_URL="${CORE_COMMAND_URL:-http://127.0.0.1:59882}"

write_value() {
  local device="$1" resource="$2" value="$3"
  printf '%s/%s = %s\n' "$device" "$resource" "$value"
  curl --fail-with-body --silent --show-error --request PUT \
    --header 'Content-Type: application/json' \
    --data "{\"${resource}\":${value}}" \
    "${CORE_COMMAND_URL}/api/v3/device/name/${device}/${resource}"
  printf '\n'
}

# Edit these values before running on the Docker host.
write_value Load ActivePower 4.0
write_value Load ReactivePower 0.0

write_value PV ActivePower 3.0
write_value PV ReactivePower 0.0

write_value Battery ActivePower 0.0
write_value Battery ReactivePower 0.0
write_value Battery BatterySOC 0.5
write_value Battery BatteryCapacity 10.0
write_value Battery BatteryMaxChargingPower 5.0
write_value Battery BatteryMaxDischargingPower 5.0

write_value EVC ActivePower 0.0
write_value EVC ReactivePower 0.0
write_value EVC BatterySOC 0.5
write_value EVC BatteryCapacity 50.0
write_value EVC BatteryMaxChargingPower 5.0
write_value EVC BatteryMaxDischargingPower 5.0