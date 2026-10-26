# HEMS REST device service on ECU B

This Compose project adds the ARM64 REST device service and Python miniflex poller to the running
EdgeX deployment. It requires the existing `edgex_edgex-network`, core-keeper,
core-metadata, core-data, and MQTT broker. It does not create or replace those
services.

The Modbus service also reuses the existing `edgex_macvlan` network. Both
networks are declared external: this project neither creates nor deletes
them. Verify the existing macvlan subnet includes `169.254.84.11` and that
this address is not already assigned before starting `device-pqi`.

The `device-pqi` container still registers in EdgeX as `device-modbus`.
Its bridge-network alias `edgex-device-modbus-bridge` preserves compatibility
with the listener hostname and service address saved in ECU B's Keeper and
metadata. Only this container should own that alias on `edgex_edgex-network`.
Recreate `device-pqi` after adding the alias; no Keeper overwrite is required.

The REST container calls ECU1 directly over HTTP:

```text
core-command -> edgex-device-hems -> 134.130.88.189:8000
```

No Nginx route or additional listener is required.
The upstream API has no authentication or TLS; restrict access to trusted
networks.

ECU B's existing Core Keeper uses port `59883`. The configuration-provider
URL in Compose must match that internal listening port.

The container is named `edgex-device-hems`. The REST SDK's `--instance=hems`
option registers it in EdgeX as `device-rest_hems`, avoiding a collision with
an existing `device-rest` service.

## Start and test

On ECU B, from the transferred project directory:

```sh
cd /tmp/demo/edgeismp
docker compose config --quiet
docker compose up -d --pull never device-hems
docker compose logs --tail=100 device-hems
```

The ARM64 image must already be loaded locally when using `--pull never`.
The `/tmp` deployment is temporary and may be cleared on reboot. For a
persistent deployment, move the project to confirmed persistent storage.

No host port is needed for the device service: core-command reaches it over
the shared network at `edgex-device-hems:59986`.

To test connectivity from the REST container's network namespace, reuse the
existing proxy image's curl without sending the request through Nginx:

```sh
docker run --rm --pull never \
  --network container:edgex-device-hems \
  --entrypoint curl \
  "$(docker inspect blel-reverse-proxy --format '{{.Config.Image}}')" \
  -i --fail-with-body --connect-timeout 5 --max-time 30 \
  'http://134.130.88.189:8000/api/v1/flexibility-range?delta_t_seconds=900'
```

The proxy image is only a convenient locally available test tool, not a
runtime dependency of the REST service. Expect HTTP 200 with JSON.

## Update an already-registered device

Editing device YAML alone may not overwrite an existing metadata record.
After transferring the updated YAML for future starts, update `Device-HEMS`
explicitly. This uses the existing proxy container's curl to call metadata
directly; Nginx is not involved:

```sh
docker exec blel-reverse-proxy curl -i --fail-with-body \
  -X PATCH http://edgex-core-metadata:59881/api/v3/device \
  -H 'Content-Type: application/json' \
  -d '[{"apiVersion":"v3","device":{"name":"Device-HEMS","description":"ECU1 HEMS API accessed directly from ECU B","protocols":{"REST":{"Host":"134.130.88.189","Port":"8000","Path":"api/v1"}}}}]'
```

Check both the HTTP status and the per-device response status for success.
The REST SDK receives the metadata update through its device callback.
Verify the registered protocol settings:

```sh
docker exec blel-reverse-proxy curl -sS --fail-with-body --max-time 10 \
  http://edgex-core-metadata:59881/api/v3/device/name/Device-HEMS
```

## Read through core-command

```sh
curl -i --fail-with-body \
  'http://127.0.0.1:59882/api/v3/device/name/Device-HEMS/flexibility-range?delta_t_seconds=900'
```

The driver combines the device's `Path` (`api/v1`) with the resource name
(`flexibility-range`) and forwards the query parameter, producing:

```text
http://134.130.88.189:8000/api/v1/flexibility-range?delta_t_seconds=900
```

The EdgeX event contains an Object reading with the upstream JSON, not an
individual Float64 reading. Supply `delta_t_seconds` in each read request;
`900` means a 15-minute calculation horizon, not a polling interval.
No device AutoEvents are configured; miniflex performs polling as described below.

## Miniflex polling

The `miniflex` service reads the REST service directly, bypassing the existing
core-command's Object serialization issue. Its `HEMS_FLEX_READ_PATH` environment
variable contains the complete URL, including `delta_t_seconds=900`.
`CONTROL_REFRESH_INTERVAL_SECONDS=60` requests a reading immediately at startup
and every minute afterward. Failed requests or invalid readings are logged,
and retried at the next interval without substituting zero values.

The response's `current_net`, `hems_ub`, and `hems_lb` are printed to container
logs. No setpoints are written. Transformer control is optional: configure
`TRAFO_SENSOR_P_READ_PATH` and, if needed, `TRANSFORMER_LIMIT` to enable the
existing control calculation.

On an ARM64 machine with internet access, build the image:

```sh
docker compose build miniflex
```

For offline ECU B deployment, save the built image, transfer the archive, and
load it with `docker load` just as for the REST image:

```sh
docker image save -o miniflex.tar miniflex:local
```

On ECU B, once both images and the configuration folder are present:

```sh
cd /tmp/demo/edgeismp
docker compose up -d --no-build --pull never miniflex
docker compose logs -f miniflex
```

The Python base image supports ARM64; building on an x86 Ubuntu PC requires an
ARM64-capable builder/emulation, for example:

```sh
docker buildx build --platform linux/arm64 --load -t miniflex:local ./miniflex
```

If core-command is not published on host port 59882, make the same request
from a container on `edgex_edgex-network` using `edgex-core-command:59882`.
