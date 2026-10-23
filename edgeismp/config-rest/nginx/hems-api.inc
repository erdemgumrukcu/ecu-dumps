location = /hems/api/v1/flexibility-range {
    limit_except GET {
        deny all;
    }

    proxy_pass http://134.130.88.189:8000/api/v1/flexibility-range;
    proxy_http_version 1.1;
    proxy_set_header Host 134.130.88.189:8000;
    proxy_set_header Connection "";
    proxy_connect_timeout 5s;
    proxy_read_timeout 60s;
}
