#!/usr/bin/env python3
"""Dormant Linux-native Phase 6 transaction-runner boundary; no effects."""
from __future__ import annotations
import hashlib,json,os,pathlib,re,stat,subprocess,sys
from typing import Any,Callable
DIGEST=re.compile(r"^[0-9a-f]{64}$");COMMIT=re.compile(r"^[0-9a-f]{40}$")
MANIFEST_KEYS={"schema_version","reviewed_commit","files","model_sha256","journal_schema_sha256","verifier_sha256",
 "runner_sha256","policy_sha256","rollback_policy_sha256","versions_lock_sha256","terraform_lock_sha256",
 "provider_lock_sha256","ansible_lock_sha256","runner_image","runner_image_digest","quality_image_id",
 "clean_tree","execution_enabled","credential_files","raw_values_recorded"}
PINNED_IMAGE="verda-platform-quality:phase1-2026-08-16"
PINNED_IMAGE_DIGEST="c7cc28ef4c3817a54926e4bce20068e101cac997e03428177262a7421ef809f8"
QUALITY_IMAGE_ID="sha256:"+PINNED_IMAGE_DIGEST
PRODUCTION_UID=65532
ARCHIVE_PATHS={
 "scripts/phase6/transaction-broker-model.py":"model_sha256",
 "schemas/phase6-transaction-journal-v2.schema.json":"journal_schema_sha256",
 "scripts/phase6/verify-github-authorization.py":"verifier_sha256",
 "scripts/phase6/linux-transaction-runner.py":"runner_sha256",
 "config/phase6-transaction-broker-policy.json":"policy_sha256",
 "config/phase6-transaction-rollback-policy.json":"rollback_policy_sha256",
 "versions.lock.yaml":"versions_lock_sha256",
 "infra/terraform/environments/management/.terraform.lock.hcl":"terraform_lock_sha256",
 "infra/terraform/provider-discovery/.terraform.lock.hcl":"provider_lock_sha256",
 "infra/ansible/requirements.yml":"ansible_lock_sha256",
}
FORBIDDEN=re.compile(r"(^|/)(\.ssh|.*(?:secret|private[-_]?key|id_ed25519|tfstate|\.pem))(?:$|/)",re.I)
class RunnerRefused(ValueError):pass
def refuse(message:str)->None:raise RunnerRefused(message)
def canonical(v:Any)->bytes:return json.dumps(v,sort_keys=True,separators=(",", ":")).encode()
def digest(v:Any)->str:return hashlib.sha256(canonical(v)).hexdigest()
def hex64(v:Any,label:str)->str:
 if type(v) is not str or not DIGEST.fullmatch(v):refuse(f"{label} digest differs")
 return v

def _validate_roots(paths:tuple[pathlib.Path,pathlib.Path],uid:int,stat_probe:Callable[[pathlib.Path],Any])->None:
 if paths[0]==paths[1]:refuse("runner config and state roots are not distinct")
 identities=[]
 for path in paths:
  if not path.is_absolute() or ".." in path.parts:refuse("runner control root is not canonical absolute")
  for ancestor in reversed(path.parents):
   info=stat_probe(ancestor)
   if not stat.S_ISDIR(info.st_mode) or info.st_uid not in {0,uid} or stat.S_IMODE(info.st_mode)&0o022:refuse("runner ancestor owner/type/writability differs")
  value=stat_probe(path)
  if not stat.S_ISDIR(value.st_mode) or stat.S_IMODE(value.st_mode)!=0o700 or value.st_uid!=uid or value.st_nlink<1:refuse("runner control root owner/mode/type differs")
  identities.append((value.st_dev,value.st_ino))
 if identities[0]==identities[1]:refuse("runner config/state roots alias the same inode")

def _validate_manifest_payload(manifest:dict[str,Any],files:dict[str,bytes],metadata:dict[str,Any],uid:int)->str:
 if not isinstance(manifest,dict) or set(manifest)!=MANIFEST_KEYS:refuse("runner archive manifest schema differs")
 if type(manifest["schema_version"]) is not int or manifest["schema_version"]!=1 or type(manifest["reviewed_commit"]) is not str or not COMMIT.fullmatch(manifest["reviewed_commit"]):refuse("runner archive identity differs")
 if manifest["clean_tree"] is not True or manifest["execution_enabled"] is not False or manifest["raw_values_recorded"] is not False or manifest["credential_files"]!=[]:refuse("runner archive is not clean inert and credential-free")
 if manifest["runner_image"]!=PINNED_IMAGE or manifest["runner_image_digest"]!=PINNED_IMAGE_DIGEST or manifest["quality_image_id"]!=QUALITY_IMAGE_ID:refuse("runner image is not exact reviewed quality image")
 allowed=set(ARCHIVE_PATHS)
 if not isinstance(manifest["files"],dict) or set(manifest["files"])!=allowed or set(files)!=allowed or set(metadata)!=allowed:refuse("runner archive inventory differs")
 for path,raw in files.items():
  normalized=pathlib.PurePosixPath(path);info=metadata[path]
  if type(path) is not str or path.startswith("/") or str(normalized)!=path or ".." in normalized.parts or FORBIDDEN.search(path) or type(raw) is not bytes:refuse("runner archive path/bytes differ")
  if hex64(manifest["files"][path],"archive file")!=hashlib.sha256(raw).hexdigest():refuse("runner archive bytes differ")
  if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) not in {0o444,0o644} or info.st_nlink!=1 or info.st_uid!=uid:refuse("runner archive file metadata differs")
 for path,key in ARCHIVE_PATHS.items():
  if hex64(manifest[key],key)!=manifest["files"][path]:refuse("runner semantic hash differs from archive inventory")
 lock=files["versions.lock.yaml"].decode("utf-8",errors="strict")
 if f'quality_image: "{PINNED_IMAGE}"' not in lock or f'quality_image_id: "{QUALITY_IMAGE_ID}"' not in lock:refuse("versions lock quality image binding differs")
 return digest(manifest)

