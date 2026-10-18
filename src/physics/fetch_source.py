"""Download the exact reviewed physics graph without replacing another file."""
from __future__ import annotations
import argparse
import hashlib
import os
import tempfile
from pathlib import Path
from urllib.request import urlopen

from .engine import ROOT, RuleError, read_json


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'data/raw/physics/physics.json')
    args=parser.parse_args()
    source=read_json(ROOT/'knowledge/physics/source.json')
    if args.output.exists():
        if hashlib.sha256(args.output.read_bytes()).hexdigest()!=source['sha256']:
            raise RuleError('existing file differs from pinned source; choose a new output path')
        print(f'Verified existing source: {args.output}')
        return
    with urlopen(source['url'],timeout=60) as response:
        raw=response.read()
    if hashlib.sha256(raw).hexdigest()!=source['sha256']:
        raise RuleError('download checksum mismatch')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    # Complete the download and checksum before exposing the destination.
    with tempfile.NamedTemporaryFile(dir=args.output.parent,delete=False) as f:
        f.write(raw)
        temp=Path(f.name)
    try:
        # link is atomic and refuses to overwrite an existing destination.
        os.link(temp,args.output)
    finally:
        temp.unlink()
    print(f'Downloaded verified source: {args.output}')


if __name__=='__main__':main()
