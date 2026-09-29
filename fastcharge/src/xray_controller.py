import asyncio
import json, uuid, os, base64, re, subprocess
from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives import serialization
from urllib.parse import urlencode, quote
import aiofiles
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple

from db import UserModel, KeysModel

PROJECT_ROOT = Path(__file__).resolve().parents[1]

SERVER_SRC_CONFIG_PATH = PROJECT_ROOT / "local" / "config.server.json"
CLIENT_SRC_CONFIG_PATH = PROJECT_ROOT / "local" / "config.signbox.json"
CLIENT_CONFIG_PATH = PROJECT_ROOT / "./config.client.json"


def fprint(*l):
    """Print tag W20 data"""
    print("\n".join(f'{f"§ {t}":<20}{d}' for t, d in l))


class XRAYController:
    def __init__(
        self,
        ip: str,
        port: int,
        sni: str,
        tag: str,
        server_config_path: str,
        keys: KeysModel,
    ) -> None:
        self.ip = ip
        self.port = port
        self.sni = sni
        self.tag = tag
        self._lock = asyncio.Lock()
        self.server_config_path = server_config_path
        self.client_config_path = CLIENT_CONFIG_PATH
        self.keys = keys

    async def load_config(self, conf_path) -> dict:
        async with aiofiles.open(conf_path, encoding="utf-8") as f:
            content = await f.read()
            return json.loads(content)

    async def save_config(self, conf_path, data):
        async with aiofiles.open(conf_path, "w", encoding="utf-8") as f:
            await f.write(json.dumps(data, indent=4))

    async def _restart_xray(self):
        proc = await asyncio.create_subprocess_exec("systemctl", "restart", "xray")
        await proc.wait()

    async def update_reality_key(
        self, block_torrents: bool = False, use_pi_hole: bool = False
    ):
        """
        Srever side function
        Update keys in server,client configs
        """

        server_config = await self.load_config(SERVER_SRC_CONFIG_PATH)

        if use_pi_hole:
            print("Use Pi-Hole True")
            server_config["dns"] = {"servers": ["127.0.0.1"]}

            server_config["outbounds"].append(
                {
                    "protocol": "dns",
                    "tag": "dns-out",
                    "settings": {
                        "rewriteNetwork": "udp",
                        "rewriteAddress": "127.0.0.1",
                        "rewritePort": 53,
                        "rules": [{"action": "direct"}],
                    },
                }
            )
            server_config["routing"]["rules"].append(
                {
                    "inboundTag": ["proxy"],
                    "port": 53,
                    "network": "tcp,udp",
                    "outboundTag": "dns-out",
                }
            )

        inbound = server_config.get("inbounds", [])[0]

        inbound["tag"] = self.tag
        inbound["port"] = self.port
        inbound["streamSettings"]["realitySettings"]["privateKey"] = self.keys.private
        inbound["streamSettings"]["realitySettings"]["shortIds"] = [self.keys.short_id]
        inbound["streamSettings"]["realitySettings"]["serverNames"] = [self.sni]
        inbound["streamSettings"]["realitySettings"]["target"] = f"{self.sni}:443"
        inbound["streamSettings"]["network"] = "tcp"
        inbound["settings"]["decryption"] = self.keys.decryption

        if block_torrents:
            server_config.get("routing", {}).get("rules", []).append(
                {"type": "field", "protocol": ["bittorrent"], "outboundTag": "block"}
            )

        # block ads
        server_config.get("routing", {}).get("rules", []).append(
            {
                "type": "field",
                "domain": ["geosite:category-ads-all"],
                "outboundTag": "block",
            }
        )

        await self.save_config(self.server_config_path, server_config)
        print(f"keys updated ")

    @staticmethod
    def generate_mlken():
        out = subprocess.check_output("./xray vlessenc".split(" "))
        out = str(out).split("Post-Quantum")[-1]
        decryption, encryption = re.findall(r"mlkem[\w|\d|.|-]*", out)
        return decryption.strip(), encryption.strip()

    @staticmethod
    def generate_reality_keys(mlken=True) -> KeysModel:
        """
        Automatic set keys in the config
        return new keys
        """

        private_key = x25519.X25519PrivateKey.generate()
        public_key = private_key.public_key()

        private_bytes = private_key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )

        if len(private_bytes) != 32:
            raise ValueError(f"Invalid private key length: {len(private_bytes)}")

        public_bytes = public_key.public_bytes(
            encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
        )

        private_b64 = (
            base64.urlsafe_b64encode(private_bytes).decode("utf-8").rstrip("=")
        )
        public_b64 = base64.urlsafe_b64encode(public_bytes).decode("utf-8").rstrip("=")

        # REALITY shortId (8 bytes hex is common)
        short_id = os.urandom(8).hex()
        decryption, encryption = None, None
        if mlken:
            decryption, encryption = XRAYController.generate_mlken()

        keys = KeysModel(
            private=private_b64,
            public=public_b64,
            short_id=short_id,
            decryption=decryption if decryption is not None else "none",
            encryption=encryption if encryption is not None else "none",
        )
        return keys

    async def merge_vless_clients(self, users: List[UserModel]):
        """
        Internal
        - inject client list into xray.server.config
        - restarts xray service
        """
        async with self._lock:

            server_config = await self.load_config(self.server_config_path)
            flow = "xtls-rprx-vision" if self.keys.encryption == "none" else None

            new_server_clients = [
                {
                    "id": u.config_id,
                    "email": u.user_id,
                    "level": 8,
                    **({"flow": flow} if flow else {}),
                }
                for u in users
            ]

            for inbound in server_config.get("inbounds", []):
                if inbound.get("tag") == self.tag:
                    inbound["settings"]["clients"] = new_server_clients

            await self.save_config(self.server_config_path, server_config)
            await self._restart_xray()

    async def export_vless(self, id: str):
        server_config = await self.load_config(self.server_config_path)

        for i in server_config.get("inbounds", []):
            if i.get("tag") == self.tag:
                for c in i.get("settings", {}).get("clients", []):
                    if c.get("id") == id:
                        port = i["port"]
                        stream = i.get("streamSettings", {})
                        reality = stream.get("realitySettings", {})

                        shortids = reality.get("shortIds", [""])
                        server_names = reality.get("serverNames", [""])

                        shortid = shortids[0] if shortids else ""
                        sni = server_names[0] if server_names else ""
                        transport = stream.get("network", "tcp")

                        params = {
                            "type": transport,
                            "security": "reality",
                            "pbk": self.keys.public,
                            "fp": "firefox",
                            # "encryption":keys.get("encryption","none")
                        }

                        if transport == "tcp":
                            params["flow"] = "xtls-rprx-vision"
                        elif transport == "grpc":
                            grpc_settings = stream.get("grpcSettings", {})
                            service_name = grpc_settings.get("serviceName", "")
                            if service_name:
                                params["serviceName"] = service_name
                                params["mode"] = "multi"

                        if shortid:
                            params["sid"] = shortid
                        if sni:
                            params["sni"] = sni

                        clean_params = {k: v for k, v in params.items() if v}

                        query = urlencode(clean_params, safe=":")
                        return (
                            f"vless://{id}@{self.ip}:{port}?{query}#{quote(self.tag)}"
                        )

        return None

    # purge both out
    async def export_client_outbound(
        self, config_id: str
    ) -> Optional[Tuple[str, dict]]:
        """Collect client config works even from other servers"""

        client_config = await self.load_config(CLIENT_SRC_CONFIG_PATH)
        out = None

        for outbound in client_config.get("outbounds", []):
            if outbound.get("tag") == "proxy":
                out = outbound
                out["flow"] = "xtls-rprx-vision"
                out["tag"] = self.tag
                out["tls"]["reality"]["public_key"] = self.keys.public
                out["tls"]["reality"]["short_id"] = self.keys.short_id
                out["tls"]["server_name"] = self.sni
                out["server"] = self.ip
                out["server_port"] = self.port
                out["uuid"] = config_id

        if out:
            return self.ip, out
        else:
            return None

    async def export_full_client_config(
        self,
        client_nodes: List[dict],
        ru_bypass=False,  # direct routing for RU domains
    ):
        """Export client config as json"""
        client_config = await self.load_config(CLIENT_SRC_CONFIG_PATH)

        # INBOUNDS/ROUTING
        routing_conf = await self.load_config(f"./local/routing/socks+tun.signbox.json")

        # Construct top-priority rules
        server_ips = []
        for el in client_nodes:
            client_config["outbounds"].append(el[1])
            server_ips.append(el[0])

        prepend_rules = [
            # 1. Route VPS server IPs directly to prevent loops
            {"ip_cidr": server_ips, "action": "route", "outbound": "direct-out"},
            # 2. Bypass local private network traffic
            {"ip_is_private": True, "action": "route", "outbound": "direct-out"},
        ]

        if ru_bypass:
            routing_conf["route"]["rule_set"] = [
                {
                    "tag": "geoip-ru",
                    "type": "remote",
                    "format": "binary",
                    "url": "https://raw.githubusercontent.com/SagerNet/sing-geoip/rule-set/geoip-ru.srs",
                    "download_detour": "direct-out",
                },
                {
                    "tag": "geosite-ru",
                    "type": "remote",
                    "format": "binary",
                    "url": "https://raw.githubusercontent.com/SagerNet/sing-geoip/rule-set/geoip-ru.srs",
                    "download_detour": "direct-out",
                },
            ]
            prepend_rules.append(
                {
                    "rule_set": ["geoip-ru", "geosite-ru"],
                    "action": "route",
                    "outbound": "direct-out",
                }
            )

        client_config["inbounds"] = routing_conf["inbounds"]
        client_config["route"] = routing_conf["route"]

        # dummy VPN config
        client_config.get("outbounds", []).pop(0)

        client_config["route"]["rules"] += prepend_rules
        client_config["route"]["rules"].append(
            {"action": "route", "outbound": "proxy"}  # final outbound
        )

        client_config["route"]["final"] = self.tag
        return client_config
