"""Bounded, credential-free messages shared by native Setup and its worker."""

MESSAGES = {
    "destination_unowned": (
        "A pasta contém arquivos sem identificação válida de propriedade. Escolha uma pasta exclusiva vazia ou revise os arquivos existentes; componentes sem propriedade comprovada não serão substituídos.",
        "The destination contains files without valid installation ownership. Choose an empty dedicated folder or review the existing files; components without proven ownership will not be replaced."),
    "marker_invalid": (
        "A identificação da instalação anterior está danificada. Os arquivos existentes serão preservados; escolha uma pasta exclusiva se a propriedade dos componentes não puder ser comprovada.",
        "The previous installation marker is damaged. Existing files will be preserved; choose a dedicated folder if ownership of the components cannot be established."),
    "active_installation": (
        "O SENTRA ainda está em execução. Feche o aplicativo e conclua suas sessões antes de tentar novamente. O instalador preservou os processos ativos.",
        "SENTRA is still running. Close the application and finish its sessions before retrying. Setup preserved the active processes."),
    "settings_invalid": (
        "As configurações locais estão danificadas ou incompatíveis. Selecione Recuperar configurações danificadas ou Instalação limpa. O arquivo original será guardado e o acesso local voltará ao modo Seguro; projetos e contas serão preservados.",
        "Local settings are damaged or incompatible. Select Recover damaged settings or Clean installation. The original file will be backed up and local access will use Safe mode; projects and accounts will be preserved."),
    "port_conflict": (
        "A porta local configurada já está sendo usada por outro serviço ou outra instância do SENTRA. Feche a instância anterior ou configure outra porta e tente novamente. Nenhum processo desconhecido foi encerrado.",
        "The configured local port is occupied by another service or SENTRA instance. Close the earlier instance or configure another port and retry. No unknown process was terminated."),
    "display_not_ready": (
        "A interface instalada não conseguiu iniciar. Consulte a verificação de interface em installer-last-run.json e os logs na pasta de dados do SENTRA.",
        "The installed interface could not start. Review the display check in installer-last-run.json and the logs in the SENTRA state folder."),
    "mcp_not_ready": (
        "O serviço local do SENTRA não ficou pronto. Consulte a verificação MCP em installer-last-run.json e os logs na pasta de dados; login no ChatGPT é uma etapa posterior.",
        "The SENTRA local service did not become ready. Review the MCP check in installer-last-run.json and the state-folder logs; ChatGPT login is a later step."),
    "unsafe_clean_destination": (
        "Esta pasta não pode ser usada para instalação limpa. Escolha uma pasta exclusiva do aplicativo, fora de diretórios de sistema, projetos Git e links de diretório.",
        "This folder cannot be used for clean installation. Choose a dedicated application folder outside system directories, Git projects and directory links."),
    "unowned_clean_conflict": (
        "Um arquivo existente não pertence a uma instalação SENTRA identificada e seria substituído. Ele foi preservado. Escolha uma pasta exclusiva para o aplicativo ou mova o arquivo por conta própria antes de tentar novamente.",
        "An existing file is not owned by an identified SENTRA installation and would be replaced. It was preserved. Choose a dedicated application folder or move the file yourself before retrying."),
    "shortcut_failed": (
        "O Windows impediu a criação do acesso ao SENTRA. Verifique o acesso à Área de Trabalho e ao menu Iniciar. Arquivos antigos não identificados foram preservados.",
        "Windows prevented creating the SENTRA launcher. Check Desktop and Start Menu access. Unidentified old files were preserved."),
    "payload_incomplete": (
        "Os componentes do instalador estão incompletos ou falharam na verificação. Baixe e verifique novamente todas as partes desta mesma versão.",
        "Installer components are incomplete or failed verification. Download and verify all parts of this same release again."),
    "access_denied": (
        "O Windows negou acesso a um arquivo ou pasta. Use o destino sugerido no seu perfil e verifique as permissões; os dados anteriores foram preservados.",
        "Windows denied access to a file or folder. Use the suggested location in your profile and check permissions; previous data was preserved."),
    "installation_failed": (
        "A configuração não foi concluída. Consulte installer-last-run.json e installer-error.json na pasta de dados do SENTRA antes de tentar novamente.",
        "Configuration did not finish. Review installer-last-run.json and installer-error.json in the SENTRA state folder before retrying."),
}


def diagnose(result, code):
    if code == 0:
        return None
    reason = result.get("failure_reason")
    text = str(result.get("message") or "").lower()
    if reason not in MESSAGES:
        if "without sentra ownership" in text:
            reason = "destination_unowned"
        elif "install marker" in text:
            reason = "marker_invalid"
        elif "installed process" in text or "another installation operation" in text:
            reason = "active_installation"
        elif result.get("error_type") == "ShortcutRegistrationError":
            reason = "shortcut_failed"
        elif result.get("error_type") == "PermissionError":
            reason = "access_denied"
        elif "payload" in text or "checksum" in text or "sha-256 mismatch" in text:
            reason = "payload_incomplete"
        else:
            verification = result.get("connect_verify") or {}
            started = verification.get("started") or {}
            status = verification.get("status") or {}
            mcp_reason = (started.get("mcp") or {}).get("reason")
            if mcp_reason in {"port_in_use_by_unmanaged_process", "port_in_use_by_different_instance", "mcp_restart_port_still_in_use"}:
                reason = "port_conflict"
            elif verification.get("display_required") and (status.get("display") or {}).get("ok") is not True:
                reason = "display_not_ready"
            elif "core_ready" in verification and not verification["core_ready"]:
                reason = "mcp_not_ready"
            else:
                reason = "installation_failed"
    return {"reason": reason, "message_pt": MESSAGES[reason][0], "message_en": MESSAGES[reason][1]}
