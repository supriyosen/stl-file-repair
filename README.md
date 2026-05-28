# Local STL Repair

A reusable local STL repair workflow for meshes that fail in Bambu Studio with errors such as non-manifold edges, open boundaries, duplicate triangles, or broken normals.

## Run The Web App

```bash
source .venv/bin/activate
uvicorn app:app --reload --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`, drop in an STL, click **Repair STL**, then download the repaired STL from the page.

## Command Line

Analyze a file:

```bash
.venv/bin/python repair_stl.py path/to/model.stl --analyze-only --pretty
```

Repair a file:

```bash
.venv/bin/python repair_stl.py path/to/model.stl -o path/to/model_repaired.stl --pretty
```

## What It Fixes

- Welds duplicate/coincident vertices.
- Removes degenerate and duplicate triangles.
- Reorients inconsistent normals.
- Fills simple holes.
- Uses MeshFix to reconstruct a printable manifold when the mesh has open boundaries or non-manifold edges.

## Notes For AI-Generated Meshes

Tripo/image-to-3D meshes often contain internal shells, tiny disconnected fragments, and open folds. Keep **MeshFix manifold repair** enabled for normal use. If a repair removes details you wanted to preserve, retry with **Remove small components** turned off.

## Vercel Deployment

This project includes `vercel.json` and `api/index.py` for Vercel's Python runtime. Vercel is convenient for sharing the UI, but large STL repair jobs may hit serverless upload, memory, or duration limits. For production-heavy repair workloads, use a container host for the backend and keep Vercel as the frontend.

## Large File Deployment

Vercel Functions cannot accept 100 MB+ mesh uploads directly. Deploy the included Docker backend to a container host, then set this Vercel environment variable:

```bash
EXTERNAL_REPAIR_API_URL=https://your-container-backend.example.com
```

The frontend will keep using Vercel, but Analyze and Repair will send files to the external backend. `render.yaml` and `Dockerfile` are included for a Render-style container deployment.
