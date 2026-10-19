#!/usr/bin/env python3
import argparse,json
from pathlib import Path
from collab.observations import HostedQuery,HostedRepositoryCollector,observe_local_repository
p=argparse.ArgumentParser(); p.add_argument('--repository'); p.add_argument('--local-only',action='store_true'); p.add_argument('--query-kind',choices=('issue','pr','milestone','branch','commit')); p.add_argument('--query-value'); a=p.parse_args()
if bool(a.query_kind)!=bool(a.query_value): p.error('--query-kind and --query-value must be supplied together')
local=observe_local_repository(Path.cwd()); value={'schemaVersion':'1.0','local':local,'hosted':None}
if not a.local_only:
    q=HostedQuery(a.query_kind,a.query_value) if a.query_kind else None
    value['hosted']=HostedRepositoryCollector(a.repository or local['repository']).collect(q)
print(json.dumps(value,sort_keys=True,indent=2))
