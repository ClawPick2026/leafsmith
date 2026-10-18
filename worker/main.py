"""Single-request JSON-line worker. Stdout is a machine protocol, not a log."""
from __future__ import annotations
import json,sys,tempfile
from pathlib import Path

PDF_OPERATIONS=frozenset({'inspect_pdf','edit_pdf_text','annotate_pdf','convert_to_pdf','convert_from_pdf','ocr_pdf','ocr_image','form_template','protect_pdf','unlock_pdf','remove_watermark','compress_pdf'})
MEDIA_OPERATIONS=frozenset({'enhance_image','compress_video','transcribe','summarize','translate_pdf'})
MAX_REQUEST_BYTES=128*1024

def dispatch(request):
    if not isinstance(request,dict) or not isinstance(request.get('operation'),str):
        return {'ok':False,'error':{'code':'invalid_request','message':'Expected an operation and a JSON request object.'}}
    op=request['operation']
    if op not in PDF_OPERATIONS|MEDIA_OPERATIONS|{'health'}:
        return {'ok':False,'error':{'code':'unknown_operation','message':'This operation is not supported.'}}
    try:
        if op=='health':
            from pdf_ops import run
            from pypdf import PdfReader
            with tempfile.TemporaryDirectory(prefix='paperwork-selftest-') as folder:
                result=run({'operation':'form_template','inputs':[],'output_dir':folder,'options':{'template_id':'contact'},'engines':{}})
                if not result.get('outputs'):raise RuntimeError('The worker did not generate a form.')
                reader=PdfReader(result['outputs'][0]['path'])
                if not reader.pages or not reader.get_fields():raise RuntimeError('The generated form failed its read-back check.')
                result={'outputs':[],'details':{'version':'0.1.0','status':'ok','form_pages':len(reader.pages),'form_fields':len(reader.get_fields())}}
        elif op in PDF_OPERATIONS:
            from pdf_ops import run
            result=run(request)
        else:
            from media_ops import run
            result=run(request)
        if not isinstance(result,dict) or not isinstance(result.get('outputs'),list):raise RuntimeError('The processing engine returned an invalid result.')
        return {'ok':True,'result':result}
    except Exception as error:
        message=str(error)[:1200] or 'The operation failed.'
        options=request.get('options') or {}
        if isinstance(options,dict):
            for key in ('password','owner_password','api_key'):
                secret=options.get(key)
                if isinstance(secret,str) and secret:message=message.replace(secret,'[redacted]')
        return {'ok':False,'error':{'code':'processing_failed','message':message}}

def main():
    line=sys.stdin.buffer.readline(MAX_REQUEST_BYTES+1)
    try:
        if len(line)>MAX_REQUEST_BYTES:raise ValueError('Request too large')
        request=json.loads(line)
    except (ValueError,UnicodeError):
        response={'ok':False,'error':{'code':'invalid_request','message':'Expected one JSON request of at most 128 KiB.'}}
    else:response=dispatch(request)
    print(json.dumps(response,ensure_ascii=True),flush=True)
    return 0 if response['ok'] else 1

if __name__=='__main__':raise SystemExit(main())
