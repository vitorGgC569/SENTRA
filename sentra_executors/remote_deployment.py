"""Real provider deployment specifications, returned for host review only.

No daemon launch, shell interpolation, image pull, build, or implicit credentials.
Compose JSON is accepted by Docker Compose; versions/images must be host-pinned.
"""
from __future__ import annotations
import re
from pathlib import Path


def _image(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_./:-]+@sha256:[0-9a-f]{64}',value):
        raise ValueError('provider_image_digest_required')
    return value


def _host_path(value):
    path=Path(value)
    if not path.is_absolute():raise ValueError('absolute_provider_deployment_path_required')
    return str(path)


def guacd_compose(*,image,certificate_file,private_key_file,port=4822):
    """Pinned upstream guacd image, TLS and loopback-only published port."""
    if type(port) is not int or not 1<=port<=65535:raise ValueError('invalid_guacd_port')
    mounts=[{'type':'bind','source':_host_path(source),'target':target,'read_only':True}
        for source,target in ((certificate_file,'/run/guacd/server.crt'),(private_key_file,'/run/guacd/server.key'))]
    return {'services':{'sentra-guacd':{'image':_image(image),'init':True,'restart':'unless-stopped',
        'entrypoint':['/usr/local/sbin/guacd'],
        'command':['-f','-b','0.0.0.0','-l','4822','-L','warning','-C','/run/guacd/server.crt','-K','/run/guacd/server.key'],
        'ports':[f'127.0.0.1:{port}:4822/tcp'],'volumes':mounts,
        'security_opt':['no-new-privileges:true'],'cap_drop':['ALL']}}}


def guacd_native_command(*,executable,certificate_file,private_key_file,host='127.0.0.1',port=4822):
    if host not in {'127.0.0.1','::1'} or type(port) is not int or not 1<=port<=65535:
        raise ValueError('local_guacd_listener_required')
    return [_host_path(executable),'-f','-b',host,'-l',str(port),'-L','warning',
            '-C',_host_path(certificate_file),'-K',_host_path(private_key_file)]


def rustdesk_server_compose(*,image,data_directory,relay_address,bind_address):
    """Native OSS hbbs/hbbr, persistent keys; no web/proprietary RPC enabled.

    bind_address is an explicit Docker host interface, not an authorization rule.
    Both peers must be configured with its own server root key by the host.
    """
    import ipaddress
    address=ipaddress.ip_address(bind_address)
    published=f'[{bind_address}]' if address.version==6 else bind_address
    if not isinstance(relay_address,str) or not re.fullmatch(r'[A-Za-z0-9.:-]+',relay_address):
        raise ValueError('explicit_rustdesk_relay_address_required')
    image=_image(image)
    volume={'type':'bind','source':_host_path(data_directory),'target':'/root'}
    def service(command,ports):
        return {'image':image,'init':True,'command':command,'restart':'unless-stopped','volumes':[volume],
            'ports':[f'{published}:{p}:{p}/{protocol}' for p,protocol in ports]}
    # These are the documented OSS registration/NAT/relay ports, not a new
    # SENTRA protocol. Web client ports 21118/21119 aren't published.
    return {'services':{
        'sentra-hbbr':service(['hbbr'],[(21117,'tcp')]),
        'sentra-hbbs':dict(service(['hbbs','-r',relay_address],[(21115,'tcp'),(21116,'tcp'),(21116,'udp')]),
                           depends_on=['sentra-hbbr'])}}
