import { defineConfig } from '@playwright/test';
export default defineConfig({testDir:'./e2e',testMatch:'phase2*.spec.ts',timeout:45000,reporter:[['list'],['json',{outputFile:'../docs/phase-2-browser-report.json'}]],fullyParallel:false,use:{baseURL:'http://127.0.0.1:8000',browserName:'chromium',channel:'msedge',headless:true,viewport:{width:1440,height:1000},screenshot:'only-on-failure'}});
