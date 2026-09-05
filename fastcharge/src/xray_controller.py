import asyncio
import json, uuid, os, base64, re, subprocess
from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives import serialization
from urllib.parse import urlencode, quote
import aiofiles
from pathlib import Path
from typing import Dict, List, Literal

from db import UserModel

PROJECT_ROOT = Path(__file__).resolve().parents[1]

SERVER_SRC_CONFIG_PATH = PROJECT_ROOT / "local"/ "config.server.json"
CLIENT_SRC_CONFIG_PATH = PROJECT_ROOT / "local"/ "config.client.json"

CLIENT_CONFIG_PATH = PROJECT_ROOT / "./config.client.json"

def fprint(*l):
    """Print tag W20 data"""
    print("\n".join(f'{f"§ {t}":<20}{d}' for t, d in l))


class XRAYController:
    def __init__(self,ip:str,server_config_path:str) -> None:
        self.ip = ip
        self._lock = asyncio.Lock()
        self.server_config_path = server_config_path

    async def load_config(self, conf_path) -> dict:
        async with aiofiles.open(conf_path, encoding="utf-8") as f:
            content = await f.read()
            return json.loads(content)

    async def save_config(self, conf_path, data):
        async with aiofiles.open(conf_path, "w", encoding="utf-8") as f:
            await f.write(json.dumps(data, indent=4))

    async def _restart_xray(self):
        proc = await asyncio.create_subprocess_exec("systemctl","restart","xray")
        await proc.wait()

    async def update_reality_key(
        self,
        tag,
        sni: str,
        server_port,
        transport: Literal["tcp", "grpc"],
        block_torrents:bool = False,
        keys=None,
        *,
        routing: Literal["socks+tun", "tproxy"],
    ):
        """Update keys in server,client configs"""

        if routing is None:
            raise Exception("No routing startegy provided")

        server_config = await self.load_config(SERVER_SRC_CONFIG_PATH)
        client_config = await self.load_config(CLIENT_SRC_CONFIG_PATH)

        if keys is None:
            keys = await self.load_config("local/keys.json")

        ok = False
        # INBOUNDS/ROUTING
        routing_conf = await self.load_config(f"./local/routing/{routing}.json")
        client_config["inbounds"] = routing_conf["inbounds"]
        client_config["routing"]  = routing_conf["routing"]

        for inbound in server_config.get("inbounds",[]):
            if inbound.get("tag") == tag:
                inbound["port"]  = server_port
                inbound["streamSettings"]["realitySettings"]["privateKey"] = keys[
                    "private"
                ]
                inbound["streamSettings"]["realitySettings"]["shortIds"] = [
                    keys["short_id"]
                ]
                inbound["streamSettings"]["realitySettings"]["serverNames"] = [sni]
                inbound["streamSettings"]["realitySettings"]["target"] = f"{sni}:443"
                inbound["streamSettings"]["network"] = transport
                inbound["settings"]["decryption"] = keys["decryption"]
        
        if block_torrents:
            server_config.get('routing',{}).get('rules',[]).append(
                {
                    "type": "field",
                    "protocol": ["bittorrent"],
                    "outboundTag": "block"
                }
            )

        for outbound in client_config.get("outbounds",[]):
            if outbound.get("tag") == tag:
                outbound["streamSettings"]["realitySettings"]["publicKey"] = keys[
                    "public"
                ]
                outbound["streamSettings"]["realitySettings"]["shortId"] = keys[
                    "short_id"
                ]
                outbound["streamSettings"]["realitySettings"]["serverName"] = sni
                outbound["streamSettings"]["network"] = transport
                outbound["settings"]["vnext"][0]["address"] = self.ip
                outbound["settings"]["vnext"][0]["port"] = int(server_port)
                ok = True
        for rule in client_config["routing"]["rules"]:
            if "ip" in rule and rule["ip"][0] == "server_ip":
                rule["ip"][0] = self.ip

        if ok:
            await self.save_config(self.server_config_path, server_config)
            await self.save_config(CLIENT_CONFIG_PATH, client_config)
        else:
            print(f"Err tag:{tag} not found")

    def generate_mlken(self):
        out = subprocess.check_output("./xray vlessenc".split(" "))
        out = str(out).split("Post-Quantum")[-1]
        decryption, encryption = re.findall(r"mlkem[\w|\d|.|-]*", out)
        return decryption.strip(), encryption.strip()

    def generate_reality_keys(self, save=False, mlken=True):
        """
        Automatic set keys in the config
        - save: save keys into keys.json
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
            decryption, encryption = self.generate_mlken()

        keys = {
            "private": private_b64,
            "public": public_b64,
            "short_id": short_id,
            "decryption": decryption if decryption is not None else "none",
            "encryption": encryption if encryption is not None else "none",
        }
        if save:
            json.dump(keys, open("local/keys.json", "w"), indent=4)
        return keys
        
    async def merge_vless_clients(self, users: List[UserModel],tag: str, keys=None):
        """
        Internal
        - inject client list into xray.server.config
        - export into server configs
        """
        async with self._lock:
            if keys is None:
                keys = await self.load_config("local/keys.json")

            server_config = await self.load_config(self.server_config_path)
            # client_config = await self.load_config(CLIENT_CONFIG_PATH)
            flow = "xtls-rprx-vision" if keys["encryption"] == "none" else None

            new_server_clients = [
                {
                    "id": u.config_id, 
                    "email": u.user_id,
                    "level": 8, 
                    **({"flow": flow} if flow else {})
                }
                for u in users
            ]
            # new_client_users = [
            #     {
            #         "id": u.config_id,
            #         "encryption": keys["encryption"], 
            #         "level": 8, 
            #         **({"flow": flow} if flow else {})
            #     }
            #     for u in users
            # ]

            for inbound in server_config.get("inbounds",[]):
                if inbound.get("tag") == tag:
                    inbound["settings"]["clients"] = new_server_clients

                # append to client config
            # for outbound in client_config.get("outbounds",[]):
            #     if outbound["tag"] == tag:
            #         outbound["settings"]["vnext"][0]["users"] = new_client_users
                
            await self.save_config(self.server_config_path,server_config)
            # await self.save_config(CLIENT_CONFIG_PATH,client_config)
            
            await self._restart_xray()
        

    async def export_vless(self, tag: str, id: str, keys=None):
        if keys is None:
            keys = await self.load_config("local/keys.json")

        server_config = await self.load_config(self.server_config_path)
        pubkey = (await self.load_config("local/keys.json"))["public"]

        for i in server_config.get("inbounds", []):
            if i.get("tag") == tag:
                for c in i.get("settings", {}).get("clients", []):
                    if c.get("id") == id:
                        port = i["port"]
                        reality = i["streamSettings"]["realitySettings"]

                        # Defensive list extraction
                        shortids = reality.get("shortIds", [""])
                        server_names = reality.get("serverNames", [""])

                        shortid = shortids[0] if shortids else ""
                        sni = server_names[0] if server_names else ""
                        transport = i["streamSettings"]["network"]

                        grpc_settings = i["streamSettings"].get(
                            "grpcSettings", {}
                        )
                        service_name = grpc_settings.get("serviceName", "")

                        params = {
                            "type": transport,
                            "security": "reality",
                            "pbk": pubkey,
                            "sid": shortid,
                            "sni": sni,
                            "fp": "chrome",
                            "serviceName": service_name,
                            "mode": "multi",
                            "encryption": keys["encryption"],
                        }
                        if keys["encryption"] == "none":
                            params["flow"] = "xtls-rprx-vision"

                        query = urlencode(params, safe=":")
                        return f"vless://{id}@{self.ip}:{port}?{query}#{quote(tag)}"

        return None
