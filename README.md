Multi-Agent Retrieval-Augmented Generation for Decision Support over Heterogeneous Data
===============================================================

Overview
--------

This project was developed as a master's thesis to build a decision support system (DSS) using retrieval-augmented generation (RAG) and a multi-agent architecture for working with heterogeneous data.

The project was developed at Università degli Studi di Camerino (UNICAM).

System dependencies (native packages)
------------------------------------
This project requires three system-level libraries/tools:

- Tesseract
- libmagic
- Poppler

Install — macOS (Homebrew)

```bash
brew update
brew install tesseract poppler libmagic
```

Install — Debian / Ubuntu

```bash
sudo apt update
sudo apt install -y tesseract-ocr libmagic1 poppler-utils
```

Verify installations

```bash
tesseract --version
file --version
pdftoppm -v
```

Environment variables
---------------------
Create a `.env` file in the repository root with the following variables:

```dotenv
OPENAI_API_KEY=your-openai-api-key
TAVILY_API_KEY=your-tavily-api-key
LANGFUSE_BASE_URL=your-langfuse-base-url
LANGFUSE_PUBLIC_KEY=your-langfuse-public-key
LANGFUSE_SECRET_KEY=your-langfuse-secret-key
```

`OPENAI_API_KEY` is required. `TAVILY_API_KEY` is optional and is only needed when using web search. `LANGFUSE_BASE_URL`, `LANGFUSE_PUBLIC_KEY`, and `LANGFUSE_SECRET_KEY` are optional and are only needed when running a Langfuse container.

Data
---------------
The repository requires a `data/` folder. Download the example data from https://drive.google.com/file/d/18a44ETWxMM1cIzs-RszawNcIgbX0nTn5/view?usp=sharing and place it in the repository's `data/` folder. This data was used during evaluation.

evaluation results can be downloaded from https://drive.google.com/file/d/1r1NpOM1Qnj0v7-jMNUegEy8liG4aCNvB/view?usp=sharing

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

3. Start the FastAPI backend from the repository root. `api.py` exposes the FastAPI app as `app`, so launch it with Uvicorn:

```bash
uvicorn api:app --reload --host 0.0.0.0 --port 8000
```

The API listens on http://localhost:8000.

4. In another terminal, activate the same virtual environment and run the ingestion CLI when you need to load a PDF:

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
The container keeps dependencies and the built frontend in the image, while the cloned repository is mounted from the host. Changes to `.env` and `data/` are available after restarting the container without copying files into it.

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

Common Docker Compose commands:

```bash
# Show running services
docker compose ps

# Follow application logs
docker compose logs -f

# Stop and remove the containers
docker compose down
```

Run the ingestion CLI using a PDF from the host repository:

```bash
docker compose run --rm --entrypoint python app cli.py load /app/path/to/document.pdf
```

References
----------
- Tesseract OCR: https://github.com/tesseract-ocr/tesseract
- Poppler utils: https://poppler.freedesktop.org/
