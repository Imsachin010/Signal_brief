# SignalBrief

Real-time notification triage and digest demo using context-aware delivery rules with optional AI-powered classification.

## Overview

SignalBrief is a proof-of-concept demonstrating a context-aware notification delivery system that:

- **Triage notifications** based on urgency and signal quality
- **Hold/deliver/defer** messages based on user availability and network conditions
- **Generate AI-powered summaries** (digests) of held notifications
- **Provide voice briefings** using text-to-speech for urgent messages
- **Suggest replies** to messages using AI

The core concept: hold low-value notifications during busy moments, then release one clean summarized brief when the context improves.

## Architecture

```
┌─────────────┐     ┌─────────────┐
│   Frontend  │────▶│   Backend   │
│   (React)   │◀────│  (FastAPI)  │
└─────────────┘     └─────────────┘
                            │
                            ▼
                     ┌─────────────┐
                     │   AI APIs   │
                     │ (Sarvam/    │
                     │  Groq)      │
                     └─────────────┘
```

## Prerequisites

- **Backend**: Python 3.14+, uv (package manager)
- **Frontend**: Node.js 18+, npm

## Quick Start

### 1. Clone and Setup

```bash
git clone <repository-url>
cd SignalBrief
```

### 2. Backend Setup

```bash
cd backend
uv sync
```

Create a `.env` file in the project root:

```bash
cp .env_example .env
# Edit .env with your actual API keys
```

### 3. Run Backend

```bash
uv run uvicorn backend.main:app --reload
```

The API runs at `http://127.0.0.1:8000`

### 4. Frontend Setup

Open a new terminal:

```bash
cd frontend
npm install
npm run dev
```

The UI runs at `http://localhost:5173` (default Vite port)

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `AI_PROVIDER_MODE` | No | AI provider: `sarvam` (default) or `fallback` |
| `SARVAM_API_KEY` | If mode=sarvam | Sarvam AI API key |
| `SARVAM_MODEL` | No | Sarvam model: `sarvam-105b` (default) or `sarvam-30b` |
| `GROQ_API_KEY` | No | Groq API key for reply suggestions |
| `GROQ_MODEL` | No | Groq model for suggestions |

### Using .env File

Create `.env` in the project root:

```bash
AI_PROVIDER_MODE=sarvam
SARVAM_API_KEY=your_sarvam_api_key_here
SARVAM_MODEL=sarvam-105b
GROQ_API_KEY=your_groq_api_key_here
GROQ_MODEL=openai/gpt-oss-120b
```

Or set via environment variables:

```bash
export SARVAM_API_KEY=your_key_here
export GROQ_API_KEY=your_key_here
```

## Configuration Priority

The backend reads secrets in this order:
1. Process environment variables (highest priority)
2. Project-local `.env` file

## Testing

### Backend Tests

```bash
python3 -m unittest discover -s backend/tests -v
```

### Manual API Testing

```bash
# Health check
curl http://127.0.0.1:8000/

# Get messages
curl http://127.0.0.1:8000/messages

# Trigger digest
curl -X POST http://127.0.0.1:8000/digest
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Health check |
| GET | `/messages` | Get all messages |
| POST | `/release` | Release a held message |
| POST | `/digest` | Generate AI digest |
| POST | `/voice-brief` | Generate voice briefing |
| POST | `/reply` | Generate reply suggestions |

## Project Structure

```
SignalBrief/
├── backend/
│   ├── main.py          # FastAPI app & routes
│   ├── controller.py   # Business logic
│   ├── ai_service.py   # AI classification/digest
│   ├── domain.py        # Domain models
│   ├── rule_engine.py   # Delivery rules
│   └── tests/           # Unit tests
├── frontend/
│   ├── src/
│   │   ├── App.tsx     # Main React app
│   │   ├── types.ts    # TypeScript types
│   │   └── styles.css  # Styling
│   └── package.json
├── .env_example        # Environment template
├── pyproject.toml      # Python config
└── README.md
```

## Features

- **Real-time message simulation** with various sender types
- **Context-aware delivery** - holds/defers based on signal quality
- **AI digest generation** - summarizes held notifications
- **Voice briefing** - TTS for urgent messages
- **Smart reply suggestions** - AI-generated responses
- **Dashboard UI** - Control room + phone preview

## License

MIT