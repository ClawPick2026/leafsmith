"""Protocol-level regression tests; processing modules have separate real-fixture suites."""
import json,subprocess,sys,unittest
from pathlib import Path
MAIN=Path(__file__).resolve().parents[1]/'main.py'
class ProtocolTests(unittest.TestCase):
 def test_unknown_operation_returns_structured_error_without_running_a_shell(self):
  run=subprocess.run([sys.executable,str(MAIN)],input=json.dumps({'operation':'shell','inputs':[],'output_dir':'/untrusted','options':{'command':'echo DO_NOT_EXECUTE'}})+'\n',text=True,capture_output=True)
  self.assertEqual(run.returncode,1,'Worker must reject unknown operations through its JSON protocol')
  data=json.loads(run.stdout);self.assertFalse(data['ok']);self.assertEqual(data['error']['code'],'unknown_operation');self.assertNotIn('DO_NOT_EXECUTE',run.stdout+run.stderr)
 def test_malformed_json_is_rejected_without_traceback(self):
  run=subprocess.run([sys.executable,str(MAIN)],input='broken\n',text=True,capture_output=True)
  self.assertEqual(run.returncode,1);self.assertEqual(json.loads(run.stdout)['error']['code'],'invalid_request');self.assertNotIn('Traceback',run.stderr)
if __name__=='__main__':unittest.main()
