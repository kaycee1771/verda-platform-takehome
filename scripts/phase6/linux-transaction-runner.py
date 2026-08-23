#!/usr/bin/env python3
"""Dormant Linux-native Phase 6 transaction-runner boundary; no effects."""
from __future__ import annotations
import hashlib,json,os,pathlib,re,stat,sys
from typing import Any,Callable
DIGEST=re.compile(r"^[0-9a-f]{64}$");COMMIT=re.compile(r"^[0-9a-f]{40}$")
MANIFEST_KEYS={"schema_version","reviewed_commit","files","broker_sha256","model_sha256","policy_sha256",
 "rollback_policy_sha256","terraform_lock_sha256","ansible_lock_sha256","runner_image","runner_image_digest",
 "clean_tree","execution_enabled","credential_files","raw_values_recorded"}
PINNED_IMAGE="verda-platform-quality@sha256:"+"0"*64
class RunnerRefused(ValueError):pass
def refuse(message:str)->None:raise RunnerRefused(message)
def canonical(v:Any)->bytes:return json.dumps(v,sort_keys=True,separators=(",", ":")).encode()
def digest(v:Any)->str:return hashlib.sha256(canonical(v)).hexdigest()
def hex64(v:Any,label:str)->str:
 if type(v) is not str or not DIGEST.fullmatch(v):refuse(f"{label} digest differs")
 return v

class LinuxRunnerBoundary:
 def __init__(self,*,platform:str=sys.platform,uid:int|None=None,config_home:pathlib.Path|None=None,
              state_home:pathlib.Path|None=None,stat_probe:Callable[[pathlib.Path],Any]=os.lstat)->None:
  if platform!="linux":refuse("Linux transaction runner is unavailable on this platform")
  self.uid=os.getuid() if uid is None else uid
  if type(self.uid) is not int or isinstance(self.uid,bool) or self.uid<0:refuse("runner UID differs")
  self.config_root=(config_home or pathlib.Path(os.environ.get("XDG_CONFIG_HOME",pathlib.Path.home()/".config")))/"verda"/"phase6"
  self.state_root=(state_home or pathlib.Path(os.environ.get("XDG_STATE_HOME",pathlib.Path.home()/".local/state")))/"verda"/"phase6"
  self.stat_probe=stat_probe
 def validate_roots(self)->None:
  for path in (self.config_root,self.state_root):
   if not path.is_absolute() or ".." in path.parts:refuse("runner control root is not canonical absolute")
   value=self.stat_probe(path)
   if not stat.S_ISDIR(value.st_mode) or stat.S_IMODE(value.st_mode)!=0o700 or value.st_uid!=self.uid or value.st_nlink<1:
    refuse("runner control root owner/mode/type differs")
 def validate_manifest(self,manifest:dict[str,Any],files:dict[str,bytes])->str:
  if not isinstance(manifest,dict) or set(manifest)!=MANIFEST_KEYS:refuse("runner archive manifest schema differs")
  if type(manifest["schema_version"]) is not int or manifest["schema_version"]!=1 or type(manifest["reviewed_commit"]) is not str or not COMMIT.fullmatch(manifest["reviewed_commit"]):refuse("runner archive identity differs")
  if manifest["clean_tree"] is not True or manifest["execution_enabled"] is not False or manifest["raw_values_recorded"] is not False or manifest["credential_files"]!=[]:refuse("runner archive is not clean inert and credential-free")
  if manifest["runner_image"]!=PINNED_IMAGE or manifest["runner_image_digest"]!="0"*64:refuse("runner image is not exact digest-pinned review image")
  if not isinstance(manifest["files"],dict) or set(manifest["files"])!=set(files):refuse("runner archive inventory differs")
  for path,raw in files.items():
   if type(path) is not str or path.startswith("/") or ".." in pathlib.PurePosixPath(path).parts or type(raw) is not bytes:refuse("runner archive path/bytes differ")
   if hex64(manifest["files"][path],"archive file")!=hashlib.sha256(raw).hexdigest():refuse("runner archive bytes differ")
  for key in ("broker_sha256","model_sha256","policy_sha256","rollback_policy_sha256","terraform_lock_sha256","ansible_lock_sha256"):hex64(manifest[key],key)
  return digest(manifest)

def main()->int:
 print("REFUSED: dormant Linux Phase 6 runner has no prepare, apply, recovery, or rollback route",file=sys.stderr);return 64
if __name__=="__main__":raise SystemExit(main())
