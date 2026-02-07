from fastapi import FastAPI, HTTPException, status, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import List, Dict, Optional
import sqlite3
import time
import datetime
import uvicorn

app = FastAPI(title="TEKNOFEST 2025 Savaşan İHA Sunucusu")

# --- VERİTABANI BAŞLATMA ---
def get_db():
    conn = sqlite3.connect('yarisma_verileri.db', check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()
    # Telemetri Tablosu (Bölüm 7)
    cursor.execute('''CREATE TABLE IF NOT EXISTS telemetri (
        takim_no INTEGER, enlem REAL, boylam REAL, irtifa REAL,
        dikilme REAL, yonelme REAL, yatis REAL, hiz REAL, 
        batarya REAL, otonom INTEGER, kilitlenme INTEGER, sunucu_saati_ms INTEGER)''')
    # Kilitlenme Tablosu (Bölüm 8)
    cursor.execute('''CREATE TABLE IF NOT EXISTS kilitlenmeler (
        takim_no INTEGER, bitis_saati TEXT, otonom_mu INTEGER)''')
    # Kamikaze Tablosu (Bölüm 9)
    cursor.execute('''CREATE TABLE IF NOT EXISTS kamikaze (
        takim_no INTEGER, baslangic_saati TEXT, bitis_saati TEXT, qr_metni TEXT)''')
    # Takım Tanımları (Bölüm 5)
    cursor.execute("CREATE TABLE IF NOT EXISTS takimlar (kadi TEXT, sifre TEXT, takim_no INTEGER)")
    cursor.execute("INSERT OR IGNORE INTO takimlar VALUES ('rota_takim', 'parola123', 1)")
    conn.commit()
    conn.close()

init_db()

# --- BELLEKTE TAKİP ---
aktif_oturumlar = {}  # {takim_no: son_islem_zamani}
son_telemetri_zamanlari = {} # {takim_no: ms_timestamp}

# --- MODELLER (Pydantic) ---
class SaatModel(BaseModel):
    saat: int; dakika: int; saniye: int; milisaniye: int

class TelemetriModel(BaseModel):
    takim_numarasi: int; iha_enlem: float; iha_boylam: float; iha_irtifa: float
    iha_dikilme: float; iha_yonelme: float; iha_yatis: float; iha_hiz: float
    iha_batarya: float; iha_otonom: int; iha_kilitlenme: int
    hedef_merkez_X: int; hedef_merkez_Y: int; hedef_genislik: int; hedef_yukseklik: int
    gps_saati: SaatModel

# --- YARDIMCI FONKSİYONLAR ---
def mevcut_sunucu_saati():
    n = datetime.datetime.now()
    return {
        "gun": n.day, "saat": n.hour, "dakika": n.minute,
        "saniye": n.second, "milisaniye": n.microsecond // 1000
    } #

# --- API UÇ NOKTALARI ---

@app.post("/api/giris") # Bölüm 5
async def giris(data: Dict):
    conn = get_db()
    res = conn.execute("SELECT takim_no FROM takimlar WHERE kadi=? AND sifre=?",
                       (data.get("kadi"), data.get("sifre"))).fetchone()
    if res:
        takim_no = res['takim_no']
        aktif_oturumlar[takim_no] = time.time()
        return takim_no # 200 OK + Takım Numarası
    raise HTTPException(status_code=400) # 400 Hatalı Giriş

@app.get("/api/sunucusaati") # Bölüm 6
async def sunucu_saati():
    return mevcut_sunucu_saati()

@app.post("/api/telemetri_gonder") # Bölüm 7
async def telemetri_gonder(data: TelemetriModel):
    # Oturum Kontrolü (401)
    if data.takim_numarasi not in aktif_oturumlar:
        raise HTTPException(status_code=401)
    
    # Frekans Kontrolü (Hata Kodu 3)
    simdi_ms = int(time.time() * 1000)
    if data.takim_numarasi in son_telemetri_zamanlari:
        if (simdi_ms - son_telemetri_zamanlari[data.takim_numarasi]) < 500:
            return JSONResponse(status_code=400, content=3)
    
    # Veri Aralığı Doğrulama (204)
    if not (-90 <= data.iha_dikilme <= 90) or not (0 <= data.iha_yonelme <= 360) or not (-90 <= data.iha_yatis <= 90):
        raise HTTPException(status_code=204)

    # Veritabanı Kaydı
    conn = get_db()
    conn.execute("INSERT INTO telemetri VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                 (data.takim_numarasi, data.iha_enlem, data.iha_boylam, data.iha_irtifa,
                  data.iha_dikilme, data.iha_yonelme, data.iha_yatis, data.iha_hiz,
                  data.iha_batarya, data.iha_otonom, data.iha_kilitlenme, simdi_ms))
    conn.commit()
    son_telemetri_zamanlari[data.takim_numarasi] = simdi_ms

    # Diğer Takımların Konumları (Bölüm 7.3)
    rows = conn.execute("SELECT * FROM telemetri WHERE takim_no != ? GROUP BY takim_no HAVING MAX(sunucu_saati_ms)",
                        (data.takim_numarasi,)).fetchall()
    konumlar = [{
        "takim_numarasi": r['takim_no'], "iha_enlem": r['enlem'], "iha_boylam": r['boylam'],
        "iha_irtifa": r['irtifa'], "iha_dikilme": r['dikilme'], "iha_yonelme": r['yonelme'],
        "iha_yatis": r['yatis'], "iha_hizi": r['hiz'], "zaman_farki": simdi_ms - r['sunucu_saati_ms']
    } for r in rows]

    return {"sunucusaati": mevcut_sunucu_saati(), "konumBilgileri": konumlar}

@app.post("/api/kilitlenme_bilgisi") # Bölüm 8
async def kilitlenme_bilgisi(data: Dict):
    if data.get("takim_numarasi") not in aktif_oturumlar: raise HTTPException(status_code=401)
    conn = get_db()
    conn.execute("INSERT INTO kilitlenmeler VALUES (?,?,?)",
                 (data.get("takim_numarasi"), str(data.get("kilitlenmeBitisZamani")), data.get("otonom_kilitlenme")))
    conn.commit()
    return status.HTTP_200_OK

@app.post("/api/kamikaze_bilgisi") # Bölüm 9
async def kamikaze_bilgisi(data: Dict):
    if data.get("takim_numarasi") not in aktif_oturumlar: raise HTTPException(status_code=401)
    conn = get_db()
    conn.execute("INSERT INTO kamikaze VALUES (?,?,?,?)",
                 (data.get("takim_numarasi"), str(data.get("kamikazeBaslangicZamani")),
                  str(data.get("kamikazeBitisZamani")), data.get("qrMetni")))
    conn.commit()
    return status.HTTP_200_OK

@app.get("/api/qr_koordinati") # Bölüm 10
async def qr_koordinati():
    return {"qrEnlem": 41.51238882, "qrBoylam": 36.11935778}

@app.get("/api/hss_koordinatlari") # Bölüm 11
async def hss_koordinatlari():
    # Hakemler aktif etmediyse boş liste döner
    return {"sunucusaati": mevcut_sunucu_saati(), "hss_koordinat_bilgileri": []}

if __name__ == "__main__":
    # Dökümandaki gerçek sunucu formatına göre güncellendi
    uvicorn.run(app, host="localhost", port=5000)