class LinuxRunnerBoundary:
 def __init__(self)->None:
  if sys.platform!="linux":refuse("Linux transaction runner is unavailable on this platform")
  self.uid=os.geteuid()
  if self.uid!=PRODUCTION_UID:refuse("production runner UID differs")
  config_home=pathlib.Path(os.environ.get("XDG_CONFIG_HOME",pathlib.Path.home()/".config"))
  state_home=pathlib.Path(os.environ.get("XDG_STATE_HOME",pathlib.Path.home()/".local/state"))
  if type(self.uid) is not int or isinstance(self.uid,bool) or self.uid<0:refuse("runner UID differs")
  self.config_root=config_home/"verda"/"phase6";self.state_root=state_home/"verda"/"phase6"
  self.repo_root=pathlib.Path(__file__).resolve().parents[2];self._fds:list[int]=[];self._used=False
 def __enter__(self):
  if self._used or self._fds:refuse("runner boundary context is one-shot")
  self._used=True
  self.validate_roots();return self
 def __exit__(self,*_):
  while self._fds:os.close(self._fds.pop())
 def validate_roots(self)->None:
  if self._fds:refuse("runner root handles are already retained")
  _validate_roots((self.config_root,self.state_root),self.uid,os.lstat)
  identities=[]
  for path in (self.config_root,self.state_root):
   before=os.lstat(path);fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW);held=os.fstat(fd)
   if (held.st_dev,held.st_ino)!=(before.st_dev,before.st_ino):os.close(fd);refuse("runner root identity changed during no-follow open")
   self._fds.append(fd);identities.append((held.st_dev,held.st_ino))
  if identities[0]==identities[1]:refuse("held runner roots alias the same inode")
 def validate_manifest(self,manifest:dict[str,Any])->str:
  files={};metadata={}
  for relative in ARCHIVE_PATHS:
   target=self.repo_root/pathlib.PurePosixPath(relative);fd=os.open(target,os.O_RDONLY|os.O_NOFOLLOW);before=os.fstat(fd)
   chunks=[]
   while True:
    chunk=os.read(fd,65536)
    if not chunk:break
    chunks.append(chunk)
   after=os.fstat(fd)
   if (before.st_dev,before.st_ino,before.st_size)!=(after.st_dev,after.st_ino,after.st_size):os.close(fd);refuse("runner archive file identity changed")
   self._fds.append(fd);files[relative]=b"".join(chunks);metadata[relative]=after
  return _validate_manifest_payload(manifest,files,metadata,self.uid)
 def validate_reviewed_commit(self,manifest:dict[str,Any])->None:
  try:
   git=os.lstat("/usr/bin/git")
   if not stat.S_ISREG(git.st_mode) or git.st_uid!=0 or stat.S_IMODE(git.st_mode)&0o022:refuse("fixed git executable trust differs")
   env={"PATH":"/usr/bin:/bin","HOME":"/nonexistent","LANG":"C.UTF-8","GIT_CONFIG_NOSYSTEM":"1","GIT_CONFIG_GLOBAL":"/dev/null"}
   command=["/usr/bin/git","-c",f"safe.directory={self.repo_root}","-C",str(self.repo_root)]
   result=subprocess.run(command+["status","--porcelain=v1"],capture_output=True,check=False,env=env)
   head=subprocess.run(command+["rev-parse","HEAD"],capture_output=True,check=False,text=True,env=env)
  except OSError as error:refuse(f"fixed git verification unavailable: {error.__class__.__name__}")
  if result.returncode!=0 or result.stdout or head.returncode!=0 or manifest.get("reviewed_commit")!=head.stdout.strip():
   refuse("runner archive is not bound to the exact clean reviewed HEAD")

def main()->int:
 print("REFUSED: dormant Linux Phase 6 runner has no prepare, apply, recovery, or rollback route",file=sys.stderr);return 64
if __name__=="__main__":raise SystemExit(main())
