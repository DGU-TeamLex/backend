"""모듈 A — 데이터 인테이크 업로드 API (이슈 #20, 1단계).

기존에는 XLSX 적재가 로컬 CLI(`scripts/import_ssis_dataset.py`) 직접 실행으로만
가능했다. 이 라우터는 웹에서 XLSX 를 업로드받아 OWASP File Upload Cheat Sheet
기준(확장자 화이트리스트·크기 상한·매직바이트·zip bomb 방지)으로 검증한 뒤,
`import_batches` 에 "RECEIVED"(처리 대기) 배치 이력을 남긴다.

이 초안의 범위는 **업로드 접수 + 검증 + 배치 기록**까지다. 실제 행 파싱과
표준화 매칭 엔진(자유텍스트 물품명 → 표준코드, 이슈 #20 항목 3·4)은 임베딩
인프라가 필요해 후속 범위로 남겨둔다 — 접수된 배치를 후속 처리가 갱신하는 것을
전제로 한다.
"""
import io
import uuid
import zipfile

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from auth.deps import require_role
from db import queries as DB

router = APIRouter(prefix="/api/v1")

T_INTAKE = ["데이터 인테이크"]

# 업로드는 전국 마스터를 바꾸는 행위라 CENTRAL 전용
_central_only = Depends(require_role("CENTRAL"))

# --- OWASP File Upload 검증 상수 (기술검토 문서 과제 D) ---
_ALLOWED_EXTS = (".xlsx",)
_ALLOWED_CONTENT_TYPES = {
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/octet-stream",  # 일부 클라이언트가 붙이는 폴백 타입 허용
}
_ZIP_MAGIC = b"PK\x03\x04"                      # XLSX 는 OOXML=ZIP 컨테이너
# Vercel 서버리스 함수는 요청 본문이 플랫폼 하드리밋(약 4.5MB)을 넘으면 FastAPI 코드가
# 실행되기도 전에 413 FUNCTION_PAYLOAD_TOO_LARGE 로 막는다(이슈 #27). 따라서 기존 20MB
# 상한은 사실상 도달 불가능한 죽은 값이었다. 코드 상한을 플랫폼 하드리밋보다 살짝 아래로
# 두어, 한계에 근접한 파일은 Vercel 기본 오류 페이지 대신 아래 _reject 의 명확한 422 안내를
# 받도록 한다. 그보다 큰 실데이터(예: SSIS 원본 46.9MB)는 서버리스 본문을 거치지 않는 업로드
# 경로(오브젝트 스토리지 직접 업로드 등)로 전환해야 한다 — 근본 해결은 후속 범위.
_VERCEL_BODY_LIMIT_BYTES = 4_500_000            # Vercel 서버리스 함수 요청 본문 하드리밋(≈4.5MB)
_MAX_UPLOAD_BYTES = 4 * 1024 * 1024             # 코드 상한 4MB — 플랫폼 하드리밋 아래 안전 마진
_MAX_UNCOMPRESSED_BYTES = 200 * 1024 * 1024     # 압축 해제 총량 상한(zip bomb 방지)
_MAX_COMPRESSION_RATIO = 200                     # 엔트리별 압축비 상한(zip bomb 방지)


def _reject(msg: str):
    # 클라이언트 입력 문제이므로 422 로 통일(검증 실패)
    raise HTTPException(status_code=422, detail=msg)


@router.post("/imports", tags=T_INTAKE, summary="XLSX 업로드 → 검증 → 적재 배치 접수")
async def create_import(
    file: UploadFile = File(..., description="SSIS 물품 입출고 XLSX 파일"),
    sourceVendor: str | None = Form(default=None, description="제공처(예: SSIS)"),
    _admin: dict = _central_only,
):
    # 1) 확장자 화이트리스트
    name = (file.filename or "").strip()
    if not name.lower().endswith(_ALLOWED_EXTS):
        _reject("허용되지 않는 파일 형식입니다. .xlsx 만 업로드할 수 있습니다.")

    # 2) content-type 보조 검사(신뢰하지 않되 명백한 불일치는 거른다)
    if file.content_type and file.content_type not in _ALLOWED_CONTENT_TYPES:
        _reject(f"허용되지 않는 content-type 입니다: {file.content_type}")

    # 3) 본문 읽기 + 원본 크기 상한
    raw = await file.read()
    if not raw:
        _reject("빈 파일입니다.")
    if len(raw) > _MAX_UPLOAD_BYTES:
        _reject(
            f"파일이 너무 큽니다(현재 {len(raw) / (1024 * 1024):.1f}MB, 최대 "
            f"{_MAX_UPLOAD_BYTES // (1024 * 1024)}MB). 이 업로드 경로는 Vercel 서버리스 함수의 "
            f"요청 본문 하드리밋(약 {_VERCEL_BODY_LIMIT_BYTES // 1_000_000}MB) 안에서만 동작합니다 — "
            "더 큰 파일은 오브젝트 스토리지 직접 업로드 경로가 준비되면 그쪽을 이용하세요."
        )

    # 4) 매직 바이트 — 확장자를 신뢰하지 않고 실제 컨테이너를 확인
    if not raw.startswith(_ZIP_MAGIC):
        _reject("XLSX(ZIP) 시그니처가 아닙니다. 실제 .xlsx 파일인지 확인하세요.")

    # 5) ZIP 구조 검증 + XLSX 구성요소 확인 + zip bomb 방지
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            if zf.testzip() is not None:
                _reject("손상된 ZIP/XLSX 파일입니다.")
            names = zf.namelist()
            if "[Content_Types].xml" not in names or not any(n.startswith("xl/") for n in names):
                _reject("XLSX 내부 구조가 아닙니다(워크북 구성요소 없음).")
            total_uncompressed = 0
            for info in zf.infolist():
                total_uncompressed += info.file_size
                if total_uncompressed > _MAX_UNCOMPRESSED_BYTES:
                    _reject("압축 해제 용량이 상한을 초과했습니다(zip bomb 의심).")
                if info.compress_size > 0 and info.file_size / info.compress_size > _MAX_COMPRESSION_RATIO:
                    _reject("비정상적으로 높은 압축비가 감지됐습니다(zip bomb 의심).")
    except zipfile.BadZipFile:
        _reject("XLSX(ZIP) 파일을 열 수 없습니다.")

    # 6) 검증 통과 — 처리 대기 배치로 접수 기록(후속 매칭 엔진이 갱신)
    batch_id = f"imp_{uuid.uuid4().hex[:12]}"
    batch = DB.record_import_batch(
        import_batch_id=batch_id,
        file_name=name,
        source_vendor=sourceVendor,
        status="RECEIVED",
    )
    return {
        "importBatch": batch,
        "message": "업로드가 접수되어 검증을 통과했습니다. 표준화 매칭·적재는 후속 처리로 진행됩니다.",
    }
