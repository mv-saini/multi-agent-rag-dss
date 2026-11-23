from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from routers.auth import _require_authentication
from starlette.concurrency import run_in_threadpool
from core.seismic.planning import catalogue

router = APIRouter(
    prefix="/api/seismic", dependencies=[Depends(_require_authentication)]
)


@router.get("/faults")
async def fault_catalogue():
    try:
        return {"data": await run_in_threadpool(catalogue, include_geometry=True)}
    except (ValueError, OSError) as exc:
        return JSONResponse(status_code=422, content={"error": str(exc)})
