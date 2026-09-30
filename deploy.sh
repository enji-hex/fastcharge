#!/bin/bash

server_port=443

while [ "$#" -gt 0 ]; do 
    case "$1" in
        -f=*)
            database="${1#*=}"   ;;
        -s=*|--server=*)
            server_ip="${1#*=}"  ;;
        -p=*|--port=*)
            server_port="${1#*=}";;
        -h|--help)
            echo "Usage: ./deploy.sh [-f=database.db]"
            echo "  -f=database.db  Push database file to server"
            echo "  -s|--server=server.ip"
            echo "  -p|--port=server.port, default 443"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"; exit 1;;
    esac
    shift
done

[ -z "$server_ip" ] && {
    echo "Server IP could NOT be empty"
    exit 1
}
server_str="root@$server_ip"
echo "Start ing deploy.sh for $server_str, XRAY port $server_port"
echo "DB: $database"


check_cmd="mkdir -p /root/fastcharge/{src,local,files} && test -f /etc/systemd/system/fastcharge.service"

if ! ssh  "$server_str" "$check_cmd"; then
    echo "Warning server uninitizlized, start .venv creation"
    scp  ./fastcharge/fastcharge.service "${server_str}:/etc/systemd/system/fastcharge.service"
    
    # .ENV
    sed -i -e "s/server_ip=.*/server_ip=$server_ip/g" \
        -e "s/server_port=.*/server_port=$server_port/g" \
        ./fastcharge/.env

cmd="
set -e

# export pathes for xray/uv

echo 'export PATH=\"\$HOME/.local/bin:\$HOME/.cargo/bin:\$PATH\"' >> ~/.bashrc
export PATH=\"\$HOME/.local/bin:\$HOME/.cargo/bin:\$PATH\"

export DEBIAN_FRONTEND=noninteractive
apt update -y
apt upgrade -y

command -v uv >/dev/null 2>&2 || {
    wget -qO- https://astral.sh/uv/install.sh | sh
}

command -v xray >/dev/null 2>&2 || {
    curl -L https://github.com/XTLS/Xray-install/raw/main/install-release.sh | bash -s -- install
}

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
    if [ -d "./fastcharge/.venv" ]; then
        rm -rf "./fastcharge/.venv"
    fi
    scp  -r  ./fastcharge/.  "${server_str}:/root/fastcharge/"
else 
    echo "Update local data only, don't touch /files"
    cmd="systemctl restart fastcharge"
    scp  -r  ./fastcharge/src/*    "${server_str}:/root/fastcharge/src/"
    scp  -r  ./fastcharge/local/*  "${server_str}:/root/fastcharge/local/"
    
fi

[ -f "$database" ] && {
    echo "Copy database to target server"
    scp  "$database" "${server_str}:/root/fastcharge/files/users.db"
}

ssh  "$server_str" "$cmd"