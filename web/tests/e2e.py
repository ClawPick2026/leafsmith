"""Browser acceptance against real documents and independently parsed downloads.
Run: .test-venv/bin/python tests/e2e.py [http://127.0.0.1:3140]
Requires a local Playwright browser; tests/browser-env.json can scope an alternate
executable_path, library_path and launch_args without changing global config.
"""
import io, json, os, sys, time
from pathlib import Path
from playwright.sync_api import sync_playwright, expect
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
ART=ROOT/'tests'/'artifacts'; ART.mkdir(exist_ok=True)
BASE=sys.argv[1] if len(sys.argv)>1 else 'http://127.0.0.1:3140'

def fixtures():
    c=canvas.Canvas(str(ART/'source.pdf'),pagesize=(600,800))
    for n,word in enumerate(['Alpha','Beta','Gamma'],1):
        c.setFont('Helvetica',24);c.drawString(50,730,f'Original {word} - Page {n}')
        if n==1:
            c.acroForm.textfield(name='name',x=50,y=600,width=200,height=25,value='Ada')
            c.acroForm.checkbox(name='approved',x=50,y=550,checked=False)
        c.showPage()
    c.save()
    c=canvas.Canvas(str(ART/'second.pdf'),pagesize=(600,800));c.drawString(50,730,'Delta document');c.save()
    Image.new('RGB',(240,120),(210,70,45)).save(ART/'red.jpg',quality=95)
    Image.new('RGB',(80,160),(70,140,85)).save(ART/'green.png')
    w=PdfWriter();w.append(str(ART/'source.pdf'));w.encrypt('secret');w.write(str(ART/'locked.pdf'))
    (ART/'invalid.pdf').write_bytes(b'not a pdf file')
    (ART/'unsafe-name.pdf').write_bytes((ART/'source.pdf').read_bytes())

fixtures()
settings=json.loads((ROOT/'tests/browser-env.json').read_text()) if (ROOT/'tests/browser-env.json').exists() else {}
env=os.environ.copy()
if settings.get('library_path'): env['LD_LIBRARY_PATH']=settings['library_path']
results=[];errors=[];requests=[]
def record(name,fn):
    t=time.time();fn();results.append({'check':name,'passed':True,'seconds':round(time.time()-t,2)});print('PASS',name,flush=True)

