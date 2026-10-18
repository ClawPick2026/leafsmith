import { defineConfig } from 'vite';
import preact from '@preact/preset-vite';
import tailwind from '@tailwindcss/vite';
export default defineConfig({ plugins:[preact(),tailwind()], clearScreen:false, server:{strictPort:true}, build:{target:'es2022'}, envPrefix:['VITE_','TAURI_ENV_'] });
