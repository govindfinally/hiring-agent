import hashlib
import logging
import os
import sqlite3
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
import uvicorn

from score import main as evaluate_resume

load_dotenv()

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

APP_ROOT = Path(__file__).resolve().parent
RATE_LIMIT_DB = APP_ROOT / "rate_limits.sqlite3"

FREE_TIER_DAILY_LIMIT = int(os.getenv("FREE_TIER_DAILY_LIMIT", "3"))
RATE_LIMIT_WINDOW = f"{FREE_TIER_DAILY_LIMIT}/day"

app = FastAPI(
    title="Hiring Agent API",
    version="1.0.0",
    description="HTTP endpoints for resume extraction and scoring in the hiring-agent project.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

limiter = Limiter(key_func=get_remote_address, default_limits=[])
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


class EvaluateRequest(BaseModel):
    pdf_path: str = Field(..., description="Absolute or relative path to the PDF to evaluate")


def _ensure_runtime_environment() -> None:
    llm_provider = os.getenv("LLM_PROVIDER", "ollama").lower()
    if llm_provider == "gemini":
        gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
        if not gemini_key:
            raise RuntimeError(
                "Missing GEMINI_API_KEY. Add it to your .env file before starting the service."
            )


def _ensure_rate_limit_table() -> None:
    with sqlite3.connect(RATE_LIMIT_DB) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS rate_limits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ip_hash TEXT NOT NULL,
                reset_date TEXT NOT NULL,
                request_count INTEGER NOT NULL DEFAULT 0,
                UNIQUE(ip_hash, reset_date)
            )
            """
        )
        connection.commit()


def _hash_ip(ip_address: str) -> str:
    return hashlib.sha256(ip_address.encode("utf-8")).hexdigest()


def _check_rate_limit(request: Request) -> None:
    client_ip = request.client.host if request.client else "unknown"
    ip_hash = _hash_ip(client_ip)
    current_day = date.today().isoformat()

    with sqlite3.connect(RATE_LIMIT_DB) as connection:
        row = connection.execute(
            "SELECT request_count FROM rate_limits WHERE ip_hash = ? AND reset_date = ?",
            (ip_hash, current_day),
        ).fetchone()

        if row is None:
            connection.execute(
                "INSERT INTO rate_limits(ip_hash, reset_date, request_count) VALUES (?, ?, 1)",
                (ip_hash, current_day),
            )
            connection.commit()
            return

        request_count = int(row[0])
        if request_count >= FREE_TIER_DAILY_LIMIT:
            raise HTTPException(
                status_code=429,
                detail="Free limit reached, upgrade for unlimited checks",
            )

        connection.execute(
            "UPDATE rate_limits SET request_count = request_count + 1 WHERE ip_hash = ? AND reset_date = ?",
            (ip_hash, current_day),
        )
        connection.commit()


@app.on_event("startup")
def startup_event() -> None:
    _ensure_runtime_environment()
    _ensure_rate_limit_table()


@app.exception_handler(RateLimitExceeded)
async def rate_limit_exception_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={"detail": "Free limit reached, upgrade for unlimited checks"},
    )


def _run_evaluation(pdf_path: str) -> Dict[str, Any]:
    if not pdf_path:
        raise HTTPException(status_code=400, detail="pdf_path cannot be empty")

    resolved_path = Path(pdf_path).expanduser().resolve()
    if not resolved_path.exists():
        raise HTTPException(status_code=404, detail=f"file not found: {resolved_path}")

    if resolved_path.suffix.lower() != ".pdf":
        raise HTTPException(status_code=400, detail="only PDF files are supported")

    try:
        result = evaluate_resume(str(resolved_path))
    except Exception:
        logger.exception("resume evaluation failed")
        raise HTTPException(
            status_code=500,
            detail="resume evaluation failed",
        ) from None

    if result is None:
        raise HTTPException(
            status_code=400,
            detail="no evaluation was produced for the supplied file",
        )

    return {
        "status": "success",
        "pdf_path": str(resolved_path),
        "evaluation": result.model_dump(),
    }


@app.get("/")
def root() -> Dict[str, Any]:
    return {
        "service": "hiring-agent",
        "status": "ok",
        "endpoints": [
            "GET /health",
            "GET /info",
            "GET /evaluate?pdf_path=<path>",
            "POST /evaluate",
            "POST /evaluate-file",
        ],
    }


@app.get("/health")
def health() -> Dict[str, Any]:
    return {"status": "ok"}


@app.get("/info")
def info() -> Dict[str, Any]:
    return {
        "service": "hiring-agent",
        "version": "1.0.0",
        "description": "FastAPI wrapper around the existing resume-evaluation CLI pipeline.",
    }


@app.get("/evaluate")
@limiter.limit(RATE_LIMIT_WINDOW)
def evaluate_from_query(request: Request, pdf_path: str = Query(...)) -> Dict[str, Any]:
    _check_rate_limit(request)
    return _run_evaluation(pdf_path)


@app.post("/evaluate", status_code=status.HTTP_200_OK)
@limiter.limit(RATE_LIMIT_WINDOW)
def evaluate_from_body(request: Request, payload: EvaluateRequest) -> Dict[str, Any]:
    _check_rate_limit(request)
    return _run_evaluation(payload.pdf_path)


@app.post("/evaluate-file", status_code=status.HTTP_200_OK)
@limiter.limit(RATE_LIMIT_WINDOW)
def evaluate_uploaded_file(request: Request, uploaded_file: UploadFile = File(...)) -> Dict[str, Any]:
    _check_rate_limit(request)

    if not uploaded_file.filename or not uploaded_file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="uploaded file must be a PDF")

    suffix = Path(uploaded_file.filename).suffix or ".pdf"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_pdf:
        temp_pdf.write(uploaded_file.file.read())
        temp_pdf_path = temp_pdf.name

    try:
        return _run_evaluation(temp_pdf_path)
    finally:
        try:
            os.remove(temp_pdf_path)
        except OSError:
            logger.warning("failed to remove temporary file %s", temp_pdf_path)


def run(host: str = "0.0.0.0", port: int = 8000) -> None:
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run the hiring-agent FastAPI backend.")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host")
    parser.add_argument("--port", type=int, default=8000, help="Bind port")
    args = parser.parse_args()

    run(host=args.host, port=args.port)
