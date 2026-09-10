import {defineConfig} from 'vite';
const backend=process.env.CLINIC_BACKEND_URL||'http://127.0.0.1:8000';
const proxy={'/api':backend,'/admin':backend};
export default defineConfig({server:{proxy,port:5173,strictPort:true},preview:{proxy,port:5173,strictPort:true}});
