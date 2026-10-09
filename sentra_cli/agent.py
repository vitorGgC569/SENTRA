"""Agentic execution loop for SENTRA CLI."""
from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from sentra_core.conversations import ConversationStore, UncertainCall
from sentra_core.context import RollingContextCondenser, LedgerSummaryRunner
from typing import Callable, Generator

from .client import ModelClient
from .config import CLIConfig
from .jobs import BackgroundJobManager
from .maestri import MaestriBridge
from .canvas import CanvasBridge
from .tools import (
    apply_patch,
    git_diff,
    git_status,
    list_files,
    read_file,
    run_registered,
    run_tests,
    search_text,
    write_file,
)

DIRECTIVE_RE = re.compile(
    r"\[\[([A-Z_]+)(?:\|(.*?))?\]\]",
    re.DOTALL,
)

SYSTEM_PROMPT = """Você é o SENTRA CLI, um agente de engenharia de software
autônomo, rigoroso e auditável. Você opera somente no workspace local
autorizado e pode colaborar com agentes conectados no canvas do Maestri.

FERRAMENTAS:
- [[MEMORY|search|texto|cursor_json_opcional]] busca contexto protegido de conversas anteriores deste workspace, com origem. Se has_more=true, use next_cursor para continuar.
- [[MEMORY|session|id]] lê o histórico recente de uma conversa salva neste workspace.
- [[R|caminho|linha_ini|linha_fim]] lê arquivo.
- [[LIST|caminho]] lista diretório.
- [[SEARCH|texto|caminho|glob]] busca texto no workspace.
- [[W|caminho|conteúdo]] cria/escreve arquivo.
- [[PATCH|diff_unificado]] aplica patch validado.
- [[TEST|alvo]] dispara pytest em background e retorna ACK com job id.
- [[LINT]], [[TYPECHECK]], [[BUILD]], [[BENCH]] disparam quality gates em background.
- [[JOB|id]] consulta um job; [[JOBS]] lista jobs recentes.
- [[DIFF]] e [[STATUS]] consultam Git.
- [[MAESTRI|list]] lista conexões do canvas.
- [[MAESTRI|dispatch|Agente|pergunta]] dispara trabalho em background sem bloquear o SENTRA.
- [[MAESTRI|dispatch_batch|{"Agente A":"pergunta","Agente B":"pergunta"}]] dispara vários agentes em background.
- [[MAESTRI|ask|Agente|pergunta]] espera a resposta; use só quando a resposta imediata for realmente necessária.
- [[MAESTRI|batch|{"Agente A":"pergunta","Agente B":"pergunta"}]] espera o lote inteiro; prefira dispatch_batch para trabalho longo.
- [[MAESTRI|raw|Agente|entrada]] envia entrada crua quando necessário.
- [[MAESTRI|check|Agente]] consulta saída atual sem enviar mensagem.
- [[MAESTRI|note_read|Nota]] lê nota conectada.
- [[MAESTRI|note_write|Nota|conteúdo]] atualiza nota conectada.
- [[MAESTRI|exec|portal|snapshot|App]] acessa a superfície oficial completa do Maestri (recruit/connect/role/routine/workspace/floor/portal).

REGRAS:
1. Nunca invente saída de ferramenta, teste, build ou outro agente.
2. Antes de editar, inspecione código e contexto relevantes.
3. Para arquivos existentes prefira PATCH, reduzindo risco de sobrescrever
   trabalho concorrente de outro agente.
4. Valide alterações com os gates apropriados. Não declare sucesso sem
   evidência executada.
5. No Maestri, use list primeiro e preserve exatamente o nome do agente.
6. TEST/LINT/TYPECHECK/BUILD/BENCH são assíncronos: ao receber ACK job=..., informe que o trabalho foi disparado e libere o usuário. Não espere o job terminar no mesmo turno e não declare sucesso antes de [[JOB|id]] confirmar SUCCEEDED.
7. Para tarefas de agentes que podem levar mais que alguns segundos, prefira dispatch/dispatch_batch, continue verificando outras ações independentes e só depois use check.
8. Não reenvie automaticamente uma pergunta se ask expirar; use check.
9. Não faça operações destrutivas fora do pedido explícito do usuário. Para
   dismiss/note delete/portal close/role delete/routine delete, acrescente
   |--confirm somente quando o usuário tiver pedido explicitamente a remoção.
10. Seja direto na resposta final e diferencie evidência de inferência.
"""


