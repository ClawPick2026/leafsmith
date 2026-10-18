"""HTTP-level shell acceptance; browser E2E covers actual interaction separately."""
import os, unittest, urllib.request

class ShellTest(unittest.TestCase):
    def test_app_ships_browser_only_workspace_and_explicit_limits(self):
        base=os.environ.get('LEAFSMITH_URL','http://127.0.0.1:3140').rstrip('/')
        body=urllib.request.urlopen(base+'/client.js',timeout=30).read().decode()
        self.assertIn('Your documents.',body)
        self.assertIn('Your device.',body)
        self.assertIn('Not included in this release',body)
        self.assertIn('Choose files',body)
        self.assertNotIn('storage.upload(',body)

if __name__=='__main__': unittest.main()
