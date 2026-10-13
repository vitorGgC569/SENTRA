"""Real Langfuse projections linked to central receipts, gates and costs.

Remote scores remain advisory. Dataset versions include environment/provider/
model/tools/verifier; stored inputs, prompts, output and corrections are OS
protected. Exporting content is a separate explicit configuration choice.
"""
import hashlib
import re
from datetime import datetime, timezone

from .protected_state import digest, canonical, StateConflict
from .langfuse_eval import _score


class ProtectedEvalRuntime:
    def __init__(self, state, references, client, *, export_content=False):
        self.state, self.references = state.scoped("selo.eval"), references
        self.client, self.export_content = client, export_content
        self.prefix = "selo/" + digest([state.owner, state.workspace_id])[:32] + "/"

    @staticmethod
    def name(value):
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", value):
            raise ValueError("invalid scoped evaluation name")
        return value

    @staticmethod
    def version(value):
        if type(value) is not int or not 1 <= value <= 1_000_000:
            raise ValueError("explicit prompt/dataset version required")
        return value

    def _get(self, key):
        row = self.state.get(key)
        if row is None: raise FileNotFoundError("scoped evaluation object unavailable")
        return row["value"]

    def _dataset(self, name, version):
        return self._get("dataset:" + self.name(name) + ":" + str(self.version(version)))

    def _item(self, dataset_name, version, item_id):
        return self._get("item:" + self.name(dataset_name) + ":" + str(self.version(version)) + ":" + self.name(item_id))

    def _content(self):
        if self.export_content is not True:
            raise PermissionError("explicit scoped prompt/dataset content export is disabled")

    def dispatch(self, action, args, *, context, request_key):
        if action == "prompt_create":
            self._content()
            allowed = {"name", "prompt", "labels", "config", "commit_message", "type"}
            if set(args) - allowed or len(canonical(args).encode()) > 256000:
                raise ValueError("invalid prompt create fields/bound")
            name = self.name(args["name"])
            body = {"name": self.prefix + name, "prompt": args["prompt"],
                "type": args.get("type", "text" if isinstance(args["prompt"], str) else "chat"),
                "labels": args.get("labels", []), "config": args.get("config", {}),
                "commitMessage": args.get("commit_message", "")}
            if not isinstance(body["config"], dict) or "sentra_request_key" in body["config"]:
                raise ValueError("prompt config must not override recovery binding")
            body["config"] = {**body["config"], "sentra_request_key": request_key}
            response = self.client.dispatch("prompt_create", body)
            version = self.version(response["version"])
            if response["name"] != body["name"] or response.get("prompt") != body["prompt"]:
                raise StateConflict("Langfuse prompt binding mismatch")
            self.state.put("prompt:" + name + ":" + str(version), {"request": body, "remote": response,
                "prompt_sha256": digest({"prompt": body["prompt"], "config": body["config"]})})
            return {"name": name, "version": version, "prompt_sha256": digest(body), "remote_confirmed": True}
        if action in {"prompt_get", "prompt_labels"}:
            name, version = self.name(args["name"]), self.version(args["version"])
            row = self.state.get("prompt:" + name + ":" + str(version))
            if row is None: raise FileNotFoundError("scoped prompt version unavailable")
            body = {"name": self.prefix + name, "version": version}
            if action == "prompt_labels": body["labels"] = args["labels"]
            response = self.client.dispatch(action, body)
            if response.get("name") != body["name"] or response.get("version") != version:
                raise StateConflict("remote prompt scope/version mismatch")
            value = row["value"]; value["remote"] = response
            self.state.put("prompt:" + name + ":" + str(version), value, expected_revision=row["revision"])
            return response
        if action == "dataset_create":
            self._content()
            name, version = self.name(args["name"]), self.version(args["version"])
            key = "dataset:" + name + ":" + str(version)
            if self.state.get(key): raise StateConflict("dataset version immutable; use new version")
            metadata = {k: args[k] for k in ("environment", "provider", "model", "tools", "verifier")}
            if (not isinstance(metadata["environment"], dict) or not isinstance(metadata["verifier"], dict)
                    or not metadata["verifier"] or not isinstance(metadata["tools"], list)):
                raise ValueError("dataset environment/tools/independent verifier required")
            remote_name = self.prefix + name + "@" + str(version)
            response = self.client.dispatch(action, {"name": remote_name,
                "metadata": {**metadata, "sentra_dataset_version": version, "manifest_sha256": digest(metadata)}})
            if response.get("name") != remote_name: raise StateConflict("dataset scope mismatch")
            value = {"name": name, "version": version, "remote_name": remote_name,
                     "remote": response, "manifest": metadata, "manifest_sha256": digest(metadata),
                     "created_at": datetime.now(timezone.utc).isoformat()}
            self.state.put(key, value)
            return {"name": name, "version": version, "manifest_sha256": value["manifest_sha256"], "remote_confirmed": True}
        if action == "dataset_get":
            dataset = self._dataset(args["name"], args["version"])
            return self.client.dispatch(action, {"name": dataset["remote_name"]})
        if action in {"item_put", "item_get"}:
            dataset = self._dataset(args["dataset_name"], args["dataset_version"])
            item_id = self.name(args["item_id"])
            key = "item:" + dataset["name"] + ":" + str(dataset["version"]) + ":" + item_id
            if action == "item_get":
                item = self._get(key)
                return self.client.dispatch(action, {"id": item["remote_id"]})
            self._content()
            if self.state.get(key): raise StateConflict("dataset item immutable within version")
            if len(canonical([args["input"], args["expected_output"]]).encode()) > 128000:
                raise ValueError("dataset item exceeds bound")
            remote_id = digest([self.prefix, key])
            body = {"datasetName": dataset["remote_name"], "id": remote_id,
                    "input": args["input"], "expectedOutput": args["expected_output"],
                    "metadata": {"sentra_manifest_sha256": dataset["manifest_sha256"]}}
            response = self.client.dispatch(action, body)
            if response.get("id") != remote_id: raise StateConflict("dataset item binding mismatch")
            self.state.put(key, {"remote_id": remote_id, "input": args["input"],
                "expected_output": args["expected_output"], "expected_sha256": digest(args["expected_output"]),
                "input_sha256": digest(args["input"]), "remote": response})
            return {"item_id": item_id, "remote_id": remote_id, "remote_confirmed": True}
        if action == "eval_run":
            dataset = self._dataset(args["dataset_name"], args["dataset_version"])
            prompt = self._get("prompt:" + self.name(args["prompt_name"]) + ":" + str(self.version(args["prompt_version"])))
            run_id = "eval-" + digest([self.prefix, request_key])[:40]
            self.state.put("run:" + run_id, {"run_id": run_id, "dataset": dataset, "prompt": prompt,
                "prompt_name": args["prompt_name"], "prompt_version": args["prompt_version"],
                "items": [], "scores_advisory": True})
            return {"run_id": run_id, "manifest_sha256": dataset["manifest_sha256"],
                    "remote_run_created": False, "remote_run_created_on_first_item": True}
        if action == "eval_item":
            self._content()
            run = self._get("run:" + self.name(args["run_id"]))
            item = self._item(run["dataset"]["name"], run["dataset"]["version"], args["item_id"])
            snapshot = self.references.snapshot(args["operation_id"], terminal=True)
            artifact = self.references.control.durable.artifact_info(args["output_artifact_id"], self.state.owner)
            if (artifact["operation_id"], artifact["run_id"]) != (args["operation_id"], snapshot["origin"]["run_id"]):
                raise PermissionError("evaluation output outside central origin")
            raw = self.references.artifact(args["operation_id"], args["output_artifact_id"], max_bytes=65536)
            import json
            output = json.loads(raw)
            trace_id = digest([self.state.owner, self.state.workspace_id, args["operation_id"]])[:32]
            gate = snapshot["quality_gate"]
            manifest = run["dataset"]["manifest"]
            if (not isinstance(gate, dict) or gate.get("authority") != "quality_gate"
                    or gate.get("deterministic") is not True or type(gate.get("passed")) is not bool):
                raise PermissionError("independent central QualityGate evidence absent")
            if not any(ref in gate.get("evidence", []) for ref in (args["operation_id"], args["output_artifact_id"])):
                raise PermissionError("QualityGate is not linked to this output/operation")
            for cost in snapshot["costs"]:
                if cost["provider"] != manifest["provider"] or cost["model"] != manifest["model"]:
                    raise PermissionError("observed provider/model differs from dataset manifest")
            if not snapshot["costs"]:
                raise PermissionError("central provider/model/cost evidence unavailable")
            from sentra_runtime.otlp_sink import SafeTelemetryEvent, to_otlp
            document = to_otlp(SafeTelemetryEvent("sentra.operation", snapshot["state"], args["operation_id"]))
            span = document["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
            span["traceId"] = trace_id
            span["attributes"].extend([
                {"key": "langfuse.observation.input", "value": {"stringValue": canonical(item["input"])}},
                {"key": "langfuse.observation.output", "value": {"stringValue": canonical(output)}},
                {"key": "sentra.dataset_manifest_sha256", "value": {"stringValue": run["dataset"]["manifest_sha256"]}},
                {"key": "sentra.quality_gate_sha256", "value": {"stringValue": digest(gate)}},
                {"key": "sentra.cost_event_ids_sha256", "value": {"stringValue": digest([c["cost_event_id"] for c in snapshot["costs"]])}}])
            self.client.dispatch("traces", document)
            remote = self.client.dispatch("run_item", {"runName": run["run_id"], "datasetItemId": item["remote_id"],
                "traceId": trace_id, "observationId": span["spanId"],
                "metadata": {"dataset_manifest_sha256": run["dataset"]["manifest_sha256"],
                    "prompt_sha256": run["prompt"]["prompt_sha256"], "prompt_version": run["prompt_version"],
                    "quality_gate_sha256": digest(gate), "cost_event_ids": [v["cost_event_id"] for v in snapshot["costs"]]}})
            record = {"run_id": run["run_id"], "item_id": args["item_id"], "trace_id": trace_id,
                "observation_id": span["spanId"], "output": output, "output_sha256": digest(output),
                "expected_sha256": item["expected_sha256"], "central": snapshot, "remote": remote,
                "objective_success": digest(output) == item["expected_sha256"] and gate["passed"],
                "actual_cost": sum(c["actual_cost"] for c in snapshot["costs"]),
                "latency_ms": snapshot["latency_ms"],
                "scores": [], "verifier": manifest["verifier"]}
            self.state.put("result:" + run["run_id"] + ":" + self.name(args["item_id"]), record)
            old = self.state.get("run:" + run["run_id"])
            old["value"]["items"].append(args["item_id"])
            self.state.put("run:" + run["run_id"], old["value"], expected_revision=old["revision"])
            return {"run_id": run["run_id"], "item_id": args["item_id"], "trace_id": trace_id,
                    "objective_success": record["objective_success"], "quality_gate_authoritative": True}
        if action in {"eval_score", "score_create"}:
            return self._score(args, context, request_key)
        if action == "eval_compare": return self.compare(args["run_a"], args["run_b"])
        if action == "run_get":
            run = self._get("run:" + self.name(args["run_id"]))
            return self.client.dispatch(action, {"datasetName": run["dataset"]["remote_name"], "runName": run["run_id"]})
        if action == "scores_get":
            item = self._get("result:" + self.name(args["run_id"]) + ":" + self.name(args["item_id"]))
            return self.client.dispatch(action, {"traceId": item["trace_id"], "limit": 100})
        # Arbitrary trace/run-item payloads would bypass the central origin bind.
        raise PermissionError("use eval_item for central trace/run-item submission")

    def _score(self, args, context, request_key):
        run_id, item_id = self.name(args["run_id"]), self.name(args["item_id"])
        key = "result:" + run_id + ":" + item_id
        row = self.state.get(key)
        if row is None: raise FileNotFoundError("evaluation item unavailable")
        item = row["value"]
        data_type = args["data_type"]
        value = _score(args["value"], data_type, categories=args.get("categories"),
                       min_value=args.get("min_value"), max_value=args.get("max_value"))
        if data_type == "TEXT" and len(value) > 500: raise ValueError("Langfuse text score exceeds 500 characters")
        correction = args.get("correction_of")
        if correction is not None and not any(s["id"] == correction for s in item["scores"]):
            raise PermissionError("correction must refer to a score of the same run item")
        score_id = digest([self.prefix, run_id, item_id, request_key])
        body = {"id": score_id, "traceId": item["trace_id"], "observationId": item["observation_id"],
                "name": self.name(args["name"]), "dataType": data_type, "value": value,
                "metadata": {"sentra_reviewer_sha256": digest(context.request.principal_id),
                             "correction_of": correction, "quality_gate_sha256": digest(item["central"]["quality_gate"]),
                             "scores_advisory": True}}
        remote = self.client.dispatch("score_create", body)
        item["scores"].append({**body, "remote": remote})
        self.state.put(key, item, expected_revision=row["revision"])
        return {"score_id": score_id, "transport_acknowledged": True, "scores_advisory": True,
                "quality_gate_changed": False, "budget_changed": False}

    def compare(self, run_a, run_b):
        a, b = self._get("run:" + self.name(run_a)), self._get("run:" + self.name(run_b))
        if (a["dataset"]["name"], a["dataset"]["version"], a["dataset"]["manifest_sha256"]) != (
                b["dataset"]["name"], b["dataset"]["version"], b["dataset"]["manifest_sha256"]):
            raise ValueError("comparison requires the same pinned dataset/environment/verifier")
        rows = []
        for item_id in sorted(set(a["items"]) | set(b["items"])):
            results = {run: self.state.get("result:" + run + ":" + item_id) for run in (run_a, run_b)}
            success = {run: result["value"]["objective_success"] if result else None for run, result in results.items()}
            rows.append({"item_id": item_id, "success": success,
                "cost": {run: result["value"]["actual_cost"] if result else None for run, result in results.items()},
                "latency_ms": {run: result["value"]["latency_ms"] if result else None for run, result in results.items()},
                "regression": success[run_a] is True and success[run_b] is False,
                "fixed": success[run_b] is True and success[run_a] is False})
        return {"run_a": run_a, "run_b": run_b, "items": rows,
                "regressions": [r["item_id"] for r in rows if r["regression"]],
                "fixed": [r["item_id"] for r in rows if r["fixed"]],
                "scores_advisory": True, "quality_gate_authoritative": True}

    def observe(self, action, args, request_key):
        """Read the existing identity after lost ACK; never repeat creation."""
        if action == "prompt_create":
            name = self.name(args["name"])
            remote = self.client.dispatch("prompt_get", {"name": self.prefix + name, "label": "latest"})
            expected_config = {**args.get("config", {}), "sentra_request_key": request_key}
            if remote.get("prompt") != args["prompt"] or remote.get("config") != expected_config:
                return None
            version = self.version(remote["version"])
            key = "prompt:" + name + ":" + str(version)
            if self.state.get(key) is None:
                self.state.put(key, {"request": {"name": self.prefix + name, "prompt": args["prompt"],
                    "config": expected_config}, "remote": remote,
                    "prompt_sha256": digest({"prompt": args["prompt"], "config": expected_config})})
            return {"name": name, "version": version, "observed": True, "created_again": False}
        if action == "dataset_create":
            name, version = self.name(args["name"]), self.version(args["version"])
            manifest = {k: args[k] for k in ("environment", "provider", "model", "tools", "verifier")}
            remote_name = self.prefix + name + "@" + str(version)
            remote = self.client.dispatch("dataset_get", {"name": remote_name})
            if remote.get("name") != remote_name or (remote.get("metadata") or {}).get("manifest_sha256") != digest(manifest):
                return None
            key = "dataset:" + name + ":" + str(version)
            if self.state.get(key) is None:
                self.state.put(key, {"name": name, "version": version, "remote_name": remote_name,
                    "remote": remote, "manifest": manifest, "manifest_sha256": digest(manifest),
                    "created_at": remote.get("createdAt")})
            return {"name": name, "version": version, "observed": True, "created_again": False}
        if action == "item_put":
            dataset = self._dataset(args["dataset_name"], args["dataset_version"])
            key = "item:" + dataset["name"] + ":" + str(dataset["version"]) + ":" + self.name(args["item_id"])
            remote_id = digest([self.prefix, key])
            remote = self.client.dispatch("item_get", {"id": remote_id})
            if (remote.get("id") != remote_id or remote.get("input") != args["input"]
                    or remote.get("expectedOutput") != args["expected_output"]): return None
            if self.state.get(key) is None:
                self.state.put(key, {"remote_id": remote_id, "input": args["input"],
                    "expected_output": args["expected_output"], "expected_sha256": digest(args["expected_output"]),
                    "input_sha256": digest(args["input"]), "remote": remote})
            return {"item_id": args["item_id"], "observed": True, "created_again": False}
        if action in {"eval_score", "score_create"}:
            key = "result:" + self.name(args["run_id"]) + ":" + self.name(args["item_id"])
            row = self.state.get(key)
            if row is None: return None
            score_id = digest([self.prefix, args["run_id"], args["item_id"], request_key])
            remote = self.client.dispatch("scores_get", {"traceId": row["value"]["trace_id"], "limit": 100})
            matches = [score for score in remote.get("data", []) if score.get("id") == score_id
                       and score.get("name") == args["name"] and score.get("value") == args["value"]
                       and score.get("dataType") == args["data_type"]]
            if len(matches) != 1: return None
            if not any(s["id"] == score_id for s in row["value"]["scores"]):
                row["value"]["scores"].append(matches[0])
                self.state.put(key, row["value"], expected_revision=row["revision"])
            return {"score_id": score_id, "observed": True, "scores_advisory": True, "created_again": False}
        if action == "eval_run":
            run_id = "eval-" + digest([self.prefix, request_key])[:40]
            row = self.state.get("run:" + run_id)
            return {"run_id": run_id, "recorded": True} if row else None
        if action == "eval_item":
            row = self.state.get("result:" + self.name(args["run_id"]) + ":" + self.name(args["item_id"]))
            return row["value"] if row else None
        return None
