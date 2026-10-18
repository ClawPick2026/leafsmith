import { buildNativeRequest } from './native-model.ts';
import type { NativeFile, NativeResult, ComponentStatus } from './native-model.ts';
export type Invoke = <T>(command: string, args?: Record<string, unknown>) => Promise<T>;
export function createNativeClient(invoke: Invoke, available: () => boolean) {
  async function call<T>(command: string, args?: Record<string, unknown>): Promise<T> {
    if (!available()) throw new Error('Native tools require the installed Paperwork Desktop app. Browser tools still work in this preview.');
    return invoke<T>(command, args);
  }
  return {
    selectInputs: () => call<NativeFile[]>('select_inputs'),
    run: (operation: string, inputIds: string[], options: Record<string, unknown>) => call<NativeResult>('run_native_job', buildNativeRequest(operation, inputIds, options)),
    save: (outputId: string) => call<boolean>('save_output', {outputId}),
    status: () => call<ComponentStatus[]>('component_status'),
    install: (componentId: string) => call<ComponentStatus>('install_component', {componentId}),
  };
}