def _bounded(text: str, limit: int = 20_000) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... [truncated {len(text) - limit} chars]"


class SentraAgent:
    """Conversation state plus deterministic tool-dispatch rounds."""

    def __init__(self, config: CLIConfig) -> None:
        self.config = config
        self.store = ConversationStore(config.state_root)
        self.session_id = self.store.open(config.workspace, session_id=config.session_id,
                                          resume=config.resume_session)
        self._turn_id = None
        self.client = ModelClient(config)
        self.client.bind_conversation(self.session_id)
        self.client.on_delivery = self._delivery
        self.client.on_usage = self._usage
        self.client.on_before_provider = self._before_provider
        self._usage_ledger = None
        self.usage_error = None
        self.maestri = MaestriBridge(config)
        self.canvas = CanvasBridge(config)
        self._directive_call_id = None
        self.jobs = BackgroundJobManager(config.workspace)
        self.context_condenser = RollingContextCondenser()
        self._context_summary_config = None
        self.context_projection = None
        self.messages = self._history()

    def _history(self):
        prompt = SYSTEM_PROMPT
        if self.canvas.is_available:
            prompt = prompt.replace("canvas do Maestri", "Canvas nativo do SENTRA")
            prompt = "\n".join(line for line in prompt.splitlines()
                               if not line.startswith("- [[MAESTRI|") and not line.startswith("5. No Maestri,"))
            prompt += "\nCANVAS NATIVO: use [[CANVAS|list]] para listar apenas conexões dirigidas deste terminal. " \
                "[[CANVAS|create_agent|nome|modelo|papel]] cria um agente SENTRA CLI real com terminal, " \
                "sessão persistente e conexão dirigida deste solicitante, dentro da quota existente. " \
                "[[CANVAS|create_terminal|nome|modelo]] cria um terminal SENTRA CLI real conectado. " \
                "Guarde node_id e resource do resultado. [[CANVAS|connect|id]] conecta este terminal " \
                "a um nó autorizado; [[CANVAS|connect|origem|destino]] conecta pares criados por você. " \
                "[[CANVAS|create_team|nome|coordenador|worker_id1,worker_id2]] organiza agentes autorizados. " \
                "Use [[CANVAS|dispatch|id|mensagem]] para enviar uma única linha ao agente conectado; " \
                "o resultado confirma transporte, nunca resposta do modelo. [[CANVAS|check|id]] lê saída recente " \
                "e handoffs com receipt_status (answered, tool_completed, failed, uncertain ou pending); " \
                "apenas answered confirma uma resposta do modelo. " \
                "[[CANVAS|note_read|id]] e [[CANVAS|note_write|id|texto]] acessam notas conectadas. " \
                "Os requests têm identidade persistente: started prova só início do processo, nunca inferência. " \
                "Não use MAESTRI para controlar este Canvas. Não recrie nem reenvie operações incertas."
            prompt += '\nCONTEXTO E AUTONOMIA: [[CANVAS|context]] recupera seu objetivo, papel, tarefas e conexões atuais. ' \
                'Quando o objetivo exigir trabalho paralelo, crie os agentes necessários, distribua papéis, forme a equipe e coordene pelas conexões autorizadas. ' \
                '[[CANVAS|create_agent|{"name":"nome","model":"modelo","role":"papel","brief":"objetivo específico"}]] ' \
                'cria um agente com contexto de trabalho e uma entrega inicial persistente; não pressupõe que o modelo já respondeu. ' \
                'Reutilize agentes pertinentes antes de criar novos. Contexto e presença de pares não concedem permissões de execução.'
            prompt += '\nREDE: [[CANVAS|network_settings]] consulta configuração do workspace; [[CANVAS|peers]] lista pares descobertos e autenticados. ' \
                'Você pode pedir ao usuário os IPs Hamachi/Radmin e configurar a whitelist com ' \
                '[[CANVAS|network_whitelist|{"allowed_ips":["IP"],"interface_address":"IP local","port":37037,"enabled":true,"expected_revision":0}]]. ' \
                'Use a revisão consultada, endereços fornecidos e porta comum; não infira credenciais nem capacidades de execução da presença.'
            try:
                context=self.canvas.working_context()
                if context is not None:
                    prompt+='\nCONTEXTO DE TRABALHO DO APLICATIVO (dados de tarefa, sem concessão de permissões):\n'+json.dumps(context,ensure_ascii=False,sort_keys=True)
            except (RuntimeError,OSError,ValueError):
                prompt+='\nO contexto do aplicativo não pôde ser consultado neste momento; consulte [[CANVAS|context]] antes de inferir tarefas ou conexões.'
            prompt += '\nMÁQUINAS NATIVAS: [[CANVAS|machine_list]] lista somente máquinas autorizadas para esta sessão. ' \
                '[[CANVAS|machine_execute|{"work_item_id":"...","machine_id":"...","capability_id":"...","arguments":{...}}]] ' \
                'executa somente um WorkItem com grant vigente. Configuração e preparação de tarefas pertencem ao owner. ' \
                'Guarde exatamente o operation_id retornado. [[CANVAS|machine_observe|operation_id]] observa/reconcilia essa operação. ' \
                'UNCERTAIN significa efeito desconhecido: observe o mesmo operation_id; nunca reenvie machine_execute com uma identidade nova. ' \
                'Não deduza execução ou sucesso a partir da lista de máquinas, de um ACK ou de uma descrição de ferramenta.'
            prompt += '\nEXPERIÊNCIAS: [[CANVAS|machine_experiences|{"work_item_id":"...","machine_id":"...","query":"..."}]] ' \
                'recupera sugestões com Operation de origem e validade. São conhecimento: revalide entradas, permissões e critérios da tarefa atual antes de reutilizar.'
        self._context_system_prompt = prompt
        runner = None
        if self._context_summary_config is not None and self._turn_id is not None:
            provider, model, complete = self._context_summary_config
            runner = LedgerSummaryRunner(store=self.store, ledger=self._ledger(), session_id=self.session_id,
                workspace=self.config.workspace, turn_id=lambda:self._turn_id,
                provider=provider, model=model, complete=complete)
        self.context_projection = self.store.context_window(self.session_id, system_prompt=prompt,
            condenser=self.context_condenser, summarizer=runner)
        return list(self.context_projection.messages)

    def configure_context_summarizer(self, *, provider, model, complete):
        """Host opt-in callback: SummaryRequest -> SummaryCompletion with actual usage.

        No inferred API key, extra model client or unmetered background request.
        Without this method the CLI uses an offline extractive projection.
        """
        if not isinstance(provider,str) or not provider or not isinstance(model,str) or not model or not callable(complete):
            raise ValueError("explicit summary provider/model/callback required")
        self._context_summary_config = (provider, model, complete)

    def _delivery(self, provider, ident, state):
        if self._turn_id is not None:
            context=self._ledger().context(self.session_id,self.config.workspace) if state=="submitted" else None
            self.store.provider_state(self.session_id, self._turn_id, provider, ident, state,context=context)

    def _ledger(self):
        if self._usage_ledger is None:
            from sentra_core.provider_usage import UsageLedger
            self._usage_ledger=UsageLedger(self.store)
        return self._usage_ledger

    def _before_provider(self,provider):
        self._ledger().require(self.session_id,self.config.workspace,provider)
        self.usage_error=None

    def _usage(self,provider,ident,model,usage):
        if self._turn_id is None:raise RuntimeError("usage reported without an active turn")
        ledger=self._ledger()
        context=ledger.context(self.session_id,self.config.workspace)
        self.store.record_provider_usage(self.session_id,self._turn_id,provider,ident,model,usage,context)
        try:
            ledger.flush(ident=self.session_id)
            self.usage_error=None
        except (OSError,ValueError,RuntimeError,sqlite3.Error) as exc:
            self.usage_error=type(exc).__name__

    def resume(self, session_id):
        if self._turn_id is not None:
            raise RuntimeError("cannot switch conversations while executing a turn")
        self.session_id = self.store.open(self.config.workspace, session_id=session_id, resume=True)
        self.client.bind_conversation(self.session_id)
        self.messages = self._history()

    def reset(self) -> None:
        if self._turn_id is not None:
            raise RuntimeError("cannot reset a conversation while executing a turn")
        self.session_id = self.store.open(self.config.workspace)
        self.client.bind_conversation(self.session_id)
        self.messages = self._history()

    @staticmethod
    def wants_maestri_orchestration(user_input: str) -> bool:
        """Detect explicit requests to make this terminal orchestrate Maestri."""
        normalized = unicodedata.normalize("NFKD", user_input)
        folded = "".join(
            char for char in normalized
            if not unicodedata.combining(char)
        ).lower().strip()
        if not folded:
            return False
        if folded.startswith(("como ", "o que ", "explique ", "me explique ")):
            return False

        subjects = (
            "maestri",
            "agente",
            "agentes",
            "terminal",
            "terminais",
            "colaboracao",
            "equipe",
            "time de agentes",
        )
        actions = (
            "gerencie",
            "gerenciar",
            "coordene",
            "coordenar",
            "recrute",
            "recrutar",
            "delegue",
            "delegar",
            "monte uma equipe",
            "crie uma colaboracao",
            "criar uma colaboracao",
            "organize os agentes",
        )
        return (
            any(subject in folded for subject in subjects)
            and any(action in folded for action in actions)
        )

    def orchestrate_maestri(self, goal: str) -> str:
        return self.maestri.orchestrate_repository(goal)

    @staticmethod
    def _is_async_ack(result: str) -> bool:
        folded = result.casefold()
        return (
            result.startswith("ACK ")
            or "dispatched in background" in folded
            or "terminal submit dispatched" in folded
            or "batch dispatched in background" in folded
        )

    def _claim_canvas_delivery(self, message: str) -> str | None:
        if not self.canvas.is_available:
            return None
        try:
            return self.canvas.claim(message.strip())
        except (OSError, ValueError, RuntimeError):
            # Losing the receipt channel must not cause a duplicate model turn.
            return None

    def _complete_canvas_delivery(self, ident: str | None, receipt: str) -> None:
        if ident:
            try:
                self.canvas.receipt(ident, receipt)
            except (OSError, ValueError, RuntimeError):
                # A missed ACK stays observable as running/uncertain in Canvas.
                pass

    def execute_directive(self, operation: str, raw_args: str) -> str:
        if self._turn_id is None:
            with self.store.executing(self.session_id):
                receipt_id = self._claim_canvas_delivery(f"[[{operation}|{raw_args}]]")
                receipt_state = "uncertain"
                self.messages = self._history()
                turn, message = self.store.begin_turn(self.session_id, f"[[{operation}|{raw_args}]]",
                                                       kind="memory_query" if operation.upper() == "MEMORY" else "command")
                self.messages.append(message)
                self._turn_id = turn
                try:
                    result = self._journaled_directive(operation, raw_args)
                    self.messages.append(self.store.append(self.session_id, "user", "[TOOL RESULT]\n" + result,
                                                           kind="memory_recall" if operation.upper() == "MEMORY" else "tool_result"))
                    self.store.end_turn(self.session_id, turn)
                    receipt_state = "tool_completed"
                    return result
                except BaseException:
                    self.store.end_turn(self.session_id, turn, "interrupted")
                    raise
                finally:
                    self._complete_canvas_delivery(receipt_id, receipt_state)
                    self._turn_id = None
        return self._journaled_directive(operation, raw_args)

    def _journaled_directive(self, operation, raw_args):
        call, recorded = self.store.start_tool(self.session_id, self._turn_id, operation, raw_args)
        if recorded is not None:
            return "Recovered recorded result; no tool was executed again.\n" + str(recorded)
        previous_call = self._directive_call_id
        self._directive_call_id = call
        try:
            result = self._execute_directive(operation, raw_args)
            if operation.upper() == "CANVAS" and raw_args.partition("|")[0] in {"machine_execute","machine_observe"}:
                result = self._machine_receipt(result)
        finally:
            self._directive_call_id = previous_call
        self.store.finish_tool(self.session_id, call, result)
        return result

    @staticmethod
    def _machine_receipt(result):
        """Keep opaque returned identities before potentially large tool evidence."""
        try:
            payload = json.loads(result)
        except (ValueError,TypeError):
            return result
        receipts = []
        def visit(value):
            if isinstance(value,dict):
                if isinstance(value.get("operation_id"),str):
                    receipts.append({"operation_id":value["operation_id"],"state":value.get("state")})
                for child in value.values(): visit(child)
            elif isinstance(value,list):
                for child in value: visit(child)
        visit(payload)
        if not receipts:
            return result
        output = {"machine_operation_receipts":receipts,**payload} if isinstance(payload,dict) else {
            "machine_operation_receipts":receipts,"result":payload}
        if any(r["state"] == "UNCERTAIN" for r in receipts):
            output = {"machine_operation_receipts":receipts,"recovery_instruction":
                "UNCERTAIN: use CANVAS machine_observe with the SAME operation_id; never resubmit with a fresh identity.",
                **{k:v for k,v in output.items() if k!="machine_operation_receipts"}}
        return json.dumps(output,ensure_ascii=False)

    def _execute_directive(self, operation: str, raw_args: str) -> str:
        op = operation.upper()

        if op == "MEMORY":
            action, _, value = raw_args.partition("|")
            if action == "search":
                query, separator, cursor = value.partition("|")
                return json.dumps(self.store.search_page(self.config.workspace, query,
                    after=json.loads(cursor) if separator else None), ensure_ascii=False)
            if action == "session":
                # Verify the requested session belongs to this exact workspace.
                status = self.store.status(value)
                if status["workspace"] != str(self.config.workspace):
                    raise PermissionError("conversation belongs to another workspace")
                return json.dumps(self.store.messages(value, limit=50), ensure_ascii=False)
            return "Error: MEMORY supports search or session"

        if op in {"R", "READ"}:
            parts = raw_args.split("|", 2) if raw_args else []
            path = parts[0].strip() if parts else ""
            start = (
                int(parts[1])
                if len(parts) > 1 and parts[1].strip().isdigit()
                else None
            )
            end = (
                int(parts[2])
                if len(parts) > 2 and parts[2].strip().isdigit()
                else None
            )
            return read_file(self.config.workspace, path, start, end)

        if op == "LIST":
            path = raw_args.strip() or "."
            return list_files(self.config.workspace, path)

        if op == "SEARCH":
            parts = raw_args.split("|", 3) if raw_args else []
            pattern = parts[0].strip() if parts else ""
            path = parts[1].strip() if len(parts) > 1 else "."
            glob = parts[2].strip() if len(parts) > 2 else "*"
            return search_text(
                self.config.workspace,
                pattern,
                path or ".",
                glob or "*",
            )

        if op == "W":
            path, sep, content = raw_args.partition("|")
            if not sep or not path.strip():
                return "Error: W requires path and content"
            return write_file(
                self.config.workspace,
                path.strip(),
                content,
            )

        if op == "PATCH":
            return apply_patch(self.config.workspace, raw_args)

        if op == "TEST":
            target = raw_args.strip() or "all"
            return self.jobs.submit(
                "TEST",
                target,
                timeout=max(self.config.timeout_s, 60.0),
            )

        if op in {"LINT", "TYPECHECK", "BUILD", "BENCH"}:
            return self.jobs.submit(
                op,
                raw_args.strip(),
                timeout=max(self.config.timeout_s, 180.0),
            )

        if op == "JOB":
            return self.jobs.status(raw_args.strip())

        if op == "JOBS":
            return self.jobs.list_jobs()

        if op == "DIFF":
            return git_diff(self.config.workspace)

        if op == "STATUS":
            return git_status(self.config.workspace)

        if op == "CANVAS":
            return self.canvas.execute(raw_args,self._directive_call_id)

        if op == "MAESTRI":
            if self.canvas.is_available:
                raise RuntimeError("Use CANVAS to control the native SENTRA Canvas")
            return self._execute_maestri(raw_args)

        return f"Unknown directive: [[{operation}]]"

    def _execute_maestri(self, raw_args: str) -> str:
        action, sep, rest = raw_args.partition("|")
        action = action.strip().lower()
        if action == "orchestrate":
            return self.orchestrate_maestri(rest)
        if action == "list":
            return self.maestri.list_peers()
        if action == "debug":
            return self.maestri.debug()
        if action == "dispatch":
            peer, sep2, prompt = rest.partition("|")
            if not sep2 or not peer.strip() or not prompt.strip():
                return "Error: MAESTRI dispatch requires agent and prompt"
            return self.maestri.dispatch_ask(peer.strip(), prompt)
        if action == "ask":
            peer, sep2, prompt = rest.partition("|")
            if not sep2 or not peer.strip() or not prompt.strip():
                return "Error: MAESTRI ask requires agent and prompt"
            return self.maestri.ask(peer.strip(), prompt)
        if action == "raw":
            peer, sep2, raw_input = rest.partition("|")
            if not sep2 or not peer.strip():
                return "Error: MAESTRI raw requires agent and raw input"
            return self.maestri.ask_raw(peer.strip(), raw_input)
        if action == "exec":
            argv = [part.strip() for part in rest.split("|") if part.strip()]
            if not argv:
                return "Error: MAESTRI exec requires at least one command argument"
            confirmed = "--confirm" in argv
            clean = [item for item in argv if item != "--confirm"]
            return self.maestri.command(
                *clean,
                timeout=180.0,
                allow_destructive=confirmed,
            )
        if action == "check":
            if not rest.strip():
                return "Error: MAESTRI check requires an agent"
            return self.maestri.check(rest.strip())
        if action in {"batch", "dispatch_batch"}:
            try:
                prompts = json.loads(rest)
            except ValueError as exc:
                return f"Error: invalid batch JSON: {exc}"
            if not isinstance(prompts, dict):
                return "Error: batch payload must be an object"
            normalized = {
                str(key): str(value)
                for key, value in prompts.items()
            }
            if action == "dispatch_batch":
                return self.maestri.dispatch_batch(normalized)
            return self.maestri.ask_batch(normalized)
        if action == "note_read":
            return self.maestri.note_read(rest.strip())
        if action == "note_write":
            name, sep2, content = rest.partition("|")
            if not sep2 or not name.strip():
                return "Error: note_write requires note and content"
            return self.maestri.note_write(name.strip(), content)
        return f"Unknown Maestri action: {action}"

    def step_stream(
        self,
        user_input: str,
        on_tool_call: Callable[[str, str], None] | None = None,
        on_tool_result: Callable[[str], None] | None = None,
        max_tool_rounds: int | None = None,
        *, continue_previous: bool = False,
    ) -> Generator[str, None, None]:
        """Run a user turn through bounded, deduplicated tool rounds."""
        with self.store.executing(self.session_id):
            receipt_id = None
            receipt_state = "uncertain"
            self.messages = self._history()
            status = self.store.status(self.session_id)
            if any(c["kind"] == "provider" for c in status["uncertain_calls"]):
                raise UncertainCall("previous provider delivery is uncertain; inspect /session and resolve it before submitting a new turn")
            if continue_previous:
                turn, message = self.store.continue_turn(self.session_id)
            else:
                turn, message = self.store.begin_turn(self.session_id, user_input)
                receipt_id = self._claim_canvas_delivery(user_input)
            self.messages.append(message)
            self._turn_id = turn
            try:
                yield from self._step_stream(user_input, on_tool_call, on_tool_result, max_tool_rounds)
                if self.client.last_error:
                    receipt_state = ("uncertain" if self.client.last_delivery_state == "uncertain"
                                     else "failed")
                else:
                    receipt_state = "answered"
            except BaseException:
                self.store.end_turn(self.session_id, turn, "interrupted")
                raise
            finally:
                self._complete_canvas_delivery(receipt_id, receipt_state)
                self._turn_id = None

    def _step_stream(self, user_input, on_tool_call=None, on_tool_result=None, max_tool_rounds=None):
        if (
            self.maestri.is_available
            and self.wants_maestri_orchestration(user_input)
        ):
            # Orchestration is an external side effect and uses the same journal.
            yield self.execute_directive("MAESTRI", "orchestrate|" + user_input)
            self.store.end_turn(self.session_id, self._turn_id)
            return

        limit = max_tool_rounds or self.config.max_tool_rounds
        seen: set[tuple[str, str]] = set()

        for round_index in range(1, limit + 1):
            # Reload from the protected transcript on every provider round;
            # appended tool results are never lost through in-memory trimming.
            self.messages = self._history()
            full_response = "".join(
                self.client.chat_stream(self.messages)
            )
            if self.client.last_error:
                self.messages.append(self.store.append(self.session_id, "assistant", full_response, kind="provider_error"))
                state = "uncertain" if self.client.last_delivery_state == "uncertain" else "provider_error"
                self.store.end_turn(self.session_id, self._turn_id, state)
                yield full_response
                return
            self.messages.append(self.store.finish_response(self.session_id, self._turn_id, full_response))

            directives = list(DIRECTIVE_RE.finditer(full_response))
            visible = DIRECTIVE_RE.sub("", full_response).strip()
            if not directives:
                self.store.end_turn(self.session_id, self._turn_id)
            if visible:
                yield visible
                if directives:
                    yield "\n"

            if not directives:
                return

            tool_outputs: list[str] = []
            memory_recall = False
            async_ack_seen = False
            for match in directives:
                op = match.group(1)
                memory_recall = memory_recall or op == "MEMORY"
                args = match.group(2) or ""
                fingerprint = (op, args)
                if fingerprint in seen:
                    result = (
                        "Skipped duplicate directive in the same user turn."
                    )
                else:
                    seen.add(fingerprint)
                    if on_tool_call:
                        on_tool_call(op, args[:120])
                    result = self.execute_directive(op, args)
                    async_ack_seen = (
                        async_ack_seen
                        or self._is_async_ack(result)
                    )
                    if on_tool_result:
                        preview = _bounded(result, 500)
                        on_tool_result(preview)

                tool_outputs.append(
                    f"Resultado de [[{op}]]:\n{_bounded(result)}"
                )

            observation = "\n\n---\n".join(tool_outputs)
            self.messages.append(self.store.append(self.session_id, "user", (
                        "[OBSERVAÇÃO DAS FERRAMENTAS]\n"
                        + _bounded(observation, 60_000)
                        + "\n\nContinue usando somente estes dados."
                    ), kind="memory_recall" if memory_recall else "tool_result"))

            if async_ack_seen:
                # Do not spend another model round waiting for work that was
                # intentionally detached. The ACK is already visible and the
                # user gets the prompt back immediately.
                self.store.end_turn(self.session_id, self._turn_id)
                yield "\n"
                return

            yield "\n"

        self.store.end_turn(self.session_id, self._turn_id, "limit_reached")
        yield (
            f"\nTool-round limit reached ({limit}). "
            "No additional directives were executed automatically.\n"
        )
