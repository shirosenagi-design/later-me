# CALL-E Ocean web interface

This directory contains the frozen React/TypeScript/Vite interface for CALL-E.
It uses real DOM controls and relative `/api` requests. During development,
Vite proxies `/api` to `http://127.0.0.1:8787` unless `VITE_API_TARGET` is set.

For the product concept, safe isolated backend startup, architecture, and known
submission gaps, see the [repository README](../README.md).

```powershell
npm ci
npm run dev
```

Available checks are `npm run lint` and `npm run build`. For isolated QA, set
`VITE_CALL_E_QA_INSTANCE_ID` to the same non-secret instance ID used by the
Python bridge before starting Vite.
