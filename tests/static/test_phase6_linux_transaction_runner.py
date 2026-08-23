import hashlib,importlib.util,pathlib,stat,subprocess,sys,types,unittest
from unittest import mock
ROOT=pathlib.Path(__file__).parents[2];PATH=ROOT/"scripts/phase6/linux-transaction-runner.py"
s=importlib.util.spec_from_file_location("linux_runner",PATH);M=importlib.util.module_from_spec(s);s.loader.exec_module(M)
def h(v):return hashlib.sha256(v).hexdigest()
def manifest(files):
 value={"schema_version":1,"reviewed_commit":"a"*40,"files":{k:h(v) for k,v in files.items()},"runner_image":M.PINNED_IMAGE,"runner_image_digest":M.PINNED_IMAGE_DIGEST,"quality_image_id":M.QUALITY_IMAGE_ID,"clean_tree":True,"execution_enabled":False,"credential_files":[],"raw_values_recorded":False}
 value.update({field:value["files"][path] for path,field in M.ARCHIVE_PATHS.items()});return value
class LinuxRunnerTests(unittest.TestCase):
 def test_direct_refuses_and_contains_no_effect_route(self):
  self.assertEqual(subprocess.run([sys.executable,str(PATH)],capture_output=True).returncode,64)
  source=PATH.read_text()
  for token in ("terraform apply","ansible-playbook","kubectl","requests","socket"):self.assertNotIn(token,source)
 def test_platform_and_exact_xdg_roots(self):
  if sys.platform!="linux":
   with self.assertRaises(M.RunnerRefused):M.LinuxRunnerBoundary()
  good=lambda p:types.SimpleNamespace(st_mode=stat.S_IFDIR|0o700,st_uid=1000,st_nlink=2,st_dev=1,st_ino=hash(str(p)))
  M._validate_roots((pathlib.PurePosixPath("/control/config/verda/phase6"),pathlib.PurePosixPath("/control/state/verda/phase6")),1000,good)
  bad=lambda p:types.SimpleNamespace(st_mode=stat.S_IFDIR|0o755,st_uid=1000,st_nlink=2,st_dev=1,st_ino=hash(str(p)))
  with self.assertRaises(M.RunnerRefused):M._validate_roots((pathlib.PurePosixPath("/c/verda/phase6"),pathlib.PurePosixPath("/s/verda/phase6")),1000,bad)
 def test_credential_free_archive_and_tamper(self):
  files={path:path.encode() for path in M.ARCHIVE_PATHS};files["versions.lock.yaml"]=(f'quality_image: "{M.PINNED_IMAGE}"\nquality_image_id: "{M.QUALITY_IMAGE_ID}"\n').encode()
  metadata={path:types.SimpleNamespace(st_mode=stat.S_IFREG|0o444,st_uid=1000,st_nlink=1) for path in files}
  value=manifest(files);M._validate_manifest_payload(value,files,metadata,1000)
  tampered=dict(files);tampered[next(iter(files))]=b"tampered"
  with self.assertRaises(M.RunnerRefused):M._validate_manifest_payload(value,tampered,metadata,1000)
  secret=manifest(files);secret["credential_files"]=["id_ed25519"]
  with self.assertRaises(M.RunnerRefused):M._validate_manifest_payload(secret,files,metadata,1000)
  linked=dict(metadata);linked[next(iter(linked))]=types.SimpleNamespace(st_mode=stat.S_IFREG|0o444,st_uid=1000,st_nlink=2)
  with self.assertRaises(M.RunnerRefused):M._validate_manifest_payload(value,files,linked,1000)
 def test_fixed_git_environment_drops_forged_parent_values(self):
  if sys.platform!="linux":self.skipTest("production constructor is Linux-only")
  boundary=M.LinuxRunnerBoundary();calls=[]
  def run(command,**kwargs):
   calls.append(kwargs["env"]);return types.SimpleNamespace(returncode=0,stdout="a"*40+"\n" if kwargs.get("text") else b"")
  executable=types.SimpleNamespace(st_mode=stat.S_IFREG|0o755,st_uid=0)
  with mock.patch.object(M.os,"lstat",return_value=executable),mock.patch.object(M.subprocess,"run",side_effect=run):
   boundary.validate_reviewed_commit({"reviewed_commit":"a"*40})
  self.assertEqual(calls,[{"PATH":"/usr/bin:/bin","HOME":"/nonexistent","LANG":"C.UTF-8","GIT_CONFIG_NOSYSTEM":"1","GIT_CONFIG_GLOBAL":"/dev/null"}]*2)
if __name__=="__main__":unittest.main()
