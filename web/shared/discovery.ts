export type Guide = {
  path: string;
  toolId: string;
  title: string;
  description: string;
  heading: string;
  intro: string;
  steps: string[];
  limitations: string[];
  faq: { question: string; answer: string }[];
};
export const siteUrl = 'https://leafsmith.lakebed.app';
// Before the rename to Leafsmith the site was paperwork.lakebed.app. That host
// still serves this deploy so old links work; the client moves visitors on.
const previousHosts = ['paperwork.lakebed.app'];

/** The same page on siteUrl when `href` is on a previous host, otherwise null. */
export function movedTo(href: string): string | null {
  const url = new URL(href);
  return previousHosts.includes(url.hostname) ? siteUrl + url.pathname + url.search + url.hash : null;
}
export const homeTitle = 'Leafsmith — Free PDF & Image Tools, No Uploads';
export const homeDescription = 'Free browser tools to merge, split and sign PDFs or convert PNG and JPEG images to PDF. No account or uploads; files are processed in tab memory.';

export const guideIndex = {
  path: '/tools',
  title: 'PDF & Image Tool Guides — Leafsmith',
  description: 'Instructions for merging and splitting PDFs, converting images to PDF and drawing electronic signatures. Free browser tools with no account or document uploads.',
  heading: 'PDF and image tool guides',
  intro: 'Choose a guide for steps, input limits and output checks.',
};

export const scopeHeading = 'Privacy and browser edition limits';
export const scopeParagraphs = [
  'Free to use, with no account and no document uploads. Files are processed in tab memory, not on our server. Download your results before closing or reloading the tab; there is no saved workspace.',
  'The host and CDN receive request metadata such as your IP address when you load the app or libraries. Third-party scripts run in the page and must be trusted. You need internet access to load processing libraries; offline operation is not guaranteed.',
  'Limits: 8 files, 25 MiB per file, 50 MiB combined and 200 pages per PDF. Device memory may impose lower practical limits. Password-protected PDFs are rejected.',
  'This browser edition has no OCR, Office conversion or original text editing. Crop changes the visible page box, not underlying content; it is not redaction.',
];

/** schema.org graph for discovery pages: the free web app, plus a breadcrumb on guides. */
export function structuredData(guide?: Guide) {
  const graph: Record<string, unknown>[] = [{
    '@type': 'WebApplication', name: 'Leafsmith', url: siteUrl + '/',
    description: homeDescription, applicationCategory: 'UtilitiesApplication',
    operatingSystem: 'Any (web browser)',
    browserRequirements: 'JavaScript required; internet access needed to load processing libraries.',
    isAccessibleForFree: true,
    offers: { '@type': 'Offer', price: '0', priceCurrency: 'USD' },
  }];
  if (guide) graph.push({
    '@type': 'BreadcrumbList',
    itemListElement: [
      { '@type': 'ListItem', position: 1, name: 'Leafsmith', item: siteUrl + '/' },
      { '@type': 'ListItem', position: 2, name: 'Tool guides', item: siteUrl + guideIndex.path },
      { '@type': 'ListItem', position: 3, name: guide.heading, item: siteUrl + guide.path },
    ],
  });
  return { '@context': 'https://schema.org', '@graph': graph };
}

