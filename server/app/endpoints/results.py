import logging

from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/_results")
async def submit_results(request: Request):
    body = await request.json()
    test_id = body.get("test_id")
    outcome = body.get("outcome")

    if test_id not in request.app.state.active_tests:
        logger.warning(f"Received results for unknown test {test_id}")
        raise HTTPException(status_code=404, detail=f"Test {test_id} not found")

    test_info = request.app.state.active_tests.get(test_id)
    if test_info and "future" in test_info:
        if not test_info["future"].done():
            test_info["future"].set_result(outcome)
        else:
            logger.warning(f"Test {test_id} future already completed")

    return {"status": "accepted", "test_id": test_id}
