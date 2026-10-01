from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse

ROOT = Path(__file__).parent
app = FastAPI(title="Broken Shop — BugPilot fixture")


@app.get("/")
async def home():
    return FileResponse(ROOT / "index.html")


@app.get("/checkout")
async def checkout():
    return FileResponse(ROOT / "checkout.html")


@app.api_route("/api/broken", methods=["GET", "POST"])
async def broken():
    return JSONResponse({"error": "payment processor exploded"}, status_code=500)


@app.get("/health")
async def health():
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=4173)
