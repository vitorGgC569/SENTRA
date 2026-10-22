"""Agentic execution loop for SENTRA CLI."""
from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
import base64
import time
from sentra_core.conversations import ConversationStore, UncertainCall
from sentra_core.context import RollingContextCondenser, LedgerSummaryRunner
from sentra_core.model_prose import prose_prefix
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

SHELL_SYSTEM_PROMPT = """Você é um Dot do shell SENTRA executando um turno admitido
pelo Control Plane. Contexto descreve objetivo, papel, Dot, conversa, Space,
agente e conexões dirigidas; somente o servidor concede autoridade.
O host SENTRA executa as diretivas literais [[CANVAS|...]] emitidas na sua
resposta e devolve resultados antes da próxima rodada. Use esse protocolo
para chamar as ferramentas abaixo e aguarde os recibos reais.

FERRAMENTAS:
- [[CANVAS|context]] consulta o contexto canônico da execução atual.
- [[CANVAS|list]] lista conexões dirigidas autorizadas.
- [[CANVAS|children]] lista respostas e estado das mensagens nas conversas filhas diretas desta conversa, somente para Dots conectados por saída dirigida.
- [[CANVAS|child_reply|{"conversation_id":"ID retornado por children","content":"mensagem"}]] envia uma resposta para essa conversa filha; o trabalho do filho exige suas próprias permissões e não recebe as permissões do pai.
- [[CANVAS|coordinator_intent|{"kind":"create_dot","name":"Worker_2","role":"worker","model":"sentra/codex/current","instructions":"objetivo"}]] propõe criação de metadata de um Dot; selecione um modelo realmente disponível no contexto.
- [[CANVAS|coordinator_intent|{"kind":...,campos canônicos}]] envia uma intenção estruturada create_dot/create_team/connect/delegate/handoff/pause/resume/cancel/reassign/pause_dot/resume_dot. Consulte o contexto antes de selecionar agentes e campos; o host valida o schema e os alvos.
- [[CANVAS|dispatch|Nome ou ID do Dot conectado|tarefa]] delega para a conversa permanente desse Dot, usando o modelo configurado dele. Este é o fluxo de colaboração entre Dots: registra uma mensagem filha, prepara a autorização permitida e executa pelo gateway SENTRA. Não é um terminal de ferramenta. Consulte children para acompanhar sem reenviar.
- Se o pedido exigir explicitamente uma ferramenta CLI, use [[CANVAS|coordinator_intent|{"kind":"dot_tool_dispatch","tool":"opencode","target_dot_id":"ID retornado por context/list","instruction":"tarefa"}]]. Tools aceitas: sentra-cli (GPT-6 Web high), opencode (Muse Spark 1.3 free high), codex. Cada faixa exige Run, WorkItem, Operation e Grant próprios. Não substitua os modelos nem interprete envio, ACK ou IN_REVIEW como conclusão. A consolidação dessa frota só existe com três recibos verificados e a resposta do coordenador. Execução no guest só vale com processo verificado. Não forneça runner, executável, caminho ou identidade de autoridade no intent.
- Antigravity não é ferramenta deste turno. Aplicativo gráfico aberto não é inferência. Se a admissão da frota marcar antigravity como indisponível, diga isso e não invente CLI nem API.
- [[CANVAS|isolate_work]] cria/reutiliza um worktree Git real para esta tarefa, quando context informar coding_isolation_available e o projeto for Git. Use para separar trabalhos de programação paralelos. Não recebe caminho nem exceção por texto. Depois consulte context: execution_workspace informa a pasta e a branch do trabalho. Arquivos relativos, comandos sem cwd e novos terminais usam essa pasta. Sessões antigas não são movidas. Não execute commit, merge ou push se não fizerem parte do pedido autorizado.
- [[CANVAS|review_worktrees|{"conversation_ids":["conversa própria ou de Dot conectado"]}]] ensaia a combinação das alterações de texto rastreadas dos trabalhos selecionados em uma pasta descartável. Informe de uma a oito conversas. O recibo distingue compatível, conflito, resultado desatualizado e revisão manual necessária. Não altera a pasta principal, não publica Git e não comprova correção semântica. Arquivos novos ainda exigem revisão explícita.
- [[CANVAS|machine_list]] lista máquinas autorizadas; [[CANVAS|machine_execute|{"work_item_id":"ID canônico","machine_id":"ID canônico","capability_id":"capability vigente","arguments":{}}]] requer a tarefa e os Grants do servidor.
- [[CANVAS|machine_observe|operation_id]] observa a mesma operação incerta.
- [[CANVAS|verify_result|{"operation_ids":["op-canvas-ID retornado por leitura"]}]] se context informar result_verification_available, confere novamente os hashes de um a oito arquivos que você leu com computer:file.read neste turno. Ao concluir uma entrega em arquivos, use essa conferência e cite seu recibo. Ela confirma integridade no instante observado; confira também os critérios reais da tarefa. Texto dizendo verified não é uma evidência.
- [[CANVAS|vm_status]] consulta o orçamento e o estado real da VM deste Dot. [[CANVAS|vm_frame]] observa um PNG real no monitor e o transmite como imagem ao modelo. [[CANVAS|vm_input|{"action":"input.key","scancodes":[28,156]}]] envia Enter ao sistema convidado; input.mouse aceita x, y e buttons. VM e WorkItem são selecionados apenas pelo servidor; controle humano impede ações do agente. Observe novamente após cada interação e nunca reenvie uma operação UNCERTAIN com uma nova identidade.
- [[CANVAS|vm_create|{"os_family":"linux","cpus":2,"memory_mb":4096,"disk_gb":64,"iso_path":"caminho absoluto da ISO local"}]] configura/cria uma VM dentro do limite agregado do servidor; somente o root Dot com acesso efetivo completo pode solicitar isso. Sem ISO, o estado é pending_image, não um sistema operacional instalado. Use a ISO local real quando fornecida e configure/provisione conforme os limites aceitos pelo servidor.
- Em machine_list, VM usa vm:observe para status/frame; vm:manage para provision/start/shutdown/pause/resume; vm:input para input.key (scancodes) e input.mouse (x,y absolutos e buttons, entrada exclusiva); vm:guest para guest.run (requer Guest Additions). Para observar uma tela, use machine_execute com capability vm:observe e arguments {"action":"frame"}; o quadro PNG validado será enviado ao modelo como imagem. Uma tomada de controle humana interrompe entradas do agente. Só afirme que o sistema está iniciado quando guest/frame confirmar.
- Arquivos e terminal: use SOMENTE as diretivas CANVAS, nunca alegue que elas não existem sem consultar [[CANVAS|machine_list]].
  O seletor de acesso da conversa configura as permissões reais. Se machine_list não devolver máquina
  e WorkItem com capabilities aplicáveis, solicite a aprovação e não execute a escrita.
  A máquina computer-local com computer:file.read/write/delete e computer:execute permite os caminhos
  ABSOLUTOS autorizados pelo perfil, inclusive fora do Space quando o proprietário selecionou acesso completo.
  Não utilize ferramentas do plugin ChatGPT read_file/list_files para estas operações: elas têm outro escopo
  e podem bloquear .sentra. O Space guarda a conversa; não determina o escopo da máquina autorizada.
  computer:file.read aceita actions read/stat/list; computer:file.write aceita write/edit;
  computer:file.delete aceita delete; computer:execute usa {"command":"PowerShell","cwd":"caminho absoluto"}.
  Para alterações e comandos em computer-local, inclua em arguments um campo reason curto (até 300 caracteres), explicando por que a ação é necessária. O usuário verá essa explicação com o caminho, o alcance e a validade do pedido na conversa. Explicação não concede permissão; aguarde a aprovação e nunca repita uma operação incerta.
  Se uma execução retornar approval_required, informe o pedido pendente e aguarde o proprietário.
  Use o machine_id e work_item_id REAIS retornados pela lista e a capability específica da ação.
  As actions de workspace-files são "write", "read", "edit", "delete", "stat"; os caminhos são RELATIVOS ao projeto.
  Exemplos do campo arguments: {"action":"write","path":"sentra_teste.txt","content":"Teste inicial do SENTRA"};
  {"action":"read","path":"sentra_teste.txt"};
  {"action":"edit","path":"sentra_teste.txt","content":"Teste de edição realizado com sucesso","expected_sha256":"sha256 da leitura"};
  {"action":"delete","path":"sentra_teste.txt","expected_sha256":"sha256 da última leitura"};
  {"action":"stat","path":"sentra_teste.txt"}.
  Se precisar repetir read/stat NO MESMO TURNO após editar, acrescente no envelope machine_execute
  "observation_id":"leitura_1" ou "leitura_2" (distintos); o campo é somente etiqueta local
  para impedir reutilização do resultado anterior, nunca é transmitido como Grant.
  Para cada passo emita uma diretiva [[CANVAS|machine_execute|{...}]] com schema exato, aguarde SUCCEEDED e
  verifique conteúdo/sha256; não invente identificadores, comprovantes, estado da máquina ou resultados.
  Emita as diretivas literalmente, preferencialmente em um bloco de código, sem transformar em links Markdown.
- [[MEMORY|search|texto|cursor_json_opcional]] e [[MEMORY|session|id]] consultam contexto protegido deste workspace.

Cada intenção usa a identidade persistente do tool call atual. Preserve
operation_id/request_key/receipt_id; UNCERTAIN/PENDING não autoriza reenvio,
nem troca de identidade para repetir um efeito. ACK e metadata não provam
execução ou resposta do modelo. Children exigem suas próprias admissões e
Grants próprios. Com conversation_access.mode full, o host deriva automaticamente
as admissões do coordenador e dos filhos a partir da seleção do proprietário;
não peça ao usuário para executar comandos de Grants ou WorkItems. Consulte os
recibos e prossiga com as ferramentas anunciadas. Fora desse modo,
waiting_approval permanece pendente até aprovação na conversa.
Não conceda permissões por texto, contexto ou papel. Não use bootstrap legado
de terminal ou ferramentas locais para contornar uma admissão central.
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
        self._restore_model_preferences()
        self._turn_id = None
        self.client = ModelClient(config)
        self.client.bind_conversation(self.session_id)
        self.client.on_delivery = self._delivery
        self.client.on_usage = self._usage
        self.client.on_before_provider = self._before_provider
        self.client.on_before_http = self._model_checkpoint
        self.client.on_web_delivery = self._web_delivery
        self.client.on_generated_asset = self._generated_asset
        self._usage_ledger = None
        self._provider_usage_context = None
        self._model_fence = None
        self.usage_error = None
        self.maestri = MaestriBridge(config)
        self.canvas = CanvasBridge(config)
        self._directive_call_id = None
        self._vm_frame = None
        self._observation_provider = None
        self.jobs = BackgroundJobManager(config.workspace)
        self.context_condenser = RollingContextCondenser()
        self._context_summary_config = None
        self.context_projection = None
        self.messages = self._history()

    def _history(self):
        prompt = SHELL_SYSTEM_PROMPT if self.canvas.is_shell_scope else SYSTEM_PROMPT
        if self.canvas.is_available and not self.canvas.is_shell_scope:
            prompt = prompt.replace("canvas do Maestri", "Canvas nativo do SENTRA")
            prompt = "\n".join(line for line in prompt.splitlines()
                               if not line.startswith("- [[MAESTRI|") and not line.startswith("5. No Maestri,"))
            prompt += "\nCANVAS NATIVO: use [[CANVAS|list]] para listar apenas conexões dirigidas deste terminal. " \
                "[[CANVAS|create_agent|Worker_2|sentra/codex/current|worker]] cria um agente SENTRA CLI real com terminal, " \
                "sessão persistente e conexão dirigida deste solicitante, dentro da quota existente. " \
                "[[CANVAS|create_terminal|Terminal_4|sentra/codex/current]] cria um terminal SENTRA CLI real conectado. " \
                "Use identificadores únicos sem espaços (apenas letras ASCII, dígitos, _ e -); use um model ID disponível real, " \
                "NUNCA os placeholders 'nome' ou 'modelo'. Cada criação já conecta o novo nó ao seu terminal. " \
                "Guarde node_id e resource do resultado. [[CANVAS|connect|id]] conecta este terminal " \
                "a um nó autorizado; [[CANVAS|connect|origem|destino]] conecta pares criados por você. " \
                "[[CANVAS|create_team|nome|coordenador|worker_id1,worker_id2]] organiza agentes autorizados. " \
                "Use [[CANVAS|dispatch|id|mensagem]] para enviar uma única linha ao agente conectado; " \
                "o resultado confirma transporte, nunca resposta do modelo. [[CANVAS|check|id]] lê saída recente " \
                "e handoffs com receipt_status (answered, tool_completed, failed, uncertain ou pending); " \
                "apenas answered confirma uma resposta do modelo. " \
                "[[CANVAS|note_read|id]] lê notas conectadas; notas apontando para este terminal são somente leitura, " \
                "e [[CANVAS|note_write|id|texto]] só altera notas nas conexões de saída autorizadas. " \
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
        if self.canvas.is_shell_scope:
            from orchestrator.providers.fleet_admission import shell_fleet_notice
            prompt += "\n" + shell_fleet_notice()
            try:
                context = self.canvas.working_context()
                if context is not None:
                    prompt += '\nCONTEXTO CANÔNICO DO SHELL (dados de tarefa, não permissões):\n' + json.dumps(context, ensure_ascii=False, sort_keys=True)
                else:
                    prompt += '\nContexto indisponível: aguarde a conexão host, sem inferir IDs ou iniciar bootstrap.'
            except (RuntimeError, OSError, ValueError):
                prompt += '\nContexto indisponível: consulte CANVAS context antes de coordenar.'
        self._context_system_prompt = prompt
        from sentra_mcp.services.control_store import create_control_plane_store
        authority = create_control_plane_store(self.config.state_root, backend='configured')
        db = authority.connect('execution_workspace')
        try:
            has_goals = bool(db.execute('PRAGMA table_info(conversation_goal_bindings)').fetchall())
        finally:
            db.close()
        if has_goals:
            current_goal = self.goal_loop_command("goal", "status")
            if current_goal.get("state") == "ACTIVE":
                goal = current_goal["goal"]
                prompt += "\nOBJETIVO ATIVO DA CONVERSA (contexto; permissões e limites permanecem na autoridade central): " + json.dumps(
                    {"goal_id": current_goal["goal_id"], "objective": goal["objective"]}, ensure_ascii=False)
                self._context_system_prompt = prompt
        runner = None
        if self._context_summary_config is not None and self._turn_id is not None:
            provider, model, complete = self._context_summary_config
            def fenced_summary(request):
                self._model_checkpoint(provider)
                return complete(request)
            runner = LedgerSummaryRunner(store=self.store, ledger=self._ledger(), session_id=self.session_id,
                workspace=self.config.workspace, turn_id=lambda:self._turn_id,
                provider=provider, model=model, complete=fenced_summary)
        self.context_projection = self.store.context_window(self.session_id, system_prompt=prompt,
            condenser=self.context_condenser, summarizer=runner)
        messages = list(self.context_projection.messages)
        for message in messages:
            if isinstance(message, dict) and isinstance(message.get("content"), str):
                message["content"] = self._redact_image_text(message["content"])
        return messages

    @staticmethod
    def _redact_image_text(text: str) -> str:
        # Recovery text can contain repr() of a protected VM receipt. Never
        # project its large encoded image into ordinary model-visible text.
        return re.sub(r"(?i)([\"']image_base64[\"']\s*:\s*[\"'])[A-Za-z0-9+/=_-]{16,}([\"'])",
                      r"\1[redacted image payload]\2", text)

    @staticmethod
    def _validated_vm_frame(operation: str, raw_args: str, result: str):
        """Return a strict VirtualBox PNG frame from a successful authorized observation."""
        if operation.upper() != "CANVAS":
            return None
        action = raw_args.partition("|")[0]
        if action not in {"machine_execute", "machine_observe", "vm_frame"}:
            return None
        if action == 'vm_frame' and raw_args != 'vm_frame':
            return None
        if action == "machine_execute":
            try:
                request = json.loads(raw_args.partition("|")[2])
                args = request.get("arguments") if isinstance(request, dict) else None
            except (ValueError, TypeError):
                return None
            if not isinstance(request, dict) or request.get("capability_id") != "vm:observe" \
                    or not isinstance(args, dict) or args.get("action") != "frame":
                return None
        elif action == "machine_observe":
            observed_id = raw_args.partition("|")[2].strip()
            if not observed_id:
                return None
        try:
            payload = json.loads(result)
        except (ValueError, TypeError):
            return None
        if not isinstance(payload, dict) or payload.get("state") != "SUCCEEDED":
            return None
        if action == "machine_observe":
            receipts = payload.get("machine_operation_receipts")
            if not isinstance(receipts, list) or not any(
                    isinstance(receipt, dict) and receipt.get("operation_id") == observed_id
                    and receipt.get("state") == "SUCCEEDED" for receipt in receipts):
                return None
        evidence = payload.get("evidence")
        if not isinstance(evidence, dict):
            return None
        encoded = evidence.get("image_base64")
        if evidence.get("transport") != "virtualbox-com-framebuffer" \
                or evidence.get("framebuffer_verified", evidence.get("desktop_verified")) is not True \
                or evidence.get("mime_type") != "image/png" \
                or not isinstance(evidence.get("vm_id"), str) or not evidence["vm_id"] \
                or not isinstance(encoded, str) or len(encoded) > 1_400_000:
            return None
        width, height = evidence.get("width"), evidence.get("height")
        if type(width) is not int or type(height) is not int or not (1 <= width <= 8192 and 1 <= height <= 8192):
            return None
        try:
            decoded = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError):
            return None
        if not decoded.startswith(b"\x89PNG\r\n\x1a\n") or len(decoded) > 1_048_576 \
                or base64.b64encode(decoded).decode("ascii") != encoded:
            return None
        return {"mime_type": "image/png", "data_base64": encoded,
                "vm_id": evidence["vm_id"], "width": width, "height": height}

    @classmethod
    def _model_machine_result(cls, operation: str, raw_args: str, result: str, call_id: str):
        """Keep receipts in protected storage; return safe text and optional ephemeral image."""
        frame = cls._validated_vm_frame(operation, raw_args, result)
        safe = cls._redact_image_text(result)
        if frame is not None:
            try:
                payload = json.loads(result)
                evidence = payload.get("evidence")
                evidence.pop("image_base64", None)
                evidence["frame_available"] = True
                # Legacy receipts used desktop_verified for a framebuffer.
                # A screenshot of BIOS/Setup is not proof of an installed OS.
                evidence["framebuffer_verified"] = True
                evidence["desktop_verified"] = False
                evidence["installed_os_verified"] = False
                payload["evidence"] = evidence
                safe = json.dumps(payload, ensure_ascii=False)
            except (ValueError, TypeError, AttributeError):
                frame = None
        if frame is not None:
            # Keep the reference at the beginning so tool-output truncation
            # cannot sever the link to the one ephemeral image.
            safe = f"[SENTRA_VM_FRAME call_id={call_id}]\n" + safe
        return safe, frame

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
            context=self._approved_provider_context(provider) if state=="submitted" else None
            self.store.provider_state(self.session_id, self._turn_id, provider, ident, state,context=context)
            if state == 'submitted':
                self._observation_provider = (provider, ident)
            if state in {'submitted', 'completed'}:
                from .shell_live_preview import LivePreviewWriter
                LivePreviewWriter().activity('provider_submitted' if state == 'submitted' else 'response_complete')

    def _approved_provider_context(self, provider):
        context = self._recorded_provider_context(provider)
        self._model_checkpoint(provider, expected=context)
        return context

    def _recorded_provider_context(self, provider):
        approved = self._provider_usage_context
        if approved is None or approved[:3] != (self.session_id, self._turn_id, provider):
            raise PermissionError("provider has no matching approved authority context")
        return dict(approved[3])

    def _model_checkpoint(self, provider=None, *, expected=None):
        if self._model_fence is None:
            from .model_fence import ModelInvocationFence
            self._model_fence = ModelInvocationFence(self._ledger(), state_root=self.config.state_root,
                shell_context=self.canvas.authority_checkpoint if self.canvas.is_shell_scope else None)
        return self._model_fence.checkpoint(self.session_id, self.config.workspace,
            provider=provider, expected=expected)

    def _restore_model_preferences(self):
        prefs = self.store.model_preferences(self.session_id, workspace=self.config.workspace)
        if prefs["requested_model"]:
            self.config.model = prefs["requested_model"]
            if self.config.model.startswith("sentra/chatgpt-web/"):
                self.config.web_reasoning_effort = prefs["requested_effort"]
            elif prefs["requested_effort"]:
                self.config.reasoning_effort = prefs["requested_effort"]

    def persist_model_preferences(self):
        effort = (self.config.web_reasoning_effort if self.config.model.startswith("sentra/chatgpt-web/")
                  else self.config.reasoning_effort)
        return self.store.set_model_preferences(self.session_id, self.config.model, effort,
                                                workspace=self.config.workspace)

    def _web_delivery(self, view):
        # Evidence is protected and excluded from ordinary prompt history.
        self.store.record_web_delivery(self.session_id, view, workspace=self.config.workspace)

    def _generated_asset(self, provider, request_id, payload):
        if self._turn_id is None:
            raise PermissionError('generated media requires an active admitted provider turn')
        from sentra_core.generated_media import GeneratedMediaStore
        GeneratedMediaStore(self.store).stage(self.session_id, self._turn_id, provider, request_id, payload)

    def _ledger(self):
        if self._usage_ledger is None:
            from sentra_core.provider_usage import UsageLedger
            self._usage_ledger=UsageLedger(self.store)
        return self._usage_ledger

    def goal_loop_command(self, kind: str, action: str = "status", *,
                          objective: str = "", max_steps: int = 2,
                          max_cost_usd: float = 0.0, deadline_seconds: float = 120):
        """Operator commands act on the central Goal, never a model prompt."""
        from sentra_executors.goal_loop import ConversationGoalLoop
        from sentra_mcp.services.context import ContextBusService
        from sentra_mcp.services.control_plane import ControlPlaneService
        from sentra_mcp.services.durable import DurableRunService

        binding = self._ledger().context(self.session_id, self.config.workspace)
        owner = binding["owner"]
        if self.canvas.is_shell_scope and action != 'status':
            raise PermissionError('shell goals and control transitions require coordinator_intent in the current admission')
        control = ControlPlaneService.from_store(self.config.state_root, backend='configured')
        durable, context = control.durable, control.context
        try:
            goals = ConversationGoalLoop(control, conversations=self.store)
            if kind == "goal":
                if action == "status":
                    return goals.status(owner, self.session_id)
                if action == "stop":
                    return goals.stop(owner, self.session_id, operator_approved=True)
                if action != "set":
                    raise ValueError("use /goal set <objective>|status|stop")
                run_id = binding.get("run_id")
                if not run_id:
                    run_id = durable.create_run(
                        owner, workspace=str(self.config.workspace),
                        idempotency_key="cli-conversation:" + self.session_id,
                        required_capabilities=[],
                    )["run_id"]
                control.ensure_agent(run_id, owner,
                    agent_id=binding.get("agent_id") or "cli:" + self.session_id, role="coordinator")
                return goals.set(owner, self.session_id, run_id=run_id,
                                 objective=objective, operator_approved=True)
            if kind != "loop":
                raise ValueError("unknown conversation control")
            if action == "status":
                return goals.loop_status(owner, self.session_id)
            if action == "stop":
                return goals.loop_stop(owner, self.session_id, operator_approved=True)
            if action == "start":
                return goals.open(owner, self.session_id,
                                  principal_id=binding.get("agent_id") or "cli:" + self.session_id,
                                  max_steps=max_steps, max_cost_usd=max_cost_usd,
                                  deadline_seconds=deadline_seconds, operator_approved=True)
            if action == "step":
                return goals.advance(owner, self.session_id, objective=objective,
                                     operator_approved=True)
            raise ValueError("use /loop start|status|stop|step <objective>")
        finally:
            context.close()
            durable.close()

    def compact_resume_command(self, action: str, arguments: dict):
        """Use the existing checkpoint and continuation gates without model I/O."""
        from native_bridge.conversation_continuation import ConversationWebContinuation
        from native_bridge.job_store import JobStore
        from sentra_mcp.services.context import ContextBusService
        from sentra_mcp.services.control_plane import ControlPlaneService
        from sentra_mcp.services.durable import DurableRunService
        if not isinstance(arguments, dict):
            raise ValueError("Compact&Resume requires an object")
        allowed = ({"run_id", "chat_id", "work_item_id", "principal_id", "request_key", "summary", "cursor", "target_url"}
                   if action == "prepare" else {"allocation_id", "continuation_id"})
        if action not in {"prepare", "status", "resume"} or set(arguments) - allowed:
            raise ValueError("use /compact-resume prepare|status|resume <JSON arguments>")
        owner = self._ledger().context(self.session_id, self.config.workspace)["owner"]
        control = ControlPlaneService.from_store(self.config.state_root, backend='configured')
        durable, context = control.durable, control.context
        outbox = self.store.telemetry_root / "browser" / "relay.sqlite3"
        outbox.parent.mkdir(parents=True, exist_ok=True)
        jobs = JobStore(outbox)
        try:
            continuity = ConversationWebContinuation(control, jobs, conversations=self.store)
            method = getattr(continuity, action)
            kwargs = dict(arguments)
            if action != "status":
                kwargs["operator_approved"] = True
            return method(owner, self.session_id, **kwargs)
        finally:
            jobs.close()
            context.close()
            durable.close()

    def _before_provider(self,provider):
        ledger = self._ledger()
        context = self._model_checkpoint(provider)
        ledger.require(self.session_id,self.config.workspace,provider,authority_context=context)
        if provider == "gateway" and self.config.model.startswith(("sentra/chatgpt-web/", "chatgpt-web/")):
            self._bind_existing_web_authority(authority_context=context)
        self._provider_usage_context = (self.session_id, self._turn_id, provider, dict(context))
        self.usage_error=None

    def _bind_existing_web_authority(self, *, authority_context=None):
        from sentra_mcp.services.control_store import SQLiteControlPlaneStore
        from sentra_mcp.services.authorization import AuthorizationService
        store = SQLiteControlPlaneStore(self.store.telemetry_root)
        with store.connect("session_checkpoint") as db:
            exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='gateway_web_transport_mode'").fetchone()
            row = db.execute("SELECT mode FROM gateway_web_transport_mode WHERE singleton=1").fetchone() if exists else None
        if not exists or (row and row["mode"] == "legacy"):
            return
        if row is None or row["mode"] != "durable_v2":
            raise PermissionError("Web transport is not activated for production")
        binding = self._ledger().context(self.session_id, self.config.workspace)
        if authority_context is not None and binding != authority_context:
            raise PermissionError("Web authority changed after the budget check")
        with store.connect("session_checkpoint") as db:
            pinned = db.execute("SELECT owner,run_id,work_item_id,principal_id,grant_id FROM gateway_web_bindings "
                "WHERE conversation_uri=? AND owner=?", (self.client._conversation_uri, binding["owner"])).fetchone()
        if pinned is not None:
            for field, pinned_field in (("run_id", "run_id"), ("work_item_id", "work_item_id"), ("agent_id", "principal_id")):
                if binding.get(field) and binding[field] != pinned[pinned_field]:
                    raise PermissionError("Web authority differs from the conversation budget scope")
            binding = {**binding, "grant_id": pinned["grant_id"]}
        if not all(binding.get(field) for field in ("run_id", "work_item_id", "agent_id")):
            if pinned is None:
                raise PermissionError("Web conversation requires its existing central Run/WorkItem/agent binding")
            for field, pinned_field in (("run_id", "run_id"), ("work_item_id", "work_item_id"), ("agent_id", "principal_id")):
                if binding.get(field) and binding[field] != pinned[pinned_field]:
                    raise PermissionError("Web authority differs from the conversation budget scope")
            binding = {**binding, **dict(pinned), "agent_id": pinned["principal_id"]}
        from sentra_mcp.services.durable import DurableRunService
        durable = DurableRunService(self.store.telemetry_root)
        try:
            run = durable.run_status(binding["run_id"], binding["owner"], include_details=False)
            if run.get("workspace") != str(self.config.workspace):
                raise PermissionError("Web Run differs from the conversation workspace")
        finally:
            durable.close()
        auth = AuthorizationService(self.store.telemetry_root)
        grant = auth.require(binding["owner"], principal_type="agent", principal_id=binding["agent_id"],
            capability="web:send", scope_type="work_item", scope_id=binding["work_item_id"],
            context={"provider": "chatgpt"}, local_owner=False)
        if binding.get("grant_id") and grant["grant_id"] != binding["grant_id"]:
            raise PermissionError("Web conversation requires its original pinned grant")
        ok, detail = self.client._gateway_admin_post("/sentra/web-transport/bind", timeout=5,
            json_body={"conversation_uri": self.client._conversation_uri, "owner": binding["owner"],
                "run_id": binding["run_id"], "work_item_id": binding["work_item_id"],
                "principal_id": binding["agent_id"], "grant_id": grant["grant_id"]})
        if not ok:
            raise PermissionError("Authenticated Web authority binding unavailable: " + detail)

    def _usage(self,provider,ident,model,usage):
        if self._turn_id is None:raise RuntimeError("usage reported without an active turn")
        ledger=self._ledger()
        # Accounting retains the admitted submission even if its Grant was
        # revoked after I/O. This record does not authorize any further effect.
        context=self._recorded_provider_context(provider)
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
        self._restore_model_preferences()
        self.client.bind_conversation(self.session_id)
        self.client.active_model = self.config.model
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

    @staticmethod
    def orchestrate_stream(chunk_source, *, receipts=(), required=("coordinator",)):
        from .orchestrated_stream import orchestrate_stream
        return orchestrate_stream(
            chunk_source, receipts=receipts, required=required,
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
        observation = getattr(self, '_observation_provider', None)
        kwargs = {'observation_provider': observation} if operation.upper() == 'CANVAS' and raw_args == 'vm_frame' and observation else {}
        call, recorded = self.store.start_tool(self.session_id, self._turn_id, operation, raw_args, **kwargs)
        if recorded is not None:
            result = str(recorded)
            safe, frame = self._model_machine_result(operation, raw_args, result, call)
            if frame is not None:
                self._vm_frame = (call, frame)
            return "Recovered recorded result; no tool was executed again.\n" + safe
        previous_call = self._directive_call_id
        self._directive_call_id = call
        try:
            result = self._execute_directive(operation, raw_args)
            if operation.upper() == "CANVAS" and raw_args.partition("|")[0] in {"machine_execute","machine_observe","vm_frame","vm_input"}:
                result = self._machine_receipt(result)
        finally:
            self._directive_call_id = previous_call
        self.store.finish_tool(self.session_id, call, result)
        if operation.upper() == "CANVAS" and raw_args.partition("|")[0] in {"machine_execute", "machine_observe", "vm_frame", "vm_input"}:
            safe, frame = self._model_machine_result(operation, raw_args, result, call)
            if frame is not None:
                self._vm_frame = (call, frame)
            return safe
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
        self._model_checkpoint(self.client.active_provider)
        if self.canvas.is_shell_scope and op not in {'CANVAS', 'MEMORY'}:
            raise PermissionError('shell Dot effects use centrally admitted Canvas machine/coordinator calls')

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
            self._vm_frame = None
            self._observation_provider = None
            self.stream_receipts = ()
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
            self._attach_vm_frame(self.messages)
            # Stream visible prose incrementally, but never project an incomplete
            # [[TOOL|...]] directive into the user-visible response.
            parts: list[str] = []
            streamed = ""
            checkpoint = getattr(self.store, 'checkpoint_response', None)
            checkpoint_at, checkpoint_chars, response_chars = time.monotonic(), 0, 0
            try:
                for chunk in self.client.chat_stream(self.messages):
                    if not isinstance(chunk, str):
                        raise TypeError("provider stream must contain text")
                    parts.append(chunk)
                    response_chars += len(chunk)
                    if callable(checkpoint) and (response_chars - checkpoint_chars >= 4096 or time.monotonic() - checkpoint_at >= 1):
                        checkpoint(self.session_id, self._turn_id, ''.join(parts))
                        checkpoint_at, checkpoint_chars = time.monotonic(), response_chars
                    assembled = "".join(parts)
                    safe_prefix = prose_prefix(assembled)
                    safe_prefix = safe_prefix.lstrip()
                    if safe_prefix.startswith(streamed):
                        delta = safe_prefix[len(streamed):]
                        if delta:
                            streamed = safe_prefix
                            yield delta
            finally:
                # Consumer cancellation/transport errors also keep the last short
                # fragment. This is only a draft, never a completion receipt.
                if parts and callable(checkpoint):
                    checkpoint(self.session_id, self._turn_id, ''.join(parts))
            full_response = "".join(parts)
            if self.client.last_error:
                if callable(checkpoint):
                    checkpoint(self.session_id, self._turn_id, full_response)
                self.messages.append(self.store.append(self.session_id, "assistant", full_response, kind="provider_error"))
                state = "uncertain" if self.client.last_delivery_state == "uncertain" else "provider_error"
                self.store.end_turn(self.session_id, self._turn_id, state)
                # The provider error may already have been streamed; showing it
                # again used to duplicate the exact same error in the console.
                visible_error = prose_prefix(full_response, complete=True).lstrip()
                if not streamed:
                    if visible_error:
                        yield visible_error
                elif visible_error.startswith(streamed):
                    tail = visible_error[len(streamed):]
                    if tail:
                        yield tail
                return
            self.messages.append(self.store.finish_response(self.session_id, self._turn_id, full_response))

            directives = list(DIRECTIVE_RE.finditer(full_response))
            visible = prose_prefix(DIRECTIVE_RE.sub("", full_response), complete=True).strip()
            if not directives:
                self.store.end_turn(self.session_id, self._turn_id)
                # This names the committed response, not a multi-agent completion.
                self.stream_receipts = ("coordinator",)
            if visible:
                # Do not replay already streamed prose after a tool round.
                if visible.startswith(streamed):
                    remaining = visible[len(streamed):]
                elif streamed.rstrip() and visible.startswith(streamed.rstrip()):
                    # The completed transcript strips whitespace at its edges.
                    remaining = visible[len(streamed.rstrip()):]
                else:
                    remaining = "\n" + visible if streamed else visible
                if remaining:
                    yield remaining
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
                if op == 'CANVAS' and args == 'vm_frame':
                    # A new completed provider round may observe a changed
                    # desktop. Repeated writes retain their original identity.
                    fingerprint = (op, args, self._observation_provider)
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

    def _attach_vm_frame(self, messages):
        """Attach only this turn's latest validated frame to its tool observation."""
        current_frame = getattr(self, '_vm_frame', None)
        if current_frame is None:
            return
        call_id, image = current_frame
        marker = f"[SENTRA_VM_FRAME call_id={call_id}]"
        for message in reversed(messages):
            if isinstance(message, dict) and marker in str(message.get("content") or ""):
                message["images"] = [{key: image[key] for key in ("mime_type", "data_base64")}]
                return
