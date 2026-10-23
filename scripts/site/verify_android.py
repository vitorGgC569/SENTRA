"""Check public apksigner/aapt reports against the preserved preview identity."""
from pathlib import Path
import argparse,hashlib,json,re

ROOT=Path(__file__).resolve().parents[2]


def certificate_identity(report):
    """Accept one pinned identity across apksigner's numbered or SDK labels.

    V3.1 prints SDK ranges instead of ``Signer #1``. Android's implementation:
    https://android.googlesource.com/platform/tools/apksig/+/master/src/apksigner/java/com/android/apksigner/ApkSignerTool.java
    """
    rows=[line for line in report.splitlines() if re.match(r'^(?:Signer |V[123](?:\.1)? Signer:)',line) and ' certificate SHA-256 digest:' in line]
    counts=re.findall(r'^Number of signers: ([0-9]+)\s*$',report,re.MULTILINE)
    if counts and counts!=['1']:raise ValueError('Exactly one APK signer required')
    # Current Android build-tools label the verified scheme directly. Require
    # the reported single signer and identical certificates in every scheme.
    if rows and all(re.fullmatch(r'V[123](?:\.1)? Signer: certificate SHA-256 digest: [a-fA-F0-9]{64}\s*',row) for row in rows):
        labels=[row.split(' certificate ',1)[0] for row in rows]
        identities={row.rsplit(': ',1)[1].strip().lower() for row in rows}
        if counts!=['1'] or len(rows)>4 or len(set(labels))!=len(labels) or len(identities)!=1:
            raise ValueError('Ambiguous APK scheme signing identity')
        return next(iter(identities))
    if len(rows)==1:
        numbered=re.fullmatch(r'Signer #1 certificate SHA-256 digest: ([a-fA-F0-9]{64})\s*',rows[0])
        if numbered:return numbered[1].lower()
    # A v3.1 report must announce one signer and expose the same identity in
    # every nonoverlapping API range. A key rotation to another key is refused.
    if counts!=['1'] or not 1<=len(rows)<=8:raise ValueError('Unrecognized APK signer report')
    ranges=[];identities=set()
    for row in rows:
        sdk=re.fullmatch(r'Signer \(minSdkVersion=([0-9]+)(?: \(dev release=true\))?, maxSdkVersion=([0-9]+)\) certificate SHA-256 digest: ([a-fA-F0-9]{64})\s*',row)
        if not sdk:raise ValueError('Mixed or unknown APK signer labels')
        low,high=int(sdk[1]),int(sdk[2])
        if not 1<=low<=high<=2147483647:raise ValueError('Invalid APK signer SDK range')
        ranges.append((low,high));identities.add(sdk[3].lower())
    ranges.sort()
    if len(identities)!=1 or any(left[1]>=right[0] for left,right in zip(ranges,ranges[1:])):
        raise ValueError('Ambiguous APK signing identity')
    return next(iter(identities))


def verify(apk,signing_report,badging_report,run,policy):
    try:identity=certificate_identity(signing_report)
    except ValueError:identity=None
    if identity!=policy['certificate_sha256']:
        # Certificate digests are public. Retain a useful diagnostic without
        # exposing a keystore, password, alias or private signing material.
        reported=re.findall(r'certificate SHA-256 digest:\s*([a-fA-F0-9]{64})',signing_report)
        raise ValueError('Android preview signing identity differs from the preserved key; '
                         +json.dumps({'parsed_identity':identity,'public_certificate_sha256':reported}))
    package=re.search(r"^package: name='([^']+)' versionCode='([0-9]+)'",badging_report,re.MULTILINE)
    if not package or package[1]!=policy['package'] or int(package[2])!=int(run) or int(run)<policy['minimum_version_code']:
        raise ValueError('Android package/versionCode does not match the approved preview update')
    return {'schema':1,'apk_sha256':hashlib.sha256(apk.read_bytes()).hexdigest(),
            'certificate_sha256':identity,'package':package[1],'version_code':int(package[2])}


if __name__=='__main__':
    parser=argparse.ArgumentParser(__doc__)
    for name in ('apk','signature','badging','policy','out'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--run',type=int,required=True);args=parser.parse_args()
    value=verify(args.apk,args.signature.read_text(),args.badging.read_text(),args.run,json.loads(args.policy.read_text()))
    args.out.write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')
