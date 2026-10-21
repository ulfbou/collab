"""Deterministic, read-only normalization of identity-bound source material."""
from __future__ import annotations
import hashlib,json,re
from dataclasses import dataclass
from typing import Any,Mapping,Sequence
from .development_intent import Diagnostic
OBLIGATION_SET_SCHEMA="collab/obligation-set/v1"; OBLIGATION_NORMALIZATION_VERSION="1"
CID=re.compile(r"^sha256:(?:[0-9a-f]{64}|[a-z-]+:v1:[0-9a-f]{64})$")
ROLES={"change-authorization","durable-authority","observed-evidence"}; KINDS={"issue","operational-authorization","policy","contract","schema","decision","documentation","repository-observation"}; VK={"command","schema","inspection","comparison","hosted-query"}
@dataclass(frozen=True)
class ObligationNormalizationResult:
 status:str; value:Mapping[str,Any]|None; diagnostics:tuple[Diagnostic,...]
 @property
 def valid(self):return self.status=="normalized"
def canon(v):return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()
def ident(d,v):return f"sha256:{d}:v1:{hashlib.sha256(canon(v)).hexdigest()}"
def diag(c,p,m):return Diagnostic(c,p,m)
def strings(v,nonempty=True):
 if not isinstance(v,list) or any(not isinstance(x,str) or not x.strip() for x in v):return None
 r=sorted(set(x.strip() for x in v));return r if r or not nonempty else None
def source(v):
 keys={"role","sourceKind","sourceId","location","contentIdentity"}
 if not isinstance(v,Mapping) or set(v)!=keys or v.get("role") not in ROLES or v.get("sourceKind") not in KINDS:return None
 if any(not isinstance(v.get(k),str) or not v[k].strip() for k in ("sourceId","location")) or not isinstance(v.get("contentIdentity"),str) or not CID.fullmatch(v["contentIdentity"]):return None
 return {k:v[k].strip() for k in ("role","sourceKind","sourceId","location","contentIdentity")}
def verification(v):
 keys={"kind","target","successCondition","requiredCapabilities","mutating"}
 if not isinstance(v,Mapping) or set(v)!=keys or v.get("kind") not in VK or v.get("mutating") is not False:return None
 if any(not isinstance(v.get(k),str) or not v[k].strip() for k in ("target","successCondition")):return None
 caps=strings(v.get("requiredCapabilities"),False)
 if caps is None:return None
 return {"kind":v["kind"],"target":v["target"].strip(),"successCondition":v["successCondition"].strip(),"requiredCapabilities":caps,"mutating":False}
def valid_intent(v):return isinstance(v,Mapping) and v.get("schema")=="collab/development-intent/v1" and v.get("normalizationVersion")=="1" and re.fullmatch(r"sha256:development-intent:v1:[0-9a-f]{64}",str(v.get("intentId",""))) and isinstance(v.get("provenance"),list) and isinstance(v.get("limitations"),list)
def valid_authority(v):
 keys=("authoritySetId","status","declaredAuthorities","resolvedAuthorities","invalidDeclarations","absentDeclarations","incompleteEvidence","conflicts","provenance","limitations")
 return isinstance(v,Mapping) and all(k in v for k in keys) and re.fullmatch(r"sha256:authority-set:v1:[0-9a-f]{64}",str(v.get("authoritySetId",""))) and v.get("status") in {"resolved","incomplete","conflicted"} and all(isinstance(v[k],list) for k in keys[2:])
def authorized(s,i,a):
 if s["role"]=="change-authorization":
  ids={x.get("identity") for x in i["provenance"] if isinstance(x,Mapping)}|{i.get("source",{}).get("contentIdentity")};return s["contentIdentity"] in ids
 if s["role"]=="durable-authority":return any(isinstance(x,Mapping) and x.get("contentIdentity")==s["contentIdentity"] and x.get("kind")==s["sourceKind"] and x.get("path")==s["location"] for x in a["resolvedAuthorities"])
 return False
