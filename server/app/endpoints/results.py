import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter()


class TestResults(BaseModel):
    test_id: str
    success: bool
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    duration: float = 0.0
    details: dict | None = None
    error: str | None = None


@router.post("/_results")
async def submit_results(request: Request, results: TestResults):
    test_id = results.test_id
    
    logger.info(f"Received results for test {test_id}: success={results.success}, "
                f"passed={results.passed}, failed={results.failed}")
    
    if test_id not in request.app.state.active_tests:
        logger.warning(f"Received results for unknown test {test_id}")
        raise HTTPException(status_code=404, detail=f"Test {test_id} not found")
    
    test_info = request.app.state.active_tests.get(test_id)
    if test_info and "future" in test_info:
        result_data = {
            "success": results.success,
            "passed": results.passed,
            "failed": results.failed,
            "skipped": results.skipped,
            "duration": results.duration,
            "details": results.details,
            "error": results.error,
        }
        
        if not test_info["future"].done():
            test_info["future"].set_result(result_data)
        else:
            logger.warning(f"Test {test_id} future already completed")
    
    return {"status": "accepted", "test_id": test_id}