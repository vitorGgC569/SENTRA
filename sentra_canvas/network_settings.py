"""Protected workspace VPN whitelist and owned presence lifecycle."""
import ipaddress
import secrets
import os
from pathlib import Path
import json
import subprocess
import threading
import time

from sentra_core.conversations import _encode,_decode
from .peer_directory import PeerNodeIdentity,SignedPeerDirectory,PEER_PORT


class WorkspaceNetworkSettings:
    def __init__(self,store):
        self.store=store;self.lock=threading.RLock();self.directories={};self.errors={}
        self._interfaces=[];self._interfaces_at=0
        with store.tx():
            store.db.execute("CREATE TABLE IF NOT EXISTS canvas_network_settings("
                "principal TEXT NOT NULL,workspace TEXT NOT NULL,revision INTEGER NOT NULL,content TEXT NOT NULL,"
                "PRIMARY KEY(principal,workspace))")

    def _load(self,ws):
        self.store.workspace(ws)
        with self.store.lock:
            row=self.store.db.execute("SELECT revision,content FROM canvas_network_settings WHERE principal=? AND workspace=?",
                (self.store.principal,ws)).fetchone()
        if row:return {**_decode(row[1]),"revision":row[0]}
        return {"revision":0,"enabled":False,"adapter_kind":"hamachi","interface_address":"","allowed_ips":[],
            "port":PEER_PORT,"label":self.store.workspace(ws)["name"][:80],"mesh_key":None}

    def status(self,ws):
        with self.lock:
            config=self._load(ws);directory=self.directories.get(ws)
            public={k:v for k,v in config.items() if k!="mesh_key"}
            return {"configuration":public,"pairing_key_configured":bool(config.get("mesh_key")),
                "local_interfaces":self.local_interfaces(),
                "presence":directory.status() if directory else {"running":False,"peers":[],"presence_grants_execution":False},
                "error":self.errors.get(ws),"collaboration_transport_ready":False}

    def local_interfaces(self):
        if time.monotonic()-self._interfaces_at<30:return list(self._interfaces)
        self._interfaces_at=time.monotonic();self._interfaces=[]
        if os.name!="nt":return []
        executable=Path(os.environ.get("SystemRoot",r"C:\Windows"))/"System32"/"WindowsPowerShell"/"v1.0"/"powershell.exe"
        script="""[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding
        $sentraNetworkRows = @(Get-NetAdapter -ErrorAction SilentlyContinue | Where-Object {
          $_.Name -match 'Hamachi|Radmin' -or $_.InterfaceDescription -match 'Hamachi|Radmin'
        } | ForEach-Object {
          $sentraNetworkAdapter = $_
          Get-NetIPAddress -InterfaceIndex $sentraNetworkAdapter.ifIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue |
            Select-Object @{Name='adapter_name';Expression={$sentraNetworkAdapter.Name}},
              @{Name='adapter_description';Expression={$sentraNetworkAdapter.InterfaceDescription}},IPAddress
        })
        ConvertTo-Json -InputObject $sentraNetworkRows -Compress"""
        try:
            result=subprocess.run([str(executable),"-NoProfile","-NonInteractive","-Command",script],
                stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=5,
                creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
            if result.returncode or len(result.stdout)>65536:return []
            rows=json.loads(result.stdout.decode("utf-8-sig"))
            if not isinstance(rows,list):return []
            for row in rows[:16]:
                address=ipaddress.ip_address(row["IPAddress"])
                if address.version==4 and not address.is_unspecified:
                    name=str(row.get("adapter_name",""))[:120];description=str(row.get("adapter_description",""))[:200]
                    self._interfaces.append({"address":str(address),"name":name,"description":description,
                        "adapter_kind":"radmin" if "radmin" in (name+description).lower() else "hamachi"})
        except (OSError,ValueError,TypeError,KeyError,subprocess.TimeoutExpired):pass
        return list(self._interfaces)

    def pairing_code(self,ws):
        """Owner-only UI action; agent status never exposes pairing material."""
        with self.lock:
            config=self._load(ws)
            if not config.get("mesh_key"):raise ValueError("save the network configuration before pairing")
            return {"mesh_key":config["mesh_key"],"port":config["port"],"purpose":"selected-workspace-peer-pairing"}

    def restore(self):
        with self.store.lock:
            rows=list(self.store.db.execute("SELECT workspace,content FROM canvas_network_settings WHERE principal=?",(self.store.principal,)))
        with self.lock:
            for row in rows:
                config=_decode(row[1]);ws=row[0]
                if config.get("enabled") is not True or ws in self.directories:continue
                try:
                    candidate=SignedPeerDirectory(identity=PeerNodeIdentity(self.store,ws),mesh_key=config["mesh_key"],
                        label=config["label"],address=config["interface_address"],port=config["port"],target_addresses=config["allowed_ips"])
                    candidate.start();self.directories[ws]=candidate
                except (OSError,ValueError,RuntimeError) as exc:
                    self.errors[ws]={"type":type(exc).__name__,"status":"configured_network_not_restored"}

    def configure(self,ws,configuration,*,agent=False):
        if not isinstance(configuration,dict):raise ValueError("network settings mapping required")
        allowed={"enabled","adapter_kind","interface_address","allowed_ips","port","label","expected_revision"}
        if not agent:allowed.add("mesh_key")
        if set(configuration)-allowed:raise ValueError("unsupported network configuration field")
        with self.lock:
            previous=self._load(ws);expected=configuration.get("expected_revision")
            if type(expected) is not int or expected!=previous["revision"]:raise ValueError("network revision changed; reload required")
            config={**previous,**{k:v for k,v in configuration.items() if k!="expected_revision"}}
            if type(config["enabled"]) is not bool or config["adapter_kind"] not in {"hamachi","radmin","manual"}:
                raise ValueError("explicit VPN adapter kind/enable required")
            if type(config["port"]) is not int or not 1<=config["port"]<=65535:raise ValueError("valid common peer port required")
            if not isinstance(config["label"],str) or not 1<=len(config["label"])<=80:raise ValueError("bounded peer label required")
            if not isinstance(config["allowed_ips"],list) or len(config["allowed_ips"])>128:raise ValueError("bounded peer IP whitelist required")
            def ipv4(value):
                if not isinstance(value,str):raise ValueError("peer IP must be text")
                parsed=ipaddress.ip_address(value)
                if parsed.version!=4 or parsed.is_unspecified or parsed.is_multicast:raise ValueError("explicit unicast IPv4 required")
                return str(parsed)
            config["allowed_ips"]=list(dict.fromkeys(ipv4(value) for value in config["allowed_ips"]))
            if not isinstance(config["interface_address"],str):raise ValueError("local interface IP must be text")
            config["interface_address"]=ipv4(config["interface_address"]) if config["interface_address"] else ""
            if config["enabled"] and (not config["interface_address"] or not config["allowed_ips"]):
                raise ValueError("local VPN IP and nonempty whitelist required to enable discovery")
            if config.get("mesh_key") is None:config["mesh_key"]=secrets.token_urlsafe(32)
            if not isinstance(config["mesh_key"],str) or not 32<=len(config["mesh_key"].encode())<=256:
                raise ValueError("bounded mesh pairing key required")
            candidate=None
            if config["enabled"]:
                candidate=SignedPeerDirectory(identity=PeerNodeIdentity(self.store,ws),mesh_key=config["mesh_key"],
                    label=config["label"],address=config["interface_address"],port=config["port"],target_addresses=config["allowed_ips"])
            with self.store.tx():
                row=self.store.db.execute("SELECT revision FROM canvas_network_settings WHERE principal=? AND workspace=?",
                    (self.store.principal,ws)).fetchone()
                current=row[0] if row else 0
                if current!=expected:raise ValueError("network revision changed; reload required")
                config["revision"]=current+1
                self.store.db.execute("INSERT INTO canvas_network_settings VALUES(?,?,?,?) "
                    "ON CONFLICT(principal,workspace) DO UPDATE SET revision=excluded.revision,content=excluded.content",
                    (self.store.principal,ws,config["revision"],_encode({k:v for k,v in config.items() if k!="revision"})))
            old=self.directories.pop(ws,None)
            if old:old.close()
            self.errors.pop(ws,None)
            if candidate:
                try:candidate.start();self.directories[ws]=candidate
                except OSError as exc:self.errors[ws]={"type":type(exc).__name__,"status":"configured_interface_or_port_unavailable"}
            return self.status(ws)

    def close(self):
        with self.lock:
            for directory in self.directories.values():directory.close()
            self.directories.clear()
