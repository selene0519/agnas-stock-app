import json
import requests
import traceback

print("=== IMPORT APP ===")
import app
print("app import OK")

print("\n=== KIS CONFIG ===")
cfg = app.kis_config_v9960()
print("enabled:", cfg.get("enabled"))
print("base_url:", cfg.get("base_url"))

print("\n=== RAW KIS DOMESTIC QUOTE: 005930 ===")
try:
    headers = app.kis_headers_v9960("FHKST01010100")
    url = f"{cfg['base_url']}/uapi/domestic-stock/v1/quotations/inquire-price"
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": "005930",
    }

    res = requests.get(url, headers=headers, params=params, timeout=10)
    print("status_code:", res.status_code)

    data = res.json()
    print("rt_cd:", data.get("rt_cd"))
    print("msg_cd:", data.get("msg_cd"))
    print("msg1:", data.get("msg1"))

    output = data.get("output") or {}

    keys_to_check = [
        "stck_prpr",      # 현재가로 가장 의심되는 필드
        "prdy_vrss",
        "prdy_ctrt",
        "stck_oprc",
        "stck_hgpr",
        "stck_lwpr",
        "stck_mxpr",
        "stck_llam",
        "acml_vol",
        "acml_tr_pbmn",
        "stck_sdpr",
        "hts_kor_isnm",
        "stck_cntg_hour",
    ]

    print("\n--- important output fields ---")
    for k in keys_to_check:
        print(k, "=", output.get(k))

    print("\n--- all output keys ---")
    print(list(output.keys()))

except Exception as e:
    print("ERROR:", type(e).__name__, str(e))
    traceback.print_exc()


print("\n=== APP PARSED RESULT: 005930 ===")
try:
    r = app.fetch_kis_domestic_price_v9960("005930")
    print(json.dumps(r, ensure_ascii=False, indent=2))
except Exception as e:
    print("ERROR:", type(e).__name__, str(e))
    traceback.print_exc()
