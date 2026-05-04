FROM golang:1.25-alpine AS builder

RUN apk add --no-cache git build-base ca-certificates

WORKDIR /src
RUN git clone --depth 1 --branch v4.0.1 https://github.com/edgexfoundry/device-rest-go.git .

# Patch device-rest-go to honor HTTPS scheme when building outbound URIs.
RUN sed -i 's|\tpath string|\tpath   string\n\tscheme string|' driver/restdriver.go && \
    sed -i 's|"http://%s:%s/%s/%s?%s", protocolParams.host, protocolParams.port, protocolParams.path, req.DeviceResourceName, reqParam|"%s://%s:%s/%s/%s?%s", protocolParams.scheme, protocolParams.host, protocolParams.port, protocolParams.path, req.DeviceResourceName, reqParam|g' driver/restdriver.go && \
    sed -i 's|"http://%s:%s/%s?%s", protocolParams.host, protocolParams.port, req.DeviceResourceName, reqParam|"%s://%s:%s/%s?%s", protocolParams.scheme, protocolParams.host, protocolParams.port, req.DeviceResourceName, reqParam|g' driver/restdriver.go && \
    sed -i 's|return restDeviceProtocolParams, nil|restDeviceProtocolParams.scheme = "http"\n\tscheme := strings.ToLower(cast.ToString(protocolParams["Scheme"]))\n\tif scheme != "" {\n\t\trestDeviceProtocolParams.scheme = scheme\n\t} else if restDeviceProtocolParams.port == "443" {\n\t\trestDeviceProtocolParams.scheme = "https"\n\t}\n\n\treturn restDeviceProtocolParams, nil|' driver/restdriver.go

RUN CGO_ENABLED=0 go build -o /out/device-rest ./cmd

FROM alpine:3.20

COPY --from=builder /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/ca-certificates.crt
COPY --from=builder /usr/share/zoneinfo /usr/share/zoneinfo
ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt

COPY --from=builder /out/device-rest /device-rest
COPY --from=builder /src/cmd/res /res

ENTRYPOINT ["/device-rest"]
