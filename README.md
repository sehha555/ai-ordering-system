# 源飯糰 AI 語音點餐系統

這是一個使用 AI 進行語音點餐的系統原型。

## 安裝

```bash
# 建議使用 uv
pip install uv

# 安裝依賴
uv pip sync --all-features
```

## 執行

```bash
# 執行 Web 服務
uvicorn src.main:app --reload
```

## 運行測試

本專案包含單元測試、BDD 整合測試、契約測試與安全性測試。

```bash
# 運行所有測試 (使用簡潔模式)
uv run pytest -q
```

若要運行特定類型的測試，可以使用 markers:

```bash
# 只運行 BDD 測試
uv run pytest -m bdd

# 只運行安全性測試
uv run pytest -m security

# 只運行契約測試
uv run pytest -m contract
```
