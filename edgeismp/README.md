# HEMS REST device service on ECU B

This Compose project adds only the ARM64 REST device service to the running
EdgeX deployment. It requires the existing `edgex_edgex-network`, core-keeper,
core-metadata, core-data, MQTT broker, and `blel-reverse-proxy`. It does not
create or replace those services.

The container is named `edgex-device-hems`. The REST SDK's `--instance=hems`
option registers it in EdgeX as `device-rest_hems`, avoiding a collision with
an existing `device-rest` service.

## Install the proxy route

Run these commands on ECU B from this directory. The gateway includes
`/etc/nginx/container-apis/*.inc` in its public server blocks, and that directory
is backed by the existing `edgex_container-apis` Docker volume.

First check that the destination file is not already present. If it exists,
inspect and back it up before replacing it:

```sh
docker exec blel-reverse-proxy ls -l /etc/nginx/container-apis/hems-api.inc
```

If the file does not exist, install the supplied
[location snippet](config-rest/nginx/hems-api.inc), validate, and reload:

```sh
docker cp ./config-rest/nginx/hems-api.inc blel-reverse-proxy:/etc/nginx/container-apis/hems-api.inc
docker exec blel-reverse-proxy nginx -t &&
docker exec blel-reverse-proxy nginx -s reload
```

Do not reload if validation fails. The snippet persists in the gateway's
existing volume; it is not managed by this Compose project. Review existing
gateway authentication/access policies before exposing the route. It is a
read-only route and does not add authentication itself.

The proxy preserves query parameters and forwards:

```text
http://blel-reverse-proxy/hems/api/v1/flexibility-range?delta_t_seconds=900
  -> http://134.130.88.189:8000/api/v1/flexibility-range?delta_t_seconds=900
```

## Start and test

```sh
docker compose config --quiet
docker compose up -d device-hems
docker compose logs --tail=100 device-hems
```

No host port is needed for the device service: core-command reaches it over
the shared network at `edgex-device-hems:59986`.

Test the proxy route from a temporary container on that network:

```sh
docker run --rm --network edgex_edgex-network curlimages/curl:latest \
  -i --fail-with-body \
  'http://blel-reverse-proxy/hems/api/v1/flexibility-range?delta_t_seconds=900'
```

Expect HTTP 200 with the API's JSON body. Do not proceed on an HTTP-to-HTTPS
redirect, authentication error, or other non-200 response. Those require
adjusting the existing gateway policy; the REST driver uses HTTP for outgoing
commands, so do not simply change the device port to 443.

Read through EdgeX core-command on ECU B:

```sh
curl -i --fail-with-body \
  'http://127.0.0.1:59882/api/v3/device/name/Device-HEMS/flexibility-range?delta_t_seconds=900'
```

The EdgeX event contains an Object reading with the upstream JSON, not an
individual Float64 reading. The driver builds the outgoing path from the
device's `Path` and the resource name; the query parameter must be supplied
in the read request. No automatic polling is configured.

If core-command is not published on host port 59882, make the same request
from a container on `edgex_edgex-network` using `edgex-core-command:59882`.

To change the upstream address, edit the snippet and reinstall/reload it.
Editing the local snippet alone does not update the running gateway.
