$server_ip="83.147.245.51"
$server_str="root@$server_ip"
$server_port = 443

ssh $server_str "
    mkdir -p /root/fastcharge/{src,local}
    test -f /etc/systemd/system/fastcharge.service
"

$service_not_exists  = ($LASTEXITCODE -ne 0)


if ($service_not_exists) {
    Write-Host  -ForegroundColor Cyan "Warning server uninitizlized, start .venv creation"
    # systemd service
    scp ./fastcharge/fastcharge.service "${server_str}:/etc/systemd/system/fastcharge.service"
    
    # .ENV
    $envData = (Get-Content .\fastcharge\.env -Raw) -replace "`r", ""
    $envData = $envData -replace '(?m)^server_ip=.*$', "server_ip=$server_ip"
    $envData = $envData -replace '(?m)^server_port=.*$', "server_port=$server_port"
    $envData | ssh $server_str "cat > /root/fastcharge/.env"

    # setup command
    $cmd = "
    set -e
    cd /root/fastcharge
    uv sync

    openssl req -x509 -newkey rsa:2048 \
        -keyout key.pem \
        -out    cert.pem \
        -sha256 \
        -days 3650 \
        -nodes \
        -subj '/CN=fastcharge'

    systemctl daemon-reload
    systemctl enable fastcharge
    systemctl start fastcharge
    "

    scp -r  .\fastcharge\*  "${server_str}:/root/fastcharge/"
} 
else {
    # Update local data only, don't touch /files
    $cmd = "systemctl restart fastcharge"
    scp -r  .\fastcharge\src\*    "${server_str}:/root/fastcharge/src/"
    scp -r  .\fastcharge\local\*  "${server_str}:/root/fastcharge/local/"
}

ssh $server_str $cmd
