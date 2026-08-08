# LeadCRM — AI-Powered B2B Lead Generation

A full-stack CRM tool that generates real B2B leads using **Serper** (Google Search API) and **Firecrawl** (website scraping), stores them in **MongoDB**, and displays them in a clean React dashboard.

Select an industry category → click Generate → the backend calls `leadgen.py` which searches Google, scrapes company websites, and returns structured lead data to the UI.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React 19, Vite 8, Tailwind CSS |
| Backend | FastAPI (Python), Uvicorn |
| Database | MongoDB (Motor async driver) |
| Lead Pipeline | `leadgen.py` → Serper API + Firecrawl API |
| Linting | Oxlint |

---

## Project Structure

```
Lead_Generation_Hermes_Agent/
│
├── src/                          # React frontend
│   ├── components/               # UI components (table, buttons, search bar…)
│   ├── pages/LeadGeneration.jsx  # Main page
│   ├── hooks/useGenerateLeads.js # API state management hook
│   ├── services/api.js           # All fetch calls (single source of truth)
│   └── config/categories.js     # Industry categories config
│
├── backend/
│   ├── app/
│   │   ├── main.py               # FastAPI app entry point
│   │   └── services/
│   │       └── hermes_service.py # Calls leadgen.py subprocess → returns leads
│   ├── src/
│   │   ├── config/               # Settings, MongoDB connection
│   │   ├── routes/leads.py       # All API endpoints
│   │   ├── controllers/          # Business logic
│   │   ├── models/               # Domain models
│   │   └── schemas/              # Pydantic request/response DTOs
│   ├── requirements.txt
│   └── .env.example              # Copy to .env and fill in values
│
├── public/
├── index.html
├── package.json
└── vite.config.js
```

---

## Prerequisites

- **Node.js** v18+
- **Python** 3.11+
- **MongoDB** running locally on port 27017
- **LeadGeneration toolkit** — `leadgen.py` with Serper + Firecrawl API keys configured

### Install MongoDB

Download from [mongodb.com/try/download/community](https://www.mongodb.com/try/download/community) and start:

```bash
mongod
```

---

## Setup

### 1. Clone the repo

```bash
git clone https://github.com/your-username/Lead_Generation_Hermes_Agent.git
cd Lead_Generation_Hermes_Agent
```

### 2. Frontend — install dependencies

```bash
npm install
```

### 3. Backend — create virtual environment and install dependencies

```bash
cd backend
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate

pip install -r requirements.txt
```

### 4. Backend — configure environment variables

Create `backend/.env` (copy from the template below):

```env
APP_NAME="Lead Generation CRM"
APP_VERSION="1.0.0"

PORT=8001

# Comma-separated allowed frontend origins
CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173

# MongoDB connection string
MONGODB_URI=mongodb://127.0.0.1:27017/crm

# Path to leadgen.py (override if installed elsewhere)
# LEADGEN_SCRIPT=C:\path\to\your\LeadGeneration\tools\leadgen.py
```

### 5. Configure `leadgen.py` path

Open `backend/app/services/hermes_service.py` and update `_default_script` to point to your `leadgen.py`:

```python
_default_script = r"C:\Users\YourName\LeadGeneration\tools\leadgen.py"
```

Or set the `LEADGEN_SCRIPT` environment variable in `.env` instead.

> `leadgen.py` requires its own `.env` with `SERPER_API_KEY` and `FIRECRAWL_API_KEY`.  
> Get keys at [serper.dev](https://serper.dev) and [firecrawl.dev](https://www.firecrawl.dev).

---

## Running the Project

Open **two terminals**.

**Terminal 1 — Backend**

```bash
cd backend
venv\Scripts\activate           # Windows
# source venv/bin/activate      # macOS / Linux

venv\Scripts\uvicorn app.main:app --port 8001 --reload
```

Backend starts at `http://localhost:8001`  
API docs available at `http://localhost:8001/docs`

**Terminal 2 — Frontend**

```bash
# from project root
npm run dev
```

Frontend starts at `http://localhost:5173`

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/leads/generate-leads` | Run Hermes pipeline, upsert to MongoDB, return leads |
| `GET` | `/leads` | List all stored leads (paginated, searchable) |
| `GET` | `/leads/categories` | List all industry categories |
| `POST` | `/leads` | Manually create a lead |
| `GET` | `/leads/{id}` | Get a single lead |
| `PATCH` | `/leads/{id}` | Update a lead |
| `DELETE` | `/leads/{id}` | Delete a lead |
| `GET` | `/debug/database` | MongoDB connectivity + document count |
| `GET` | `/health` | App health status |

---

## How Lead Generation Works

```
User clicks "Generate Leads"
  │
  ├─ POST /leads/generate-leads  { industry, city, count }
  │
  ├─ Backend → hermes_service.py
  │     └─ Runs leadgen.py as subprocess (thread pool, platform-safe)
  │           ├─ Serper API  →  Google search results for the query
  │           └─ Firecrawl   →  Scrapes each company website for contacts
  │
  ├─ Results normalised → upserted into MongoDB (deduped by website)
  │
  └─ MongoDB documents returned to frontend → rendered in leads table
```

Lead generation takes **30–120 seconds** depending on the number of results and how many websites respond to scraping. The UI shows a live status spinner while waiting.

---

## Industry Categories

Real Estate · IT · Software · Healthcare · Education · Manufacturing · E-Commerce · Finance · Marketing · Logistics

Add or remove categories by editing `src/config/categories.js` — the UI updates automatically.

---

## Environment Variables Reference

### `backend/.env`

| Variable | Default | Description |
|----------|---------|-------------|
| `APP_NAME` | `Lead Generation CRM` | App display name |
| `PORT` | `8001` | Uvicorn listen port |
| `CORS_ORIGINS` | `http://localhost:5173` | Allowed frontend origins (comma-separated) |
| `MONGODB_URI` | `mongodb://127.0.0.1:27017/crm` | MongoDB connection string |
| `LEADGEN_SCRIPT` | *(hardcoded fallback)* | Absolute path to `leadgen.py` |

---

## Common Issues

**502 Bad Gateway on Generate Leads**  
→ `leadgen.py` path is wrong or the script errored. Check backend terminal for `[leadgen]` output.

**Cannot reach the server**  
→ Backend not running, or port mismatch. Confirm `api.js` `BASE_URL` matches the port uvicorn is listening on.

**MongoDB connection failed**  
→ `mongod` is not running. Start MongoDB before starting the backend.

**Port already in use**  
→ Kill the existing process: `netstat -ano | findstr :8001` then `taskkill /PID <pid> /F`

---

## License

MIT
