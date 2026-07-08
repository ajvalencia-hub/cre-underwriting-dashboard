import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_ROOT / ".env")
STORAGE_ROOT = BACKEND_ROOT / "storage"
TEMPLATES_DIR = STORAGE_ROOT / "templates"
GENERATED_DIR = STORAGE_ROOT / "generated"
DOCUMENTS_DIR = STORAGE_ROOT / "documents"
DB_DIR = STORAGE_ROOT / "db"
# CRE_DB_PATH override exists for test harnesses (e.g. the Playwright smoke
# boots the API against a scratch database).
DB_PATH = Path(os.environ.get("CRE_DB_PATH") or DB_DIR / "app.sqlite3")

for d in (TEMPLATES_DIR, GENERATED_DIR, DOCUMENTS_DIR, DB_DIR):
    d.mkdir(parents=True, exist_ok=True)

DATA_DIR = BACKEND_ROOT / "app" / "data"
INPUT_SCHEMA_PATH = DATA_DIR / "input_schema.json"

CORS_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

# Free public-data API keys — all optional. Each data_sources/*.py module
# degrades gracefully (returns dataSource: "unavailable") when its key is
# unset, so the app runs fine with none of these configured. See
# backend/.env.example for signup links.
CENSUS_API_KEY = os.environ.get("CENSUS_API_KEY", "")
BLS_API_KEY = os.environ.get("BLS_API_KEY", "")  # optional — BLS works unauthenticated at low volume
BEA_API_KEY = os.environ.get("BEA_API_KEY", "")
FRED_API_KEY = os.environ.get("FRED_API_KEY", "")
HUD_API_TOKEN = os.environ.get("HUD_API_TOKEN", "")

# Nominatim (OpenStreetMap) usage policy requires an identifying User-Agent.
GEOCODE_USER_AGENT = "CRE-Underwriting-Dashboard/1.0 (local dev)"

# IC memo branding — override in backend/.env for your shop.
FIRM_NAME = os.environ.get("FIRM_NAME", "Acme Real Estate Partners")
MEMO_BRAND_COLOR = os.environ.get("MEMO_BRAND_COLOR", "1F3B57")  # hex, no '#'

# Anthropic API — optional. Used as a fallback for ambiguous document-type
# classification and (in a later milestone) structured data extraction from
# messy/narrative documents. Degrades gracefully to heuristic-only results
# when unset. Free-tier public data sources above have nothing to do with
# this key; it's billed Anthropic API usage, unlike everything else in this
# file. See backend/.env.example.
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_CLASSIFIER_MODEL = os.environ.get("ANTHROPIC_CLASSIFIER_MODEL", "claude-haiku-4-5-20251001")
# Structured extraction is a harder task than classification, so it defaults
# to a stronger model.
ANTHROPIC_EXTRACTION_MODEL = os.environ.get("ANTHROPIC_EXTRACTION_MODEL", "claude-sonnet-5")

# OpenAI API — optional, billed usage. Only used by the Underwriting Agent
# (see app/services/agent/) when AGENT_PROVIDER=openai. Degrades the same
# way the Anthropic key does: missing key -> agent reports itself as
# unavailable rather than erroring.
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_AGENT_MODEL = os.environ.get("OPENAI_AGENT_MODEL", "gpt-5.1")

# Underwriting Agent (K0-K12 build) — which provider drives the agent chat.
# Both Anthropic and OpenAI adapters are implemented; this just picks which
# one is live. Falls back to a small/cheap default per provider so the
# agent works out of the box once a key is set.
AGENT_PROVIDER = os.environ.get("AGENT_PROVIDER", "anthropic")
ANTHROPIC_AGENT_MODEL = os.environ.get("ANTHROPIC_AGENT_MODEL", "claude-sonnet-5")

# Ollama (M2) — local, no key required (the spec's own security note: local
# needs no key). Defaults to the standard local install; override if Ollama
# runs elsewhere (a remote box, a different port).
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_AGENT_MODEL = os.environ.get("OLLAMA_AGENT_MODEL", "llama3.1")
