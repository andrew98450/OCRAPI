# OCR Recognition Service API

依 `openai.yaml`（OpenAPI 3.1.0）實作的 OCR RESTful 服務。

- Python 3.12
- FastAPI
- Pydantic v2
- Pytesseract + Pillow
- Docker（包含 Tesseract 語言包與 Poppler）

API 路徑、request/response schema 完全依照 `openai.yaml`，未變更任何既有路徑或欄位。

## 專案結構

```
OCRAPI/
├── main.py                  # FastAPI 入口（建立 app、掛載 routers、lifespan）
├── config.py                # 環境變數設定
├── routers/
│   ├── __init__.py
│   ├── deps.py              # 共用 dependency 與 response 轉換
│   ├── ocr.py               # POST /ocr/jobs、/ocr/url、/ocr/base64、/ocr/pdf
│   │                        # GET  /ocr/jobs/{jobId}/result|blocks|tables
│   ├── jobs.py              # GET /ocr/jobs、GET/DELETE /ocr/jobs/{jobId}
│   └── export.py            # GET /ocr/jobs/{jobId}/export/{txt,json,docx,pdf}
├── schemas/
│   ├── __init__.py
│   ├── jobs.py              # JobStatus / JobResponse / JobStatusResponse / JobListResponse
│   ├── ocr.py               # OCRResult / OCRBlock / BlockResponse / OCRTable / TableResponse
│   └── requests.py          # /ocr/url、/ocr/base64 的 Pydantic v2 request model
├── services/
│   ├── __init__.py
│   ├── auth.py              # BearerAuth（OpenAPI security scheme）
│   ├── callback.py          # callback_url 完成通知
│   ├── export_service.py    # TXT / JSON / DOCX / 可搜尋 PDF 產生
│   ├── fetcher.py           # /ocr/url 遠端圖片下載與驗證
│   ├── ocr_service.py       # OCR 流程（Pytesseract + Pillow、blocks、tables）
│   ├── storage.py           # 檔案儲存（20MB 限制）
│   ├── store.py             # Job 狀態儲存（in-memory、TTL 過期）
│   └── validators.py        # Content-Type、檔名、magic bytes 驗證
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .dockerignore
└── README.md
```

## 啟動方式

### Docker

```bash
docker compose up --build
# 或
docker build -t ocr-api .
docker run --rm -p 8000:8000 -e API_TOKEN=secret ocr-api
```

Swagger UI：<http://localhost:8000/docs>

### 本機（需自行安裝 Tesseract 與 Poppler）

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows
# source .venv/bin/activate       # Linux/macOS
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1
```

> Job 狀態儲存在單一 process 的記憶體中，因此請固定使用 **1 個 worker**
> （`--workers 1`）。多 worker 會導致建立 job 的 process 與查詢的 process 不一致。

## 環境變數

| 變數 | 預設值 | 說明 |
| --- | --- | --- |
| `API_TOKEN` | （未設定） | 設定後 Bearer token 必須相符；未設定時任何非空 Bearer token 都接受（開發用） |
| `STORAGE_DIR` | `./storage` | 上傳檔與暫存檔目錄 |
| `DEFAULT_OCR_LANGUAGE` | `eng` | 未指定 language 或語言包不存在時的預設語言 |
| `DEFAULT_OCR_ENGINE` | `tesseract` | 未指定 engine 時的預設值 |
| `PDF_DPI` | `200` | PDF 頁面轉圖解析度 |
| `MAX_PDF_PAGES` | `100` | 單一 PDF 最多處理頁數 |
| `JOB_TTL_SECONDS` | `86400` | 完成後保留時間，逾時狀態變為 `expired` |
| `HTTP_TIMEOUT_SECONDS` | `60` | `/ocr/url` 下載逾時 |
| `TESSERACT_CMD` | （未設定） | 自訂 tesseract 執行檔路徑 |
| `LOG_LEVEL` | `INFO` | 日誌等級 |

## API

| Method | Path | 說明 |
| --- | --- | --- |
| POST | `/ocr/jobs` | 上傳圖片/PDF 建立 OCR job（multipart/form-data） |
| GET | `/ocr/jobs` | 列出 jobs（`page`、`page_size`、`status`） |
| POST | `/ocr/url` | 以圖片 URL 建立 job |
| POST | `/ocr/base64` | 以 Base64 圖片建立 job |
| POST | `/ocr/pdf` | 上傳 PDF 建立 job（`pages` 可指定頁碼） |
| GET | `/ocr/jobs/{jobId}` | 查詢狀態與進度 |
| DELETE | `/ocr/jobs/{jobId}` | 刪除 job 與其檔案 |
| GET | `/ocr/jobs/{jobId}/result` | OCR 結果 |
| GET | `/ocr/jobs/{jobId}/blocks` | OCR 文字區塊（含 bbox） |
| GET | `/ocr/jobs/{jobId}/tables` | 表格結果 |
| GET | `/ocr/jobs/{jobId}/export/txt` | 匯出純文字 |
| GET | `/ocr/jobs/{jobId}/export/json` | 匯出 JSON |
| GET | `/ocr/jobs/{jobId}/export/docx` | 匯出 DOCX |
| GET | `/ocr/jobs/{jobId}/export/pdf` | 匯出可搜尋 PDF |

建立 job 一律回傳 `202 Accepted` 與 `JobResponse`（`job_id`、`status`、`created_at`），
之後以 `GET /ocr/jobs/{jobId}` 輪詢，`status` 為 `completed` 或 `failed` 後可取得結果。

`/ocr/base64` 在 `openai.yaml` 未宣告 response body，本實作爲了讓 client 能取得
`job_id` 輪詢，回傳與其他建立端點相同的 `JobResponse`（僅新增內容，未變更既有契約）。

### 範例

```bash
curl -X POST http://localhost:8000/ocr/jobs \
  -H "Authorization: Bearer secret" \
  -F "file=@sample.png" \
  -F "language=chi_tra" \
  -F "detect_table=true"

