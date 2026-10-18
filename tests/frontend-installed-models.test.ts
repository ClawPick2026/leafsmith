import {test} from 'node:test';
import assert from 'node:assert/strict';
import * as native from '../src/native-model.ts';

test('installed local models can be used without granting a second model file',()=>{
  const status=[{id:'whisper_model',name:'Whisper model',installed:true,description:'Verified local model'}];
  assert.deepEqual(native.localModelOptions('whisper.cpp',null,status),{});
  assert.throws(()=>native.localModelOptions('llama.cpp',null,status),/select|download/i);
});
test('selected model files take precedence over the downloaded default',()=>{
  assert.deepEqual(native.localModelOptions('llama.cpp','selected-model-id',[]),{model_file_id:'selected-model-id'});
});
test('missing or undetected model status never implies installed',()=>{
  assert.throws(()=>native.localModelOptions('whisper.cpp',null,[]),/select|download/i);
  assert.throws(()=>native.localModelOptions('whisper.cpp',null,[{id:'whisper_model',name:'model',installed:false,description:'Unavailable'}]),/select|download/i);
  assert.deepEqual(native.localModelOptions('ollama',null,[]),{});
});

test('PDF export choices expose the documented worker text, CSV, HTML and image formats',async()=>{
  const {nativeTools}=await import('../src/native-catalog.ts');
  const choices=nativeTools.find(tool=>tool.id==='convert_from_pdf')?.fields.find(field=>field.key==='format')?.choices??[];
  for(const format of ['docx','xlsx','pptx','txt','csv','html','png','jpeg']) assert.ok(choices.includes(format),`Missing ${format} export choice`);
});
