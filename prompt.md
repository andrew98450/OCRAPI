請根據提供的 openai.yaml 建立 OCR RESTful API。

要求：

- 使用 Python 3.12
- 使用 FastAPI
- 使用 Pydantic v2
- 完全遵循 openai.yaml
- 不可修改任何 API Contract
- 不可自行優化 API 結構
- 不做非必要重構
- 僅補齊缺失實作

OCR：
- 使用 Pytesseract + Pillow
- 回傳辨識文字

部署：
- Docker

輸出：

- 專案資料夾結構
- main.py
- routers/*
- schemas/*
- services/*
- Dockerfile
- requirements.txt

請直接提供可執行程式碼，不要只提供範例。

所有程式碼需可直接部署執行。

輸入驗證規範：

1. Content-Type 驗證
   - 僅允許：
     - image/jpeg
     - image/png
     - image/webp
     - application/pdf

2. 檔案大小驗證
   - 單一檔案最大 20MB
   - 超過限制回傳 413

3. 檔案存在驗證
   - 未上傳檔案回傳 400

4. 檔名驗證
   - 禁止空檔名
   - 禁止特殊控制字元

5. Request Body 驗證
   - 使用 Pydantic v2 Model
   - 欄位格式不符回傳 422

6. OCR 結果驗證
   - 回傳字串不可為 null
   - 若辨識失敗回傳空字串而非 null