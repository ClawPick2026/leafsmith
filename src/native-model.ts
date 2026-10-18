export type NativeFile = { id: string; name: string; size: number; pathHint: string };
export type NativeOutput = { id: string; name: string; mime: string; size: number };
export type ComponentStatus = { id: string; name: string; installed: boolean; version?: string; description: string; downloadBytes?: number; error?: string };
export type NativeResult = { outputs: NativeOutput[]; details: Record<string, unknown> };
export const nativeOperations = ['inspect_pdf', 'annotate_pdf', 'edit_pdf_text', 'convert_to_pdf', 'convert_from_pdf', 'ocr_pdf', 'ocr_image', 'form_template', 'protect_pdf', 'unlock_pdf', 'remove_watermark', 'compress_pdf', 'summarize', 'translate_pdf', 'transcribe', 'compress_video', 'enhance_image'] as const;
export type NativeOperation = typeof nativeOperations[number];
/** Font choice that omits `font`, so the worker keeps the text object's original font. */
export const KEEP_ORIGINAL_FONT = 'Keep original font';
const isGrantId = (id: unknown) => typeof id === 'string' && !!id && !id.includes('/') && !id.includes('\\') && !id.includes(':') && !id.includes(String.fromCharCode(0));
// Empty or cleared optional number fields mean "use the worker default".
const blankNumber = (value: unknown) => value === undefined || value === '' || value === 0 || (typeof value === 'number' && !Number.isFinite(value));
export function localModelOptions(provider: string, modelId: string | null, components: ComponentStatus[]): Record<string, unknown> {
  if (!['whisper.cpp', 'llama.cpp'].includes(provider)) return {};
  if (modelId) return {model_file_id:modelId};
  const id=provider==='whisper.cpp'?'whisper_model':'llama_model';
  if (components.some(component=>component.id===id && component.installed===true)) return {};
  throw new Error('Select or download a local model first.');
}
export function buildNativeRequest(operation: string, inputIds: string[], options: Record<string, unknown>) {
  if (!(nativeOperations as readonly string[]).includes(operation)) throw new Error('Unknown native operation.');
  if (!inputIds.length && operation !== 'form_template') throw new Error('Select native input files first.');
  if (!inputIds.every(isGrantId)) throw new Error('Use granted file IDs, not paths.');
  if (['summarize', 'translate_pdf', 'transcribe'].includes(operation) && options.provider && !['ollama', 'local', 'llama.cpp', 'whisper.cpp'].includes(String(options.provider)) && options.cloud_consent !== true) {
    throw new Error('Explicit cloud consent is required for this job.');
  }
  const params = { ...options };
  if (!['summarize', 'translate_pdf', 'transcribe'].includes(operation)) delete params.cloud_consent;
  if (['whisper.cpp', 'llama.cpp', 'local'].includes(String(params.provider))) {
    delete params.endpoint;
    delete params.api_key;
  }
  if (operation === 'edit_pdf_text') {
    if (params.font === KEEP_ORIGINAL_FONT || params.font === '') delete params.font;
    if (blankNumber(params.font_size)) delete params.font_size;
  }
  if (operation === 'remove_watermark') {
    if (blankNumber(params.page)) delete params.page;
    if (params.exact_text === '') delete params.exact_text;
    if (params.annotation_subtype === 'None' || params.annotation_subtype === '') delete params.annotation_subtype;
    if (!('exact_text' in params) && !('annotation_subtype' in params)) throw new Error('Enter the exact watermark text or an annotation type to remove.');
  }
  if (operation !== 'translate_pdf') delete params.font_file_id;
  else if ('font_file_id' in params && !isGrantId(params.font_file_id)) throw new Error('Use granted file IDs, not paths.');
  return { request: { operation, inputIds: [...inputIds], options: params } };
}
