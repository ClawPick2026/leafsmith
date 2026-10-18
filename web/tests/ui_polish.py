"""Browser regression tests for cursor behavior and factual website copy."""
import json,os,unittest
from pathlib import Path
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parents[1]
BASE=os.environ.get('PAPERWORK_URL','https://paperwork.lakebed.app')

class CursorTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  settings=json.loads((ROOT/'tests/browser-env.json').read_text());env=os.environ.copy();env['LD_LIBRARY_PATH']=settings['library_path']
  cls.pw=sync_playwright().start();cls.browser=cls.pw.chromium.launch(headless=True,executable_path=settings['executable_path'],args=settings['launch_args'],env=env)
 @classmethod
 def tearDownClass(cls):cls.browser.close();cls.pw.stop()
 def setUp(self):
  self.page=self.browser.new_page(viewport={'width':1440,'height':1080});self.page.goto(BASE,wait_until='networkidle')
 def tearDown(self):self.page.close()
 def assert_pointer_controls(self):
  controls=self.page.locator('button:enabled, a[href]')
  wrong=controls.evaluate_all("els => els.filter(e=>e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden'&&getComputedStyle(e).cursor!=='pointer').map(e=>({name:e.getAttribute('aria-label')||e.innerText,cursor:getComputedStyle(e).cursor}))")
  self.assertEqual(wrong,[],f'Enabled controls must use the pointing-hand cursor: {wrong}')
  button=self.page.locator('button:enabled:visible').last;button.hover()
  self.assertEqual(button.evaluate('e=>getComputedStyle(e).cursor'),'pointer')
 def test_pointing_hand_on_every_enabled_button_in_each_view(self):
  self.assert_pointer_controls()
  ids=self.page.locator('[data-testid^="tool-"]').evaluate_all('els=>els.map(e=>e.dataset.testid)')
  self.assertEqual(len(ids),12)
  self.page.get_by_role('button',name='Try a sample',exact=True).click()
  expect(self.page.get_by_test_id('run-tool')).to_be_enabled(timeout=45000)
  self.assert_pointer_controls()
  for tool in ids:
   self.page.get_by_role('button',name='Paperwork home').click();self.page.get_by_test_id(tool).click();self.assert_pointer_controls()
  self.page.get_by_role('button',name='Paperwork home').click();self.page.get_by_test_id('tool-qr').click();self.page.get_by_test_id('run-tool').click()
  expect(self.page.get_by_test_id('download-result')).to_have_count(1,timeout=45000);self.assert_pointer_controls()
  self.page.get_by_role('button',name='Scope & privacy',exact=True).click();self.assert_pointer_controls()

 def test_promotional_subtitles_are_absent(self):
  phrases=['Pick a task. We’ll keep it simple.','A calmer place to sort, sign and transform your PDFs.','Useful tools, without sending your files away.','Less friction. More finished.','Make light work','A little more private.','Start with a file. Finish with a little less work.','A tool for every to-do.','Ready when you are.','The small print, in plain words','Local by design. Honest by default.','Made to be scanned']
  def assert_objective():
   body=self.page.locator('body').inner_text()
   for phrase in phrases:self.assertNotIn(phrase.casefold(),body.casefold())
  assert_objective()
  self.page.get_by_role('button',name='Scope & privacy',exact=True).click();assert_objective()
  self.page.get_by_role('button',name='Paperwork home').click();self.page.get_by_test_id('tool-qr').click();self.page.get_by_test_id('run-tool').click()
  expect(self.page.get_by_test_id('download-result')).to_have_count(1,timeout=45000);assert_objective()

if __name__=='__main__':unittest.main()
