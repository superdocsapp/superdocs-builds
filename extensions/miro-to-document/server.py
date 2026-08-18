from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse


app = FastAPI(
    title="SuperDocs Miro Document Server"
)


OUTPUT_DIR = (
    Path(__file__).resolve().parent / "output"
)


@app.get("/")
def home():
    return {
        "message": "SuperDocs Miro document server is running",
        "document": "/miro_document.html"
    }


@app.get("/miro_document.html")
def get_document():
    document = OUTPUT_DIR / "miro_document.html"

    if not document.exists():
        return {
            "error": "Generated document not found"
        }

    return FileResponse(
        document,
        media_type="text/html"
    )


@app.get("/images/{filename}")
def get_image(filename: str):
    image = OUTPUT_DIR / "images" / filename

    if not image.exists():
        return {
            "error": "Image not found"
        }

    return FileResponse(
        image
    )