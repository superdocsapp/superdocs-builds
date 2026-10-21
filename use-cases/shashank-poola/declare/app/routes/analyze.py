from fastapi import APIRouter
from pydantic import ValidationError

from llm.glm import GLMError, analyze_with_glm
from prompts.declare import build_analyze_messages
from routes.errors import failure
from schemas.declare import AnalysisProviderResponse, AnalyzeRequest
from utils.analysis import validate_analysis

router = APIRouter()


@router.post("/analyze")
async def analyze(input_: AnalyzeRequest):
    try:
        provider = AnalysisProviderResponse.model_validate(await analyze_with_glm(build_analyze_messages(input_.model_dump())))
        return {"success": True, "data": validate_analysis(input_, provider), "error": None}
    except ValidationError as error:
        return failure(400, "INVALID_ANALYZE_REQUEST_OR_GLM_RESPONSE", error.errors())
    except GLMError as error:
        return failure(503, "GLM_PROVIDER_NOT_CONFIGURED") if str(error) == "GLM_PROVIDER_NOT_CONFIGURED" else failure(502, "DECLARE_ANALYSIS_FAILED")
    except Exception:
        return failure(400, "INVALID_ANALYZE_REQUEST_OR_GLM_RESPONSE")
