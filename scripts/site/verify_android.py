"""Check public apksigner/aapt reports against the preserved preview identity."""
from pathlib import Path
import argparse,hashlib,json,re

ROOT=Path(__file__).resolve().parents[2]


def verify(apk,signing_report,badging_report,run,policy):
    signers=re.findall(r'^Signer #\d+ certificate SHA-256 digest: ([a-fA-F0-9]{64})\s*$',signing_report,re.MULTILINE)
    if len(signers)!=1 or signers[0].lower()!=policy['certificate_sha256']:
        raise ValueError('Android preview signing identity differs from the preserved key')
    package=re.search(r"^package: name='([^']+)' versionCode='([0-9]+)'",badging_report,re.MULTILINE)
    if not package or package[1]!=policy['package'] or int(package[2])!=int(run) or int(run)<policy['minimum_version_code']:
        raise ValueError('Android package/versionCode does not match the approved preview update')
    return {'schema':1,'apk_sha256':hashlib.sha256(apk.read_bytes()).hexdigest(),
            'certificate_sha256':signers[0].lower(),'package':package[1],'version_code':int(package[2])}


if __name__=='__main__':
    parser=argparse.ArgumentParser(__doc__)
    for name in ('apk','signature','badging','policy','out'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--run',type=int,required=True);args=parser.parse_args()
    value=verify(args.apk,args.signature.read_text(),args.badging.read_text(),args.run,json.loads(args.policy.read_text()))
    args.out.write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')
