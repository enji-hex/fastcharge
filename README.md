# FastCharge

> _A minimal, lightweight control plane for Xray process lifecycles and configuration management._

FastCharge was built to replace heavy web dashboards (like 3x-UI) with a simple, zero-bloat orchestration pipeline designed strictly for process and JSON configuration control.

## Features
- **Automated Key Generation:** Generates node-specific encryption keys on provisioning.
- **Client Management:** Provision, revoke, and track clients by subscription expiration time.
- **Template-Based Configs:** Generates modular client and server configurations separating core rules and routing tables.
- **Dual Export Formats:** Exports client configurations as direct `vless://` URI links or fully compliant Xray JSON objects.


> Warning
> Used XARY version: [v26.3.27](https://github.com/XTLS/Xray-core/releases/tag/), newer versions coud broken setup

## Deployment

Node deployements are managed by [`./deploy.sh`](./deploy.sh) script.

**Initial setup** \
On the first run, the script installs `uv`, `xray`, generates self-signed TLS certificates, and registers the `fastcharge.service` systemd unit file.

**Updates** \
Subsequent script executions sync updated source files from `./src` and active Xray routing templates from `./local`. Pass `-f` to force a complete database reset on the target node.

```
# Deploy or update remote server node
./deploy.sh -s=127.0.0.1 -p=443
```

## Project layout
```sh
fastcharge/
    src/    # Core FastAPI control plane & database models
    local/  # Xray JSON templates and routing rules
    files/  # Server-side SQLite database
openwrt-service/ # [!testing] OpenWrt CGI/shell service for router integration
```

## References
- [xray install](https://github.com/XTLS/Xray-install)

## License

This project is licensed under the MIT License. 

Feel free to use, modify, and update this code as you wish. \
THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND.