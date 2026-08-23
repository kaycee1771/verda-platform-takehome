import hashlib,importlib.util,pathlib,stat,subprocess,sys,types,unittest
ROOT=pathlib.Path(__file__).parents[2];PATH=ROOT/"scripts/phase6/linux-transaction-runner.py"
s=importlib.util.spec_from_file_location("linux_runner",PATH);M=importlib.util.module_from_spec(s);s.loader.exec_module(M)
def h(v):return hashlib.sha256(v).hexdigest()
def manifest(files):
 value={"schema_version":1,"reviewed_commit":"a"*40,"files":{k:h(v) for k,v in files.items()},"runner_image":M.PINNED_IMAGE,"runner_image_digest":M.PINNED_IMAGE_DIGEST,"clean_tree":True,"execution_enabled":False,"credential_files":[],"raw_values_recorded":False}
 value.update({field:value["files"][path] for path,field in M.ARCHIVE_PATHS.items()});return value
class LinuxRunnerTests(unittest.TestCase):
 def test_direct_refuses_and_contains_no_effect_route(self):
  self.assertEqual(subprocess.run([sys.executable,str(PATH)],capture_output=True).returncode,64)
  source=PATH.read_text()
  for token in ("subprocess","terraform apply","ansible-playbook","kubectl","requests","socket"):self.assertNotIn(token,source)
 def test_platform_and_exact_xdg_roots(self):
  with self.assertRaises(M.RunnerRefused):M.LinuxRunnerBoundary(platform="win32")
  good=lambda p:types.SimpleNamespace(st_mode=stat.S_IFDIR|0o700,st_uid=1000,st_nlink=2)
  b=M.LinuxRunnerBoundary(platform="linux",uid=1000,config_home=pathlib.PurePosixPath("/control/config"),state_home=pathlib.PurePosixPath("/control/state"),stat_probe=good,allow_test_probe=True);b.validate_roots()
  bad=lambda p:types.SimpleNamespace(st_mode=stat.S_IFDIR|0o755,st_uid=1000,st_nlink=2)
  with self.assertRaises(M.RunnerRefused):M.LinuxRunnerBoundary(platform="linux",uid=1000,config_home=pathlib.PurePosixPath("/c"),state_home=pathlib.PurePosixPath("/s"),stat_probe=bad,allow_test_probe=True).validate_roots()
 def test_credential_free_archive_and_tamper(self):
  files={path:path.encode() for path in M.ARCHIVE_PATHS};b=M.LinuxRunnerBoundary(platform="linux",uid=1000,config_home=pathlib.Path("/c"),state_home=pathlib.Path("/s"),allow_test_probe=True)
  metadata={path:types.SimpleNamespace(st_mode=stat.S_IFREG|0o444,st_uid=1000,st_nlink=1) for path in files}
  value=manifest(files);b.validate_manifest(value,files,metadata);b.validate_reviewed_commit(value,lambda:("a"*40,True))
  tampered=dict(files);tampered[next(iter(files))]=b"tampered"
  with self.assertRaises(M.RunnerRefused):b.validate_manifest(value,tampered,metadata)
  secret=manifest(files);secret["credential_files"]=["id_ed25519"]
  with self.assertRaises(M.RunnerRefused):b.validate_manifest(secret,files,metadata)
  linked=dict(metadata);linked[next(iter(linked))]=types.SimpleNamespace(st_mode=stat.S_IFREG|0o444,st_uid=1000,st_nlink=2)
  with self.assertRaises(M.RunnerRefused):b.validate_manifest(value,files,linked)
  with self.assertRaises(M.RunnerRefused):b.validate_reviewed_commit(value,lambda:("b"*40,True))
if __name__=="__main__":unittest.main()
