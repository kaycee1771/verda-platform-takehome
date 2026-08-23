import hashlib,importlib.util,pathlib,stat,subprocess,sys,types,unittest
ROOT=pathlib.Path(__file__).parents[2];PATH=ROOT/"scripts/phase6/linux-transaction-runner.py"
s=importlib.util.spec_from_file_location("linux_runner",PATH);M=importlib.util.module_from_spec(s);s.loader.exec_module(M)
def h(v):return hashlib.sha256(v).hexdigest()
def manifest(files):return {"schema_version":1,"reviewed_commit":"a"*40,"files":{k:h(v) for k,v in files.items()},"broker_sha256":h(b"b"),"model_sha256":h(b"m"),"policy_sha256":h(b"p"),"rollback_policy_sha256":h(b"r"),"terraform_lock_sha256":h(b"t"),"ansible_lock_sha256":h(b"a"),"runner_image":M.PINNED_IMAGE,"runner_image_digest":"0"*64,"clean_tree":True,"execution_enabled":False,"credential_files":[],"raw_values_recorded":False}
class LinuxRunnerTests(unittest.TestCase):
 def test_direct_refuses_and_contains_no_effect_route(self):
  self.assertEqual(subprocess.run([sys.executable,str(PATH)],capture_output=True).returncode,64)
  source=PATH.read_text()
  for token in ("subprocess","terraform apply","ansible-playbook","kubectl","requests","socket"):self.assertNotIn(token,source)
 def test_platform_and_exact_xdg_roots(self):
  with self.assertRaises(M.RunnerRefused):M.LinuxRunnerBoundary(platform="win32")
  good=lambda p:types.SimpleNamespace(st_mode=stat.S_IFDIR|0o700,st_uid=1000,st_nlink=2)
  b=M.LinuxRunnerBoundary(platform="linux",uid=1000,config_home=pathlib.PurePosixPath("/control/config"),state_home=pathlib.PurePosixPath("/control/state"),stat_probe=good);b.validate_roots()
  bad=lambda p:types.SimpleNamespace(st_mode=stat.S_IFDIR|0o755,st_uid=1000,st_nlink=2)
  with self.assertRaises(M.RunnerRefused):M.LinuxRunnerBoundary(platform="linux",uid=1000,config_home=pathlib.PurePosixPath("/c"),state_home=pathlib.PurePosixPath("/s"),stat_probe=bad).validate_roots()
 def test_credential_free_archive_and_tamper(self):
  files={"scripts/phase6/transaction-broker.py":b"broker","policies/transaction.json":b"policy"};b=M.LinuxRunnerBoundary(platform="linux",uid=1000,config_home=pathlib.Path("/c"),state_home=pathlib.Path("/s"))
  value=manifest(files);b.validate_manifest(value,files)
  tampered=dict(files);tampered[next(iter(files))]=b"tampered"
  with self.assertRaises(M.RunnerRefused):b.validate_manifest(value,tampered)
  secret=manifest(files);secret["credential_files"]=["id_ed25519"]
  with self.assertRaises(M.RunnerRefused):b.validate_manifest(secret,files)
if __name__=="__main__":unittest.main()
