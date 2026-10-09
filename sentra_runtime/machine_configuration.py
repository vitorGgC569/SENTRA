"""Persist explicit host configuration without grants or live session claims."""
import hashlib
import json


class MachineConfigurationStore:
    def __init__(self, store, owner):
        self.store, self.owner = store, owner
        db = self.store.connect("machine_configuration")
        try:
            with db:
                version = db.execute("PRAGMA user_version").fetchone()[0]
                if version > 1:
                    raise RuntimeError("newer machine configuration database")
                db.execute("CREATE TABLE IF NOT EXISTS configured_machines("
                    "owner TEXT NOT NULL,machine TEXT NOT NULL,config TEXT NOT NULL,sha256 TEXT NOT NULL,"
                    "PRIMARY KEY(owner,machine))")
                db.execute("PRAGMA user_version=1")
        finally:
            db.close()

    def put(self, machine_id, config):
        encoded = json.dumps(config,sort_keys=True,ensure_ascii=False,allow_nan=False,separators=(",",":"))
        if len(encoded.encode()) > 2_000_000:
            raise ValueError("machine configuration too large")
        digest = hashlib.sha256(encoded.encode()).hexdigest()
        db = self.store.connect("machine_configuration")
        try:
            with db:
                db.execute("INSERT INTO configured_machines VALUES(?,?,?,?) ON CONFLICT(owner,machine) "
                           "DO UPDATE SET config=excluded.config,sha256=excluded.sha256",
                           (self.owner,machine_id,encoded,digest))
        finally:
            db.close()

    def entries(self):
        db = self.store.connect("machine_configuration")
        try:
            rows = list(db.execute("SELECT * FROM configured_machines WHERE owner=? ORDER BY machine", (self.owner,)))
        finally:
            db.close()
        values = []
        for row in rows:
            if hashlib.sha256(row["config"].encode()).hexdigest() != row["sha256"]:
                raise RuntimeError("persisted machine configuration integrity failure")
            value = json.loads(row["config"])
            if not isinstance(value, dict):
                raise RuntimeError("invalid persisted machine configuration")
            values.append({"machine_id":row["machine"], "configuration":value})
        return values
