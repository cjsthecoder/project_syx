# Morpheus AGI Chatbot Framework

A modular system that provides a web-based chat interface backed by a FastAPI server and LangChain for LLM integration.

## Project Structure

```
morpheus/
├── backend/                # FastAPI + LangChain backend
│   ├── app/
│   │   ├── main.py         # FastAPI entry point
│   │   ├── api/            # API route definitions
│   │   ├── core/           # Core logic and abstractions
│   │   └── utils/          # Shared utilities
│   ├── tests/              # Unit tests
│   └── requirements.txt    # Python dependencies
├── frontend/               # React + Shadcn/UI frontend
│   ├── src/
│   │   ├── components/     # Reusable UI components
│   │   ├── pages/          # Page-level containers
│   │   ├── hooks/          # Custom React hooks
│   │   └── api/            # API client
│   ├── public/             # Static assets
│   └── package.json        # NPM dependencies
├── docs/                   # Documentation
│   ├── REQUIREMENTS.md     # Requirements file
│   └── ARCHITECTURE.md     # High-level design
└── README.md               # This file
```

## Quick Start

### Backend Setup

1. Create and activate virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # macOS/Linux
   # or
   venv\Scripts\activate    # Windows
   ```

2. Install dependencies:
   ```bash
   cd backend
   pip install -r requirements.txt
   ```

3. Set environment variables:
   ```bash
   export OPENAI_API_KEY="your-api-key-here"
   export MODEL_NAME="gpt-4o-mini"  # optional, defaults to gpt-4o-mini
   ```

4. Run the server:
   ```bash
   uvicorn app.main:app --reload
   ```

### Frontend Setup

1. Install dependencies:
   ```bash
   cd frontend
   npm install
   ```

2. Start development server:
   ```bash
   npm run dev
   ```

## Features

- **Chat Interface**: Web-based chat UI built with React and Shadcn/UI
- **Backend API**: FastAPI server with LangChain integration
- **LLM Support**: OpenAI GPT-4o-mini (extensible to other providers)
- **Stubbed Features**: Ready for future RAG, memory pruning, and multi-project support

## Documentation

See `docs/REQUIREMENTS.md` for detailed specifications and requirements.

## Version 1 Goals

- Establish working chatbot with GUI and stable backend interfaces
- Extensible architecture for future enhancements
- Clean separation between frontend and backend
- LangChain abstraction for LLM providers
