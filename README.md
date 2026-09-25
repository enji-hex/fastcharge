
# xray_controller.py

> The most **stupid** tool to control XRAY configs on ur server

I was got crazy about 3x-UI - the entire dashboard built only for `JSON` controlling. So I decided to make stupidly simple tool that control xray for my daily tasks

Currently support:  VLESS + TCP + REALITY + Vision, but of course you can easily extend it,
so it's not a ready tool, just template.

# depploy 
- Generate certs `openssl req -x509 -newkey rsa:2048 -nodes -keyout key.pem -out cert.pem -days 365 -subj "/CN=localhost"`
- Install UV `curl -LsSf https://astral.sh/uv/install.sh | sh`
- `bash -c "$(curl -L https://github.com/XTLS/Xray-install/raw/main/install-release.sh)" @ install`
- sync UV


# Project layout

```sh
src/        # all .py files
local/      
    - # references for routing, server/client configs
    - # keys.json (keys for xray)
files/users.db
```


# Functions

- Generate keys, append clients
- Remove clients (or reset all)
- Create server config from template
- Create client config from template
- Create shared link for gui apps like nekoray,v2rayA etc.


## refs.
- [xray install](https://github.com/XTLS/Xray-install)
- [xray config example](/usr/local/etc/xray/config.json)

## TODO 
- create one-liner autosetup for serevr