export type Tool = {id:string; name:string; category:string; description:string; icon:string; tint:string; note:string};
export const categories = ['All tools','Pages','Edit & sign','Convert','Images','Utilities'];
export const tools: Tool[] = [
 {id:'organize',name:'Organize PDF',category:'Pages',description:'Reorder, rotate, crop, extract or delete pages.',icon:'pages',tint:'#e8effc',note:'Page copying may remove interactive forms and bookmarks. Crop changes the visible page box, not underlying content; it is not redaction.'},
 {id:'merge',name:'Merge PDFs',category:'Pages',description:'Combine multiple PDFs in the selected file order.',icon:'merge',tint:'#e8effc',note:'Reorder the file list before merging. Interactive fields and bookmarks may not survive merging.'},
 {id:'split',name:'Split PDF',category:'Pages',description:'Extract selected pages or save each page as a separate PDF.',icon:'split',tint:'#e8effc',note:'Download individual pages separately; your browser may ask permission for multiple downloads. Page copying may remove interactive forms.'},
 {id:'annotate',name:'Annotate PDF',category:'Edit & sign',description:'Add text, images, shapes and translucent highlights.',icon:'edit',tint:'#f9ebdf',note:'Adds flattened content, not editable PDF comments. Does not change existing text or fonts, remove watermarks, or redact information. Placement coordinates use the unrotated PDF page; drawing the box on the preview fills them in.'},
 {id:'sign',name:'Sign PDF',category:'Edit & sign',description:'Draw your signature and place it on a document.',icon:'sign',tint:'#f9ebdf',note:'A drawn electronic signature only, added as a locked stamp annotation above page content, form fields and earlier annotations. Not a certificate-backed digital signature or identity verification. Existing digital signatures may be invalidated by any PDF edit.'},
 {id:'forms',name:'Fill PDF forms',category:'Edit & sign',description:'Fill existing text fields, checkboxes and supported dropdowns.',icon:'form',tint:'#f9ebdf',note:'Supports existing AcroForm text, checkbox and choice fields. No XFA, new field creation, or form template library. Flattening removes interactivity.'},
 {id:'images-pdf',name:'Images to PDF',category:'Convert',description:'Convert PNG and JPEG images into one PDF.',icon:'image',tint:'#e7f0e7',note:'PNG and JPEG input only, one image per page. No Word, Excel or PowerPoint conversion.'},
 {id:'pdf-images',name:'PDF to images',category:'Convert',description:'Export selected PDF pages, or a cropped area of them, as PNG images.',icon:'export',tint:'#e7f0e7',note:'Renders pages as PNG. Crop margins limit each image to the selected area of the page. Downloads are separate and selected pages are capped at 30 per run.'},
 {id:'text',name:'Extract PDF text',category:'Convert',description:'Save text already embedded in a PDF as a .txt file.',icon:'text',tint:'#e7f0e7',note:'Not OCR. Scanned or image-only pages may contain no extractable text. Reading order and layout are not guaranteed.'},
 {id:'optimize',name:'Optimize PDF',category:'Pages',description:'Optimize PDF structure without changing image quality.',icon:'compress',tint:'#e8effc',note:'Best-effort PDF reserialization, not image downsampling. Already optimized PDFs may not shrink; the original is returned if the output would be larger.'},
 {id:'image-tools',name:'Image studio',category:'Images',description:'Crop, resize, compress, adjust brightness and contrast, or combine images.',icon:'sliders',tint:'#f0eafa',note:'PNG, JPEG and WebP conversion uses your browser canvas. Cropping removes the pixels outside the selected area. JPEG/WebP may be lossy. Image adjustment is not AI restoration. Image adjustment output is capped at 4096 px per side. All canvases, including combined images, are capped at 16 million pixels.'},
 {id:'qr',name:'QR code generator',category:'Utilities',description:'Generate a QR code from a link or text.',icon:'qr',tint:'#f0eafa',note:'Generates an SVG locally. No tracking or URL shortening. Limit 1000 UTF-8 bytes.'}
];
export function findTools(category:string,search:string): Tool[] {
 const q=search.trim().toLowerCase();
 return tools.filter(t=>(category==='All tools'||t.category===category)&&(!q||`${t.name} ${t.description} ${t.note}`.toLowerCase().includes(q)));
}
export const unsupported = [
 ['Existing text & font editing','PDF text reflow and original-font editing are not included. New text can be added as an overlay.'],
 ['Word, Excel & PowerPoint','Office-to/from-PDF conversion needs a separate conversion engine.'],
 ['OCR & scanned document editing','This release extracts existing PDF text only; it does not recognize text in images.'],
 ['Passwords, unlocking & watermark removal','Encryption, decryption and reliable watermark removal are not included. Protected PDFs are rejected.'],
 ['AI summaries, book summaries & translation','No AI provider or model is connected, and no document is sent to one.'],
 ['Audio/video transcription & video compression','These processing-heavy features are outside this browser-only release.'],
 ['Form templates & digital certificates','Fill existing supported forms and add a drawn signature; no template library or certificate signing.']
];