def normalize_obligation_set(development_intent,authority_set,source_material):
 """Normalize bounded sources without executing verification or inferring precedence."""
 ds=[]
 if not valid_intent(development_intent):ds.append(diag("invalid_development_intent","$.developmentIntent","Development Intent is invalid"))
 if not valid_authority(authority_set):ds.append(diag("invalid_authority_set","$.authoritySet","AuthoritySet is invalid"))
 if ds:return ObligationNormalizationResult("invalid",None,tuple(ds))
 if development_intent.get("authoritySetId")!=authority_set["authoritySetId"]:return ObligationNormalizationResult("invalid",None,(diag("authority_set_mismatch","$.developmentIntent.authoritySetId","AuthoritySet identities differ"),))
 if not isinstance(source_material,Sequence) or isinstance(source_material,(str,bytes,bytearray)):return ObligationNormalizationResult("invalid",None,(diag("invalid_source_material","$.sourceMaterial","Source material must be an array"),))
 obs=[];inc=[];prov=[]
 for i,d in enumerate(source_material):
  path=f"$.sourceMaterial[{i}]"
  if not isinstance(d,Mapping) or set(d)!={"source","requirements"}:return ObligationNormalizationResult("invalid",None,(diag("invalid_source_material",path,"source and requirements are required"),))
  s=source(d["source"])
  if s is None or not isinstance(d["requirements"],list):return ObligationNormalizationResult("invalid",None,(diag("invalid_source_material",path,"Source binding is invalid"),))
  prov.append(s);auth=authorized(s,development_intent,authority_set)
  for j,r in enumerate(d["requirements"]):
   if not isinstance(r,Mapping) or not isinstance(r.get("sourceRequirementId"),str) or not r["sourceRequirementId"].strip():return ObligationNormalizationResult("invalid",None,(diag("missing_source_requirement_id",f"{path}.requirements[{j}]","sourceRequirementId is required"),))
   rid=r["sourceRequirementId"].strip();missing=[];st=r.get("statement");scope=strings(r.get("affectedScope"));ev=strings(r.get("requiredEvidence"));ver=verification(r.get("verification"));lim=strings(r.get("limitations"),False)
   if not isinstance(st,str) or not st.strip():missing.append("statement")
   if scope is None:missing.append("affectedScope")
   if ev is None:missing.append("requiredEvidence")
   if ver is None:missing.append("verification")
   if lim is None:missing.append("limitations")
   if not auth:missing.append("authoritativeSource")
   if missing:
    x={"sourceRequirementId":rid,"sourceRef":s,"missingFields":sorted(missing),"limitations":lim or []};x["incompleteObligationId"]=ident("incomplete-obligation",x);inc.append(x)
   else:
    x={"sourceRequirementId":rid,"sourceRef":s,"statement":st.strip(),"affectedScope":scope,"requiredEvidence":ev,"verification":ver,"limitations":lim};obs.append({"obligationId":ident("obligation",x),**x,"completionState":"unverified"})
 conflicts=[]
 for c in authority_set["conflicts"]:
  x={"origin":"authority-set","authoritySetId":authority_set["authoritySetId"],"upstreamConflict":c,"resolution":"unresolved","precedence":"not-inferred"};conflicts.append({"conflictId":ident("obligation-conflict",x),**x})
 obs.sort(key=lambda x:x["obligationId"]);inc.sort(key=lambda x:x["incompleteObligationId"]);conflicts.sort(key=lambda x:x["conflictId"]);prov=sorted({json.dumps(x,sort_keys=True):x for x in prov}.values(),key=canon)
 status="conflicted" if conflicts else "incomplete" if inc or authority_set["status"]!="resolved" else "normalized"
 out={"schema":OBLIGATION_SET_SCHEMA,"normalizationVersion":OBLIGATION_NORMALIZATION_VERSION,"intentId":development_intent["intentId"],"authoritySetId":authority_set["authoritySetId"],"status":status,"provenance":prov,"obligations":obs,"incompleteObligations":inc,"conflicts":conflicts,"limitations":sorted(set(development_intent["limitations"]+authority_set["limitations"])),"verificationExecuted":False,"acceptanceDecision":"not-performed"};out["obligationSetId"]=ident("obligation-set",out)
 return ObligationNormalizationResult(status,out,())
