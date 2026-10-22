"""Human-readable projections; never accepted as operation authority."""
from pathlib import Path
import time


def present_access_request(row,root,dot):
    args=row['arguments'];command=args.get('command');target=Path(args.get('path') or args.get('cwd') or root)
    target=(root/target).resolve() if not target.is_absolute() else target.resolve()
    inside=target.is_relative_to(root)
    action=args.get('action')
    label='executar este comando' if command else 'excluir este arquivo' if action=='delete' else 'criar este arquivo' if action=='write' else 'editar este arquivo' if action=='edit' else 'consultar este caminho'
    expires=row.get('expires_at',row['created_at']+300)
    return {**row,'summary':{'title':dot['name']+' precisa '+label,
        'reason':row.get('reason') or 'Para continuar o trabalho desta conversa.',
        'target':str(target.relative_to(root)) if inside else str(target),
        'scope':'Comando no computador, iniciado neste diretório' if command else 'Somente esta ação neste caminho do projeto' if inside else 'Somente esta ação neste caminho fora do projeto',
        'expires_at':expires,'duration_seconds':300,'active':time.time()<expires,
        'command':command or None,'automatic_retry':False}}


def panel_hint(row,root):
    if row['capability_id'] not in {'computer:file.read','computer:file.write'}:return None
    target=Path(row['arguments'].get('path') or root);target=(root/target).resolve() if not target.is_absolute() else target.resolve()
    if not target.is_relative_to(root) or not target.is_file():return None
    relative=target.relative_to(root).as_posix()
    return {'kind':'files','resourceId':relative} if len(relative)<=128 else None
