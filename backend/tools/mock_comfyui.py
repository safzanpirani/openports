"""Mock ComfyUI server for local testing.

Runs a tiny HTTP server that mimics a few ComfyUI endpoints used by this project.

Usage:
  cd backend
  uv run uvicorn tools.mock_comfyui:app --port 18188

Then test:
  curl http://127.0.0.1:18188/system_stats
  curl http://127.0.0.1:18188/models
  curl http://127.0.0.1:18188/models/checkpoints
"""

from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(title="Mock ComfyUI")


@app.get("/")
def root():
    return "ComfyUI"  # simple string body


@app.get("/system_stats")
def system_stats():
    # Fields here are intentionally "best-effort"; real ComfyUI varies by version.
    return {
        "comfyui_version": "0.3.70",
        "os": "linux",
        "ram_total": 34359738368,
        "ram_free": 21474836480,
        "devices": [
            {
                "name": "NVIDIA GeForce RTX 4090",
                "type": "cuda",
                "vram_total": 25769803776,
                "vram_free": 19685266739,
            }
        ],
    }


@app.get("/models")
def models_root():
    return ["checkpoints", "loras", "vae", "controlnet"]


@app.get("/models/checkpoints")
def models_checkpoints():
    return ["sdxl.safetensors", "flux1-dev.safetensors"]


@app.get("/models/loras")
def models_loras():
    return ["add-detail.safetensors", "style.safetensors"]


@app.get("/models/vae")
def models_vae():
    return ["vae-ft-mse-840000-ema-pruned.safetensors"]


@app.get("/models/controlnet")
def models_controlnet():
    return ["control_v11p_sd15_openpose.safetensors"]
