"""Mock Ollama server for local testing.

Usage:
  cd backend
  uv run uvicorn tools.mock_ollama:app --port 11435

Then test:
  curl http://127.0.0.1:11435/api/version
  curl http://127.0.0.1:11435/api/tags
  curl -XPOST http://127.0.0.1:11435/api/show -H 'Content-Type: application/json' -d '{"name":"llama3.2:latest"}'
"""

from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="Mock Ollama")


@app.get("/api/version")
def version():
    return {"version": "0.1.48"}


@app.get("/api/tags")
def tags():
    return {
        "models": [
            {
                "name": "llama3.2:latest",
                "modified_at": "2026-02-15T00:00:00Z",
                "size": 1234567890,
                "digest": "sha256:deadbeef",
                "details": {"format": "gguf", "family": "llama", "parameter_size": "3B", "quantization_level": "Q4_K_M"},
            },
            {
                "name": "nomic-embed-text:latest",
                "modified_at": "2026-02-15T00:00:00Z",
                "size": 234567890,
                "digest": "sha256:cafebabe",
                "details": {"format": "gguf", "family": "bert", "parameter_size": "137M", "quantization_level": "Q8_0"},
            },
        ]
    }


class ShowReq(BaseModel):
    name: str


@app.post("/api/show")
def show(req: ShowReq):
    if req.name == "llama3.2:latest":
        return {
            "license": "LLAMA",
            "modelfile": "FROM llama3.2\nPARAMETER temperature 0.7",
            "parameters": "temperature 0.7",
            "template": "{{ .Prompt }}",
            "details": {"format": "gguf", "family": "llama", "parameter_size": "3B", "quantization_level": "Q4_K_M"},
        }
    return {
        "license": "unknown",
        "modelfile": "",
        "parameters": "",
        "template": "",
        "details": {},
    }