export const guides: Guide[] = [
  {
    path: '/merge-pdf', toolId: 'merge',
    title: 'Merge PDFs in File Order, No Uploads — Leafsmith',
    description: 'Combine two to eight PDFs in your browser. Set the file order, merge up to 200 pages and download one PDF without uploading your documents.',
    heading: 'Merge PDFs in the order you choose',
    intro: 'Combine separate PDF documents into one downloadable file. The workspace list determines the order of entire documents; it does not interleave their pages.',
    steps: [
      'Open Merge PDFs and choose two to eight unencrypted PDF files. Remove any images from the workspace before merging.',
      'Use ↑ and ↓ beside each filename to set the document order. Pages inside each source keep their original order.',
      'Check that the combined output will contain at most 200 pages, then select Merge PDFs.',
      'In Results, select Download to save merged.pdf. Open the downloaded file and check the page order before sharing it.',
    ],
    limitations: [
      'The merged output is limited to 200 pages in total, even if each source PDF is within the per-file page limit.',
      'Page copying may lose interactive forms and bookmarks. Keep the original documents if these features matter.',
      'Rewriting a PDF may invalidate existing certificate signatures; merging does not preserve signature validity.',
    ],
    faq: [
      { question: 'Can I change the order of individual pages while merging?', answer: 'Merge uses the order of whole files. Download the merged PDF, then use Organize PDF if you need to extract or reorder individual pages.' },
      { question: 'Why is merging unavailable when images are open?', answer: 'Merge PDFs requires at least two PDFs and no images in the workspace. Remove the images, or use Images to PDF first and then open that PDF with your other documents.' },
    ],
  },
  {
    path: '/split-pdf', toolId: 'split',
    title: 'Split a PDF or Extract Selected Pages — Leafsmith',
    description: 'Extract a page range into one PDF or save separate page files. Select pages locally, with up to 30 individual downloads per batch and no uploads.',
    heading: 'Split a PDF or keep only selected pages',
    intro: 'Work on the active PDF to produce one file containing a selection, or one file per selected page. Your source on disk is not changed.',
    steps: [
      'Open Split PDF, choose a PDF and select its filename in the workspace to make it active.',
      'Enter page numbers and ranges such as 1,3-5 in the Pages field. Leave it empty to select every page.',
      'Under Output, choose One PDF with selected pages or Separate PDF for each selected page. For separate files, select no more than 30 pages per batch.',
      'Select Extract pages or Split into pages, then use Download beside each file in Results. Your browser may request permission for multiple downloads.',
    ],
    limitations: [
      'Each input PDF may contain up to 200 pages. Separate page output is limited to 30 pages per batch; repeat with another range for more pages.',
      'Page copying may lose interactive forms and bookmarks. It may also invalidate existing certificate signatures.',
    ],
    faq: [
      { question: 'How do I save several selected pages as a single PDF?', answer: 'Enter a selection such as 1,3-5, keep One PDF with selected pages under Output, then select Extract pages. Download extracted.pdf from Results.' },
      { question: 'Why did only one separate page download?', answer: 'Each page has its own Download link in Results. Download the other files individually and allow multiple downloads if your browser prompts you. There is no ZIP download.' },
    ],
  },
  {
    path: '/images-to-pdf', toolId: 'images-pdf',
    title: 'Convert PNG and JPEG Images to PDF — Leafsmith',
    description: 'Turn PNG and JPEG images into a PDF in your browser. Arrange up to eight images, fit each within A4 bounds and download without uploading files.',
    heading: 'Put PNG and JPEG images into one PDF',
    intro: 'Create a PDF from photos or scanned page images. Each image becomes one page, scaled down if necessary to fit within A4 bounds, using the workspace file order.',
    steps: [
      'Open Images to PDF and choose PNG or JPEG images from your device. Remove PDFs and other image formats from the workspace.',
      'Use ↑ and ↓ beside each filename to arrange the images in reading order. Each image becomes a separate page.',
      'Select Create PDF. Each page size follows the image, capped at A4 bounds; images are not padded onto fixed-size sheets.',
      'Select Download in Results to save images.pdf. Check orientation and legibility in the saved PDF before printing or sharing.',
    ],
    limitations: [
      'PNG and JPEG input only, with at most 8 images. WebP, HEIC, TIFF and Office files are not supported by this converter.',
      'One image per page, within A4 bounds rather than fixed A4 sheets. This is not OCR: text in a scanned image is not converted into searchable or editable text.',
    ],
    faq: [
      { question: 'Can I turn a phone scan into searchable PDF text?', answer: 'You can put a PNG or JPEG scan into a PDF, but the page remains an image. This browser edition has no OCR and does not recognize the text in your scan.' },
      { question: 'Can I mix photos and PDFs in this conversion?', answer: 'No. Create a PDF from the images first, download it, then open it with the other PDFs in Merge PDFs. Images to PDF accepts only PNG and JPEG files.' },
    ],
  },
  {
    path: '/sign-pdf', toolId: 'sign',
    title: 'Draw and Place an Electronic Signature on PDF — Leafsmith',
    description: 'Draw a signature, set its page and position, and download a signed PDF locally. A drawn electronic signature, not certificate signing or identity verification.',
    heading: 'Draw a signature and place it on a PDF',
    intro: 'Add your drawn signature as an image on a chosen PDF page. This creates a visible electronic signature, not a verified digital certificate.',
    steps: [
      'Open Sign PDF, choose an unencrypted PDF and select its filename to make it active.',
      'Set Page to the page you want to sign, then draw in the signature box. Use Clear if you need to draw it again.',
      'Drag on the page preview to draw the signature box, or set X from the left, Y from the bottom, Width and Height in PDF points. There are 72 points per inch; typed coordinates use the unrotated page.',
      'Select Add signature. Results shows the signed page rendered from signed.pdf; check the placement there, then select Download to save the file.',
    ],
    limitations: [
      'A drawn electronic signature is not certificate-backed and is not identity verified. Ask the recipient whether this form of signature is acceptable.',
      'Rewriting a PDF may invalidate existing certificate signatures. Keep the original if it already contains a certificate signature.',
      'The signature is flattened page content, not a new interactive signature field. Placement on rotated pages needs careful checking.',
    ],
    faq: [
      { question: 'Does this verify who signed the document?', answer: 'No. The tool places the drawing you provide on the PDF. It does not verify identity, issue a certificate or provide a signing audit trail.' },
      { question: 'Why is my signature missing from the source preview?', answer: 'The source preview shows the original PDF with a box marking where the signature will go. After you select Add signature, the Results preview is rendered from signed.pdf. Move the box and run again if the placement needs adjusting.' },
    ],
  },
];
