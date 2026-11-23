Multi-Agent Retrieval-Augmented Generation for Decision Support over Heterogeneous Data
===============================================================

Overview
--------

This project was developed as a master's thesis to build a decision support system (DSS) using retrieval-augmented generation (RAG) and a multi-agent architecture for working with heterogeneous data.

The project was developed at Università degli Studi di Camerino (UNICAM).

Environment variables
---------------------
Create a `.env` file in the repository root with the following variables:

```dotenv
OPENAI_API_KEY=your-openai-api-key
LLAMA_CLOUD_API_KEY=your-llama-cloud-api-key
TAVILY_API_KEY=your-tavily-api-key
LANGFUSE_BASE_URL=your-langfuse-base-url
LANGFUSE_PUBLIC_KEY=your-langfuse-public-key
LANGFUSE_SECRET_KEY=your-langfuse-secret-key
JWT_SECRET_KEY=replace-with-a-long-random-secret
COOKIE_SECURE=false
POSTGRES_DSN=postgresql://user:password@host:port/dbname
CROSS_ENCODER_DEVICE=cpu
```

`OPENAI_API_KEY` is required for the language models and cloud embeddings. `LLAMA_CLOUD_API_KEY` is required to ingest and parse PDFs. `TAVILY_API_KEY` is optional and is only needed for web search.

`LANGFUSE_BASE_URL`, `LANGFUSE_PUBLIC_KEY`, and `LANGFUSE_SECRET_KEY` are optional and only needed when Langfuse tracing is enabled. `JWT_SECRET_KEY` defaults to an insecure development value, so set it to a long random value outside local development. Set `COOKIE_SECURE=true` when serving over HTTPS; it defaults to `false`.

`POSTGRES_DSN` is required for application data, parent/child chunks, dense embeddings, BM25 search, and conversation checkpoints. Restore `data/db.sql`, which includes the extensions, chunk tables, indexes, and retrieval view. LangGraph checkpoint tables are created automatically.

`CROSS_ENCODER_DEVICE`, possible values: `cpu`, `mps`, `cuda`. By default, it is configured as `cpu`. For Apple, Macbook, use `mps`. For Nvidia GPU use `cuda`.

Data
---------------
The repository requires a `data/` folder containing spatial data, PDFs/image assets, and the PostgreSQL dump. Download the example data from https://drive.google.com/file/d/1SO9ZI0xqpJzpHQYQTDmxbj7YmzLDdWF-/view?usp=sharing and place the contents in the repository's `data/` folder. This data was used during evaluation.

Evaluation results can be downloaded from <TODO ADD URL>

Quickstart (Python)
--------------------
1. Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

2. Install Python dependencies:

```bash
pip install -r requirements.txt
```

3. Use PostgreSQL 17 with pgvector 0.8.x and pg_search 0.26.x installed. Add `pg_search` to `shared_preload_libraries` and restart PostgreSQL. Restore the complete backup and set `POSTGRES_DSN` in `.env`:

```bash
createdb dss
psql --dbname dss --set ON_ERROR_STOP=1 --file data/db.sql
```

4. Start the FastAPI backend from the repository root. `api.py` exposes the FastAPI app as `app`, so launch it with Uvicorn:

```bash
uvicorn api:app --reload --host 0.0.0.0 --port 8000
```

The API listens on http://localhost:8000.

5. Documents can be ingested from the frontend UI and CLI. To ingest a document from CLI run:

```bash
python cli.py load /path/to/document.pdf
```

To display CLI help:

```bash
python cli.py --help
```

Quickstart (Vue)
---------------------
The frontend is a Vue application served by Vite. From the repository root:

```bash
cd frontend
npm install
npm run dev
```

Open the URL printed by Vite, usually http://localhost:5173. The Vite development proxy forwards `/api` requests to the backend at http://localhost:8000, so keep the backend running in a separate terminal.

For a production build:

```bash
npm run build
```

Docker
------
Before the first start, create `.env` and place the downloaded `data` inside the project dir.

From the repository root, build and start the application with:

```bash
docker compose up --build
```

The application is available at http://localhost:8080. Press `Ctrl+C` to stop it.

If the images have already been built, start the application without rebuilding:

```bash
docker compose up
```

To run the application in detached mode, add the `-d` option:

```bash
docker compose up -d
```

The application image contains the Python dependencies and built frontend. The repository is mounted at `/app`. Python reads the mounted `.env` file each time the backend starts, so after editing `.env`, apply the changes with:

```bash
docker compose restart app
```

Compose sets `POSTGRES_DSN` to the bundled PostgreSQL service, overriding the value in `.env`. To change the database used by Docker, edit `POSTGRES_DSN` in `docker-compose.yml` and recreate the app with `docker compose up -d --force-recreate app`.

Backend source and data changes are available through the mount; restart the app to reload backend code. Changes to the frontend, Python dependencies, Dockerfile, or files under `docker/` require rebuilding with `docker compose up -d --build app`.

Nginx allows request bodies up to 51 MiB to accommodate the backend's default 50 MiB PDF limit and multipart overhead. If you increase `MAX_UPLOAD_SIZE_BYTES` in `config.py`, also increase `client_max_body_size` in `docker/nginx.conf` and rebuild the app image.

Docker serves the application over HTTP by default. For a public server deployment, configure HTTPS with a TLS certificate through a reverse proxy in front of port 8080. Set `COOKIE_SECURE=true` in `.env` and run `docker compose restart app` after enabling HTTPS.

Common Docker Compose commands:

```bash
# Show running services
docker compose ps

# Follow application logs
docker compose logs -f

# Stop and remove the containers
docker compose down
```

To discard the PostgreSQL volume and import `data/db.sql` again on the next start:

```bash
docker compose down --volumes
docker compose up --build
```

`docker compose down --volumes` permanently deletes the database stored in the Compose volume. Create a fresh dump first if it contains changes you need to keep.

To restore a new dump without deleting the volume, ensure the dump is compatible with the existing schema and run `psql` explicitly. A full dump normally expects an empty database, so recreating the volume is the simplest development workflow.

References: [pgvector](https://github.com/pgvector/pgvector), [ParadeDB index creation](https://www.paradedb.com/docs/reference/indexing/create-index), [match queries](https://www.paradedb.com/docs/reference/full-text/match), [BM25 scoring](https://www.paradedb.com/docs/reference/full-text/score), and [installation](https://www.paradedb.com/docs/start/install).
