import shutil

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_session

router = APIRouter()

settings = get_settings()


def _check_tesseract() -> dict:
    tesseract_path = shutil.which(settings.tesseract_cmd)
    if tesseract_path is None:
        return {
            "available": False,
            "path": None,
            "message": "Tesseract OCR is not installed. Scanned PDFs and images will be processed without text extraction.",
        }
    try:
        import pytesseract
        pytesseract.pytesseract.tesseract_cmd = tesseract_path
        languages = pytesseract.get_languages(config="")
        return {
            "available": True,
            "path": tesseract_path,
            "languages": languages,
            "message": f"Tesseract OCR available with languages: {', '.join(languages) if languages else 'none'}",
        }
    except Exception as e:
        return {
            "available": False,
            "path": tesseract_path,
            "message": f"Tesseract binary found but not usable: {e}",
        }


def _check_libreoffice() -> dict:
    libreoffice_path = shutil.which("libreoffice")
    if libreoffice_path is None:
        return {
            "available": False,
            "path": None,
            "message": "LibreOffice is not installed. DOCX files will not be convertible to PDF.",
        }
    return {
        "available": True,
        "path": libreoffice_path,
        "message": "LibreOffice available for DOCX to PDF conversion.",
    }


@router.get("/health")
async def health_check():
    return {"status": "healthy", "service": "bates-exhibit-privilege-packet"}


@router.get("/health/db")
async def health_db(session: AsyncSession = Depends(get_session)):
    try:
        result = await session.execute(text("SELECT 1"))
        result.scalar()
        return {"status": "healthy", "database": "connected"}
    except Exception as e:
        return {"status": "unhealthy", "database": "disconnected", "error": str(e)}


@router.get("/health/dependencies")
async def health_dependencies():
    return {
        "status": "healthy",
        "tesseract": _check_tesseract(),
        "libreoffice": _check_libreoffice(),
    }