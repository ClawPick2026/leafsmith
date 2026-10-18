"""Review regressions; must pass before publication. Uses fixtures from e2e.py."""
import json,os,sys
from pathlib import Path
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parents[1];ART=ROOT/'tests/artifacts';ART.mkdir(exist_ok=True)
settings=json.loads((ROOT/'tests/browser-env.json').read_text());env=os.environ.copy();env['LD_LIBRARY_PATH']=settings['library_path']
base=sys.argv[1] if len(sys.argv)>1 else 'http://127.0.0.1:3140'
results=[]
with sync_playwright() as p:
 b=p.chromium.launch(headless=True,executable_path=settings['executable_path'],args=settings['launch_args'],env=env)
 def check(name,fn):
  page=b.new_page(viewport={'width':1440,'height':1080});page.goto(base,wait_until='networkidle')
  try:fn(page);results.append({'check':name,'passed':True});print('PASS',name)
  except Exception as e:results.append({'check':name,'passed':False,'error':str(e)});print('FAIL',name,str(e)[:250])
  finally:page.close()
 def load(page,name,tool):
  page.get_by_test_id('file-input').set_input_files(str(ART/name))
  expect(page.get_by_role('button',name='Clear workspace',exact=True)).to_be_enabled(timeout=45000)
  page.get_by_test_id('tool-'+tool).click()
 def retained(page):
  page.get_by_test_id('tool-qr').click();page.get_by_test_id('run-tool').click();expect(page.get_by_test_id('download-result')).to_have_count(1,timeout=45000)
  url=page.get_by_test_id('download-result').get_attribute('href')
  page.get_by_label('Link or text').fill('');page.get_by_test_id('run-tool').click();expect(page.get_by_role('alert')).to_be_visible()
  expect(page.get_by_test_id('download-result')).to_have_count(1)
  assert page.get_by_test_id('download-result').get_attribute('href')==url
 check('failed operation preserves previous download',retained)
 def sample(page):
  load(page,'source.pdf','organize');page.get_by_role('button',name='Paperwork home').click()
  sample=page.get_by_role('button',name='Try a sample',exact=True)
  assert sample.count()==0 or not sample.is_enabled(),'Sample must not silently replace an occupied workspace'
 check('sample cannot replace occupied workspace silently',sample)
 def stale_signature(page):
  load(page,'source.pdf','sign');c=page.get_by_label('Draw signature');box=c.bounding_box()
  page.mouse.move(box['x']+20,box['y']+40);page.mouse.down();page.mouse.move(box['x']+80,box['y']+80);page.mouse.up();page.wait_for_timeout(300)
  page.get_by_role('button',name='Paperwork home').click();page.get_by_test_id('tool-sign').click();page.get_by_test_id('run-tool').click()
  expect(page.get_by_role('alert')).to_contain_text('Draw a signature first')
 check('blank signature canvas never stamps stale signature',stale_signature)
 def rejected(page):
  page.get_by_test_id('file-input').set_input_files(str(ART/'locked.pdf'));expect(page.get_by_role('alert')).to_be_visible(timeout=45000)
  page.get_by_test_id('tool-organize').click();expect(page.get_by_role('alert')).to_contain_text('encrypt',ignore_case=True)
 check('rejected PDF reason remains visible after tool navigation',rejected)
 def labels(page):
  load(page,'source.pdf','split');expect(page.get_by_role('combobox',name='Output',exact=True)).to_be_visible()
 check('selects have concise programmatic labels',labels)
 def icons(page):
  assert page.locator('header svg').first.get_attribute('stroke-width')=='1.5'
 check('SVG strokes use valid SVG attributes',icons)
 b.close()
(ART/'review-regressions.json').write_text(json.dumps(results,indent=2))
sys.exit(0 if all(r['passed'] for r in results) else 1)
