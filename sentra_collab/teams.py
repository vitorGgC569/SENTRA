"""Teams, local accounts, and presentation sync for one installation.

Membership records name a project, space, or document. They are not grants.
Every read and write reconsults the installation Control Plane. Provider
credentials are not accepted and are not stored. This module does not open
a second Control Plane and does not serve SQLite.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

from sentra_mcp.services.control_plane import ControlPlaneService

from .authority import validate_presentation
from .scope import parse_scope, same_scope

SECRET_MARKERS = ("begin private key", "begin openssh private key", "begin rsa private key")


class TeamDenied(PermissionError):
    pass


class SyncConflict(RuntimeError):
    pass


def _clean_text(value, label, limit):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise TeamDenied("invalid " + label)
    if any(ord(ch) < 32 for ch in value):
        raise TeamDenied("invalid " + label)
    lowered = value.lower()
    if any(marker in lowered for marker in SECRET_MARKERS) or ".sqlite" in lowered:
        raise TeamDenied("credentials stay outside the team record")
    return value.strip()


class TeamDirectory:
    """Scope labels plus live Control Plane decisions for one owner."""

    def __init__(self, control, *, owner, actor_id, directory, actor_type="user"):
        if not isinstance(control, ControlPlaneService):
            raise TypeError("team records require the installation Control Plane")
        if not owner or not actor_id:
            raise ValueError("owner and actor required")
        if actor_type not in {"user", "agent"}:
            raise TeamDenied("invalid actor type")
        self.control = control
        self.owner = owner
        self.actor_id = actor_id
        self.actor_type = actor_type
        self._path = Path(directory) / "teams.json"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        if not self._path.exists():
            self._dump({"accounts": {}, "teams": {}, "projections": {}})

    def register_account(self, payload):
        if not isinstance(payload, dict) or set(payload) != {
            "account_id", "principal_id", "display_name", "project_id",
        }:
            raise TeamDenied("account record accepts only local identity fields")
        account_id = _clean_text(payload["account_id"], "account id", 80)
        principal_id = _clean_text(payload["principal_id"], "principal id", 80)
        display_name = _clean_text(payload["display_name"], "display name", 80)
        project_id = _clean_text(payload["project_id"], "project id", 80)
        decision = self._grant(self.actor_id, self.actor_type, "collab.account.register", project_id)
        record = {
            "account_id": account_id,
            "principal_id": principal_id,
            "display_name": display_name,
            "project_id": project_id,
            "credentials_stored": False,
            "grant_id": decision["grant_id"],
        }
        with self._lock:
            data = self._load()
            current = data["accounts"].get(account_id)
            if current is not None and current["principal_id"] != principal_id:
                raise TeamDenied("account is already bound to another principal")
            if len(data["accounts"]) >= 500 and current is None:
                raise TeamDenied("account quota reached")
            data["accounts"][account_id] = record
            self._dump(data)
        return dict(record)

    def create_team(self, payload):
        if not isinstance(payload, dict) or set(payload) != {"team_id", "project_id", "name"}:
            raise TeamDenied("team record accepts only id, project and name")
        team_id = _clean_text(payload["team_id"], "team id", 80)
        project_id = _clean_text(payload["project_id"], "project id", 80)
        name = _clean_text(payload["name"], "team name", 80)
        decision = self._grant(self.actor_id, self.actor_type, "collab.team.manage", project_id)
        record = {
            "team_id": team_id,
            "project_id": project_id,
            "name": name,
            "members": [],
            "grant_id": decision["grant_id"],
        }
        with self._lock:
            data = self._load()
            if team_id in data["teams"]:
                raise TeamDenied("team already exists")
            if len(data["teams"]) >= 200:
                raise TeamDenied("team quota reached")
            data["teams"][team_id] = record
            self._dump(data)
        return self._public_team(record)

    def add_member(self, payload):
        if not isinstance(payload, dict) or set(payload) != {"team_id", "account_id", "scope"}:
            raise TeamDenied("membership accepts only team, account and scope")
        scope = parse_scope(payload["scope"])
        team_id = _clean_text(payload["team_id"], "team id", 80)
        account_id = _clean_text(payload["account_id"], "account id", 80)
        decision = self._grant(self.actor_id, self.actor_type, "collab.team.manage", scope["project_id"])
        with self._lock:
            data = self._load()
            team = data["teams"].get(team_id)
            account = data["accounts"].get(account_id)
            if team is None or account is None:
                raise TeamDenied("team or account is unknown")
            if team["project_id"] != scope["project_id"] or account["project_id"] != scope["project_id"]:
                raise TeamDenied("membership cannot leave its project")
            members = team["members"]
            if any(item["account_id"] == account_id and same_scope(item["scope"], scope) for item in members):
                raise TeamDenied("membership already exists")
            if len(members) >= 200:
                raise TeamDenied("membership quota reached")
            members.append({
                "account_id": account_id,
                "principal_id": account["principal_id"],
                "scope": scope,
                "grant_id": decision["grant_id"],
            })
            self._dump(data)
        return {"team_id": team_id, "account_id": account_id, "scope": scope, "credentials_stored": False}

    def assert_member_scope(self, principal_id, scope):
        """Refuse when this principal has no exact membership. This is not a grant."""
        scope = parse_scope(scope)
        with self._lock:
            data = self._load()
        for team in data["teams"].values():
            if team["project_id"] != scope["project_id"]:
                continue
            for member in team["members"]:
                if member["principal_id"] == principal_id and same_scope(member["scope"], scope):
                    return {"team_id": team["team_id"], "scope": scope}
        raise TeamDenied("scope is outside the team membership")

    def sync(self, payload):
        if not isinstance(payload, dict) or set(payload) != {
            "team_id", "account_id", "principal_id", "scope", "presentation", "expected_revision",
        }:
            raise TeamDenied("sync accepts only team, account, principal, scope and presentation")
        return self._sync(payload, write=True)

    def read_sync(self, payload):
        if not isinstance(payload, dict) or set(payload) != {"team_id", "account_id", "principal_id", "scope"}:
            raise TeamDenied("sync read accepts only team, account, principal and scope")
        return self._sync(payload, write=False)

    def export_account(self, account_id):
        """Read one local account. The Control Plane is consulted again."""
        account_id = _clean_text(account_id, "account id", 80)
        with self._lock:
            record = self._load()["accounts"].get(account_id)
        if record is None:
            raise TeamDenied("account is unknown")
        decision = self._grant(
            self.actor_id, self.actor_type, "collab.account.register", record["project_id"],
        )
        return {
            "account_id": record["account_id"],
            "principal_id": record["principal_id"],
            "display_name": record["display_name"],
            "project_id": record["project_id"],
            "credentials_stored": False,
            "grant_id": decision["grant_id"],
        }

    def _sync(self, payload, *, write):
        scope = parse_scope(payload["scope"])
        principal_id = _clean_text(payload["principal_id"], "principal id", 80)
        team_id = _clean_text(payload["team_id"], "team id", 80)
        account_id = _clean_text(payload["account_id"], "account id", 80)
        capability = "collab.sync.write" if write else "collab.sync.read"
        if write:
            presentation = validate_presentation(payload["presentation"])
            expected = payload["expected_revision"]
            if type(expected) is not int or expected < 0:
                raise TeamDenied("invalid sync revision")
        decision = self._grant(principal_id, "user", capability, scope["project_id"])
        key = json.dumps(scope, sort_keys=True, separators=(",", ":"))
        with self._lock:
            data = self._load()
            team = data["teams"].get(team_id)
            account = data["accounts"].get(account_id)
            if team is None or account is None or account["principal_id"] != principal_id:
                raise TeamDenied("sync principal is not a member of this team")
            if not any(
                item["account_id"] == account_id and same_scope(item["scope"], scope)
                for item in team["members"]
            ):
                raise TeamDenied("scope is outside the team membership")
            current = data["projections"].get(team_id, {}).get(key)
            if not write:
                if current is None:
                    return {
                        "revision": 0,
                        "presentation": {"layout": {}, "nodes": {}, "notes": {}},
                        "executed": False,
                        "credentials_stored": False,
                        "grant_id": decision["grant_id"],
                    }
                return {
                    "revision": current["revision"],
                    "presentation": current["presentation"],
                    "executed": False,
                    "credentials_stored": False,
                    "grant_id": decision["grant_id"],
                }
            revision = current["revision"] if current else 0
            if revision != expected:
                raise SyncConflict("team projection changed; reload required")
            stored = {
                "revision": revision + 1,
                "presentation": presentation,
                "principal_id": principal_id,
                "grant_id": decision["grant_id"],
                "executed": False,
                "credentials_stored": False,
                "scope": scope,
            }
            data["projections"].setdefault(team_id, {})[key] = stored
            if len(data["projections"][team_id]) > 128:
                raise TeamDenied("projection quota reached")
            self._dump(data)
        return {
            "revision": stored["revision"],
            "scope": scope,
            "executed": False,
            "credentials_stored": False,
            "grant_id": decision["grant_id"],
            "control_plane": "installation",
        }

    def _grant(self, principal_id, principal_type, capability, project_id):
        decision = self.control.authorization.authorize(
            self.owner,
            principal_type=principal_type,
            principal_id=principal_id,
            capability=capability,
            scope_type="project",
            scope_id=project_id,
            context={"actual_cost": 0.0},
            local_owner=False,
        )
        if decision.get("allowed") is not True or not decision.get("grant_id"):
            raise TeamDenied("control plane grant missing")
        return decision

    def _load(self):
        return json.loads(self._path.read_text(encoding="utf-8"))

    def _dump(self, data):
        raw = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        if b"sqlite" in raw.lower() or b"BEGIN PRIVATE" in raw:
            raise TeamDenied("team record would store local credentials or a database")
        temp = self._path.with_suffix(".json.tmp")
        temp.write_bytes(raw)
        temp.replace(self._path)

    @staticmethod
    def _public_team(record):
        return {
            "team_id": record["team_id"],
            "project_id": record["project_id"],
            "name": record["name"],
            "member_count": len(record["members"]),
            "credentials_stored": False,
        }
