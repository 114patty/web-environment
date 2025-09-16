# 基本 Python 環境
FROM python:3.10-slim

# 工作目錄
WORKDIR /app

# 安裝依賴
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 複製程式碼
COPY . .

# 對外開放 port 7860 (HF 預設)
EXPOSE 7860

# 啟動 Flask
CMD ["python", "app.py"]
