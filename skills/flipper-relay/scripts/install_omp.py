#!/usr/bin/env python3
"""Copy this complete skill into OMP, preserving an existing copy first."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import uuid


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination',type=Path,default=Path.home()/'.omp/agent/skills/flipper-relay')
    args=parser.parse_args()
    source=Path(__file__).resolve().parents[1]
    destination=args.destination.expanduser().absolute()
    if destination.resolve()==source:
        print(json.dumps({'installed':str(destination),'changed':False}))
        return
    if source in destination.resolve().parents or destination.resolve() in source.parents:
        parser.error('Source and destination must not contain one another')
    if destination.is_symlink():
        parser.error('Refusing a symlink destination; inspect the existing installation')
    backup=None
    destination.parent.mkdir(parents=True,exist_ok=True)
    staging=destination.parent/('.flipper-relay-install-'+uuid.uuid4().hex)
    try:
        shutil.copytree(source,staging,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        if destination.exists():
            backup_root=destination.parent.parent/'skill-backups'
            backup_root.mkdir(parents=True,exist_ok=True)
            backup=backup_root/('flipper-relay-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8])
            destination.replace(backup)
        try:
            staging.replace(destination)
        except OSError:
            if backup is not None and not destination.exists():
                backup.replace(destination)
            raise
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    print(json.dumps({'installed':str(destination),'backup':str(backup) if backup else None,
                      'mcp_config_changed':False,'service_changed':False},indent=2))


if __name__=='__main__':
    main()
