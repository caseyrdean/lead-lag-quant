"""Lead-Lag Quant — FastAPI server entry point.

Run with:
    uv run python main.py
or:
    uv run uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
"""
import uvicorn
from dotenv import load_dotenv

load_dotenv()


def main():
    uvicorn.run(
        "api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
    )


if __name__ == "__main__":
    main()
