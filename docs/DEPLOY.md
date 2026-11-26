# Deploying and configuration

## Environment variables

| Variable | Where | Purpose |
| --- | --- | --- |
| `VITE_BACKEND_URL` | frontend `.env.local` | API base URL, default `http://localhost:8000` |
| `VITE_MAP_TILE_URL`, `VITE_MAP_TILE_ATTRIBUTION` | frontend, optional | Authorised public-browser tile URL template and required provider attribution. Set both to enable a basemap |
| `VITE_EVENTS_API_URL` | frontend, optional | External events feed. Leave unset to hide events |
| `VITE_EVENTS_DEMO` | frontend, optional | Set to `true` to show labelled sample events in place of the external feed |
| `CORS_ORIGINS` | backend | Comma-separated allowed origins, default `http://localhost:5173,http://127.0.0.1:5173` |
| `OPENAI_API_KEY`, `OPENAI_MODEL` | backend, optional | Live explanations, model defaults to `gpt-4o-mini` |

Copy `backend/.env.example` to `backend/.env` and `frontend/fire_website/.env.example` to `.env.local`.

## Backend on Render

`render.yaml` defines the service. Set `CORS_ORIGINS` to your frontend URL, for example `https://<your-frontend-host>` (the exact origin, no trailing slash). If it is unset, the API only accepts requests from localhost, the browser blocks the deployed frontend, and the API logs a startup warning.

## Frontend on Vercel

Set the project root to `frontend/fire_website` and `VITE_BACKEND_URL` to the Render URL, then redeploy.

The default map uses the bundled Glasgow ward boundaries and requires no basemap key. To add a street basemap, use a provider-approved browser tile URL and its required attribution. Values prefixed with `VITE_` are included in the browser build. Use only public or origin-restricted provider credentials intended for browser use.

## Publishing the demo (checklist)

No hosted URL is recorded in this repository: add one only after the smoke check below passes.

1. Render: create a Blueprint from `render.yaml`. Leave `OPENAI_API_KEY` unset; explanations use the built-in templates. Note the service URL.
2. Vercel: project root `frontend/fire_website`, env `VITE_BACKEND_URL` = the Render URL, then deploy. Note the frontend URL.
3. Render: set `CORS_ORIGINS` to the exact frontend origin and redeploy the API.
4. Run the smoke check (below). Open the frontend in a private window, switch Mock and Model, click a ward and press Explain.
5. Only then add the URL to the README "Live demo" section and the repository homepage field (repository Settings, or `gh repo edit --homepage <url>`).

The free Render tier sleeps when idle, so the first request can take about a minute.

## Read-only smoke check

```bash
python scripts/smoke_check.py --api https://<api-host> --frontend https://<frontend-host>
```

It only issues GET and OPTIONS requests and needs no credentials. It checks API liveness, that the model is loaded, 23 wards for both Model and Mock, a working explanation (template fallback is accepted), that the frontend serves its app shell, and that CORS allows the frontend origin. It exits non-zero on failure. `--frontend` is optional.

## Liveness and model-data readiness

- `GET /api/health` is liveness only (the process is up). It is the Render health check, so missing data does not restart-loop the service.
- `GET /api/ready` validates the committed model data and returns 200 with `mode: "model"`, or 503 with `mode: "degraded"` and a `problems` list when an artefact is missing or malformed. `GET /api/status` also reports `data_mode`.
- Set `FIRE_SIGHT_MOCK_MODE=1` to run the demo deliberately on sample data: `/api/ready` then returns 200 with `mode: "mock"` (problems, if any, are still listed), so it is distinguishable from a failed load.