curl -H "Authorization: Bearer secret" \
  http://localhost:8000/ocr/jobs/<job_id>/result

curl -OJ -H "Authorization: Bearer secret" \
  http://localhost:8000/ocr/jobs/<job_id>/export/pdf
```

## 輸入驗證

| 規則 | 行為 |
| --- | --- |
| Content-Type | 僅接受 `image/jpeg`、`image/png`、`image/webp`、`application/pdf`，否則 `415` |
| 檔案內容 | 以 magic bytes 驗證，與宣告的 Content-Type 不符回 `415` |
| 檔案大小 | 單檔上限 20MB，超過回 `413`；空檔案回 `400` |
| 檔案存在 | 未上傳 `file` 欄位回 `400` |
| 檔名 | 空白檔名或含控制字元（含 multipart 編碼後的 `%00`–`%1F`、`%7F`）回 `400` |
| JSON body | 以 Pydantic v2 驗證（`image_url` 為 URI、`image_base64` 需為合法 Base64 且為允許的圖片格式），格式錯誤回 `422` |
| multipart 欄位 | `engine` enum、`callback_url` URI、`page`/`page_size` 型別錯誤回 `422` |
| OCR 文字 | 一定為字串；辨識失敗時 job 為 `failed`，`result.text` 回空字串 `""`（不為 `null`） |

## 實作說明

- **非同步處理**：建立 job 後以 FastAPI `BackgroundTasks` 在背景執行 OCR，
  client 立即拿到 `202`，再用 `GET /ocr/jobs/{jobId}` 輪詢 `progress`（0–100）。
- **OCR 引擎**：`engine` 欄位接受 `paddleocr`、`tesseract`、`azure`，但目前部署只
  內建 Tesseract（依規格使用 Pytesseract + Pillow）；其他值仍會以 Tesseract 處理。
- **語言**：`language` 支援 `chi_tra`、`eng`、`chi_tra+eng` 等寫法；若語言包未安裝，
  自動退回 `DEFAULT_OCR_LANGUAGE`（Docker 內含 `eng`、`chi_tra`、`chi_sim`）。
- **confidence**：採 Tesseract 原生 0–100 刻度，取所有辨識詞的平均值。
- **layout analysis**：`detect_layout=true` 時 blocks 以段落（Tesseract block）為單位，
  否則以行為單位；`bbox` 為該區塊的外接矩形。
- **table extraction**：`detect_table=true` 時，依 tab、連續兩個以上空格或 `|` 分欄，
  將連續兩列以上的內容輸出為 `OCRTable`。
- **可搜尋 PDF**：對每個頁面重新執行 OCR，產生帶隱藏文字層的 PDF（多頁以 pypdf 合併）。
- **callback**：`callback_url` 於 job 完成或失敗後以 JSON POST 通知
  （`job_id`、`status`、`progress`、`created_at`、`completed_at`、`error`），失敗僅記錄日誌。
- **過期**：完成或失敗的 job 超過 `JOB_TTL_SECONDS` 後狀態變為 `expired` 並清除檔案；
  查詢結果／區塊／表格在 job 尚未完成時回 `409`、已過期回 `410`、不存在回 `404`。
  匯出僅限 `completed` 的 job（`failed` job 可取得空字串結果，但匯出回 `409`）。
