#!/bin/bash

server_ip="45.59.119.189"
server_str="root@$server_ip"
server_port=443

ssh $server_str "mkdir -p /root/fastcharge/{src,local} ; test -f /etc/systemd/system/fastcharge.service"

if [ "$service_not_exists" ]; then
    echo "Warning server uninitizlized, start .venv creation"
    scp  ./fastcharge/fastcharge.service "${server_str}:/etc/systemd/system/fastcharge.service"
    
    # .ENV
    sed -e "s/server_ip=.*/server_ip=$server_ip/g" \
        -e "s/server_port=.*/server_port=$server_port/g" ./fastcharge/.env > ./.env

cmd="
set -e

cd /root/fastcharge
uv sync

openssl req -x509 -newkey rsa:2048 \
    -keyout key.pem \
    -out cert.pem \
    -sha256 \
    -days 3650 \
    -nodes \
    -subj '/CN=localhost'

systemctl daemon-reload
systemctl enable fastcharge
systemctl start fastcharge
"
    scp -r  ./fastcharge/*  "${server_str}:/root/fastcharge/"
else 
    echo "Update local data only, don't touch /files"
    cmd="systemctl restart fastcharge"
    scp -r  ./fastcharge/src/*    "${server_str}:/root/fastcharge/src/"
    scp -r  ./fastcharge/local/*  "${server_str}:/root/fastcharge/local/"
    
fi

ssh $server_str "$cmd"