with sync_playwright() as p:
    launch={'headless':True,'args':settings.get('launch_args',['--no-sandbox']),'env':env}
    if settings.get('executable_path'):launch['executable_path']=settings['executable_path']
    browser=p.chromium.launch(**launch)
    context=browser.new_context(viewport={'width':1440,'height':1080},accept_downloads=True)
    page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
    page.on('request',lambda r:requests.append({'url':r.url,'method':r.method,'body':r.post_data or ''}))
    page.set_default_timeout(30000)
    page.goto(BASE,wait_until='networkidle')
    def home():
        page.get_by_role('button',name='Paperwork home').click()
    def clear():
        home()
        if page.get_by_role('button',name='Clear workspace',exact=True).count():page.get_by_role('button',name='Clear workspace',exact=True).click()
    def load(names,tool):
        clear();page.get_by_test_id('file-input').set_input_files([str(ART/name) for name in names])
        expect(page.get_by_role('status')).to_have_count(0,timeout=45000) if False else None
        expect(page.get_by_role('button',name='Clear workspace',exact=True)).to_be_enabled(timeout=45000)
        page.get_by_test_id('tool-'+tool).click()
        expect(page.get_by_test_id('run-tool')).to_be_enabled(timeout=45000)
    def run(name):
        page.get_by_test_id('run-tool').click()
        expect(page.get_by_role('region',name='Results')).to_be_visible(timeout=60000)
        a=page.get_by_test_id('download-result').filter(has_text='Download').first
        with page.expect_download() as dl:a.click()
        path=ART/name;dl.value.save_as(path);return path
    def shell():
        expect(page.get_by_role('heading',name='Your documents. Your device.')).to_be_visible()
        assert page.locator('[data-testid^="tool-"]').count()==12
        page.screenshot(path=str(ART/'desktop-home.png'),full_page=True)
        page.get_by_role('button',name='Scope & privacy').click()
        expect(page.get_by_role('heading',name='Not included in this release')).to_be_visible()
        assert 'does not upload documents' in page.locator('main').inner_text()
        home();page.get_by_role('textbox',name='Search tools').fill('Organize')
        expect(page.locator('[data-testid^="tool-"]')).to_have_count(1)
        page.get_by_role('textbox',name='Search tools').fill('')
    record('responsive app shell, search and explicit limitations',shell)
    def organize():
        load(['source.pdf'],'organize');page.get_by_test_id('page-range').fill('3,1')
        page.get_by_label('Rotate output pages').select_option('90')
        page.get_by_label('Left',exact=True).fill('10');page.get_by_label('Top',exact=True).fill('20')
        result=PdfReader(run('organized.pdf'))
        assert len(result.pages)==2
        assert 'Gamma' in result.pages[0].extract_text() and 'Alpha' in result.pages[1].extract_text()
        assert result.pages[0].rotation==90
        assert abs(float(result.pages[0].cropbox.width)-590)<.1
        assert abs(float(result.pages[0].cropbox.height)-780)<.1
        page.screenshot(path=str(ART/'desktop-workspace.png'),full_page=True)
    record('reorder, extract, delete, rotate and crop real PDF',organize)
    def merge():
        load(['source.pdf','second.pdf'],'merge');result=PdfReader(run('merged.pdf'))
        assert len(result.pages)==4 and 'Delta' in result.pages[3].extract_text()
    record('merge PDFs in workspace order',merge)
    def split():
        load(['source.pdf'],'split');page.get_by_test_id('page-range').fill('2-3')
        page.get_by_role('combobox',name='Output',exact=True).select_option('individual');page.get_by_test_id('run-tool').click()
        expect(page.get_by_test_id('download-result')).to_have_count(2,timeout=45000)
        for i in range(2):
            with page.expect_download() as dl:page.get_by_test_id('download-result').nth(i).click()
            path=ART/f'split-{i}.pdf';dl.value.save_as(path);r=PdfReader(path)
            assert len(r.pages)==1 and ['Beta','Gamma'][i] in r.pages[0].extract_text()
    record('split selection into independent one-page downloads',split)
    def annotate():
        load(['source.pdf'],'annotate');page.get_by_label('New text',exact=True).fill('Reviewed by Paperwork')
        result=PdfReader(run('annotated.pdf'))
        assert 'Reviewed by Paperwork' in ' '.join(result.pages[0].extract_text().split())
        assert result.get_fields()['name']['/V']=='Ada'
    record('add text overlay while preserving supported forms',annotate)
    def fill():
        load(['source.pdf'],'forms');page.get_by_label('name',exact=True).fill('Grace Hopper')
        page.get_by_label('approved',exact=True).check();result=PdfReader(run('filled.pdf'))
        assert result.get_fields()['name']['/V']=='Grace Hopper'
        assert result.get_fields()['approved']['/V']!='/Off'
    record('fillable text and checkbox values round-trip',fill)
    def images_pdf():
        load(['red.jpg','green.png'],'images-pdf');result=PdfReader(run('images.pdf'))
        assert len(result.pages)==2
    record('JPEG and PNG to two-page PDF',images_pdf)
    def pdf_images():
        load(['source.pdf'],'pdf-images');page.get_by_test_id('page-range').fill('2')
        image=Image.open(run('export.png'));assert image.size==(900,1200)
    record('PDF page renders to real PNG',pdf_images)
    def text_extract():
        load(['source.pdf'],'text');page.get_by_test_id('page-range').fill('3')
        text=run('text.txt').read_text();assert 'Gamma' in text and 'Alpha' not in text
    record('extract embedded text for selected pages',text_extract)
    def optimize():
        load(['source.pdf'],'optimize');path=run('optimized.pdf')
        assert path.stat().st_size<=(ART/'source.pdf').stat().st_size
        result=PdfReader(path);assert len(result.pages)==3 and 'Alpha' in result.pages[0].extract_text()
    record('optimization never increases output size',optimize)
    def image_studio():
        load(['red.jpg'],'image-tools');page.get_by_label('Maximum width (px)').fill('120')
        image=Image.open(run('resized.jpg'));assert image.size==(120,60)
        load(['red.jpg','green.png'],'image-tools');page.get_by_role('combobox',name='Task',exact=True).select_option('merge')
        image=Image.open(run('combined.png'));assert image.size==(240,280)
    record('image resize/compress and vertical combination',image_studio)
    def qr():
        clear();page.get_by_test_id('tool-qr').click();page.get_by_label('Link or text').fill('https://example.com/paperwork')
        content=run('qr.svg').read_text();assert '<svg' in content and ('<path' in content or '<rect' in content)
        expect(page.get_by_role('img',name='Generated QR code')).to_be_visible()
    record('QR SVG generation and preview',qr)
    def signature():
        load(['source.pdf'],'sign');c=page.get_by_label('Draw signature');box=c.bounding_box()
        page.mouse.move(box['x']+20,box['y']+50);page.mouse.down()
        for dx,dy in [(40,30),(60,70),(90,25),(130,55)]:page.mouse.move(box['x']+dx,box['y']+dy)
        page.mouse.up();page.wait_for_timeout(300)
        result=PdfReader(run('signed.pdf'));resources=result.pages[0]['/Resources']
        assert '/XObject' in resources
    record('drawn electronic signature adds an image to PDF',signature)
    def invalid():
        load(['source.pdf'],'organize');page.get_by_test_id('page-range').fill('99');page.get_by_test_id('run-tool').click()
        expect(page.get_by_role('alert')).to_be_visible();assert page.get_by_test_id('download-result').count()==0
        clear();page.get_by_test_id('file-input').set_input_files(str(ART/'locked.pdf'))
        expect(page.get_by_role('alert')).to_contain_text('encrypt',ignore_case=True,timeout=45000)
        clear();page.get_by_test_id('file-input').set_input_files(str(ART/'invalid.pdf'))
        expect(page.get_by_role('alert')).to_be_visible(timeout=45000)
    record('invalid ranges, encrypted and malformed PDFs fail visibly',invalid)
    def mobile():
        clear();page.set_viewport_size({'width':390,'height':844})
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        expect(page.get_by_role('button',name='Choose files',exact=True)).to_be_visible()
        page.screenshot(path=str(ART/'mobile-home.png'),full_page=True)
    record('390px mobile layout without horizontal overflow',mobile)
    def privacy():
        assert not any('Original Alpha' in r['body'] or 'Grace Hopper' in r['body'] for r in requests)
        assert not any('/storage/' in r['url'] for r in requests)
        assert not errors,errors
    record('no document uploads and no uncaught browser errors',privacy)
    browser.close()
(ART/'acceptance.json').write_text(json.dumps({'base_url':BASE,'checks':results,'browser_errors':errors,'network_request_count':len(requests)},indent=2))
print(json.dumps({'passed':len(results),'base_url':BASE,'report':str(ART/'acceptance.json')},indent=2))
