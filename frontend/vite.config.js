import {defineConfig} from 'vite';
const proxy={'/api':'http://127.0.0.1:8000','/admin':'http://127.0.0.1:8000'};
export default defineConfig({server:{proxy,port:5173,strictPort:true},preview:{proxy,port:5173,strictPort:true}});
