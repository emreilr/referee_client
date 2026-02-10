from fastapi import FastAPI, HTTPException, status, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field, validator
from typing import List, Dict, Optional
import sqlite3
import time
import datetime
import uvicorn
import json
import os

app = FastAPI(title="TEKNOFEST 2025 Savaşan İHA Sunucusu (Strict Mode)")

# --- VERİTABANI BAŞLATMA ---
def get_db():
    conn = sqlite3.connect('yarisma_verileri.db', check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS telemetri (
        takim_no INTEGER, enlem REAL, boylam REAL, irtifa REAL,
        dikilme REAL, yonelme REAL, yatis REAL, hiz REAL, 
        batarya REAL, otonom INTEGER, kilitlenme INTEGER, 
        hedef_merkez_X INTEGER, hedef_merkez_Y INTEGER, 
        hedef_genislik INTEGER, hedef_yukseklik INTEGER,
        gps_saati_ms INTEGER, sunucu_saati_ms INTEGER)''')
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS kilitlenmeler (
        takim_no INTEGER, baslangic_saati TEXT, bitis_saati TEXT, otonom_mu INTEGER)''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS kamikaze (
        takim_no INTEGER, baslangic_saati TEXT, bitis_saati TEXT, qr_metni TEXT)''')

    cursor.execute("CREATE TABLE IF NOT EXISTS takimlar (kadi TEXT, sifre TEXT, takim_no INTEGER)")
    
    # Takımları JSON dosyasından yükle
    try:
        if os.path.exists("teams.json"):
            with open("teams.json", "r") as f:
                teams = json.load(f)
                for team in teams:
                    cursor.execute("INSERT OR IGNORE INTO takimlar (kadi, sifre, takim_no) VALUES (?, ?, ?)",
                                   (team['kadi'], team['sifre'], team['takim_no']))
                print(f"{len(teams)} teams loaded from teams.json.")
        else:
            print("Warning: teams.json not found. Using default team.")
            cursor.execute("INSERT OR IGNORE INTO takimlar VALUES ('rota_takim', 'parola123', 1)")
    except Exception as e:
        print(f"Error loading teams: {e}")

    conn.commit()
    conn.close()

init_db()

# --- BELLEKTE TAKİP (IP TABANLI OTURUM) ---
# Döküman[cite: 17]: "Sisteme yalnızca belirtilen ip adresleri üzerinden bağlantıya izin verilecektir."
# Bu yüzden session yönetimini IP üzerinden yapıyoruz.
ip_session_map = {}  # { "127.0.0.1": takim_no }
son_telemetri_zamanlari = {} # {takim_no: ms_timestamp}

# --- MODELLER (Strict Validation) ---

class SaatModel(BaseModel):
    saat: int
    dakika: int
    saniye: int
    milisaniye: int

# Kilitlenme ve Kamikaze paketlerinde Takım No YOK 
class KilitlenmeModel(BaseModel):
    kilitlenmeBitisZamani: SaatModel
    otonom_kilitlenme: int # Dökümanda snake_case [cite: 182]

class KamikazeModel(BaseModel):
    kamikazeBaslangicZamani: SaatModel
    kamikazeBitisZamani: SaatModel
    qrMetni: str

class TelemetriModel(BaseModel):
    takim_numarasi: int # Telemetride Var [cite: 101]
    iha_enlem: float
    iha_boylam: float
    iha_irtifa: float
    iha_dikilme: float
    iha_yonelme: float
    iha_yatis: float
    iha_hiz: float
    iha_batarya: float
    iha_otonom: int
    iha_kilitlenme: int
    hedef_merkez_X: int
    hedef_merkez_Y: int
    hedef_genislik: int
    hedef_yukseklik: int
    gps_saati: SaatModel

# --- CUSTOM EXCEPTION HANDLERS (Dökümana Uyum) ---
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    # Döküman: "204: Gönderilen paketin Formatı Yanlış"
    # Pydantic bir model hatası (format hatası) yakalarsa 204 dönüyoruz.
    return JSONResponse(status_code=204, content={"detail": "Format Yanlış"})

# --- YARDIMCI FONKSİYONLAR ---
def mevcut_sunucu_saati():
    n = datetime.datetime.now()
    # Döküman [cite: 63-67]: Sunucu saatinde 'gun' var.
    return {
        "gun": n.day, "saat": n.hour, "dakika": n.minute,
        "saniye": n.second, "milisaniye": n.microsecond // 1000
    }

def format_time_str(t: SaatModel):
    return f"{t.saat}:{t.dakika}:{t.saniye}:{t.milisaniye}"

# --- API UÇ NOKTALARI ---

@app.post("/api/giris") # [cite: 45-57]
async def giris(data: Dict, request: Request):
    """
    Giriş başarılı olursa, İSTEĞİ YAPAN IP ADRESİ ile TAKIM NO eşleştirilir.
    """
    conn = get_db()
    res = conn.execute("SELECT takim_no FROM takimlar WHERE kadi=? AND sifre=?",
                       (data.get("kadi"), data.get("sifre"))).fetchone()
    if res:
        takim_no = res['takim_no']
        # IP'yi kaydet (Localhost testlerinde hepsi 127.0.0.1 olabilir, dikkat)
        client_ip = request.client.host
        ip_session_map[client_ip] = takim_no
        
        print(f"[GIRIS] IP: {client_ip} -> Takım: {takim_no}")
        return takim_no # 200 OK
    
    # [cite: 57] Kullanıcı adı/şifre geçersiz ise 400
    raise HTTPException(status_code=400, detail="Gecersiz kadi/sifre")

@app.get("/api/sunucusaati") # [cite: 58-68]
async def sunucu_saati():
    return mevcut_sunucu_saati()

@app.post("/api/telemetri_gonder") # [cite: 69-165]
async def telemetri_gonder(data: TelemetriModel, request: Request):
    # 1. Oturum Kontrolü (IP Bazlı)
    # Telemetri paketinde takım no olsa da güvenlik IP ile sağlanır [cite: 49]
    client_ip = request.client.host
    if client_ip not in ip_session_map:
        # [cite: 27] 401: Kimliksiz erişim
        raise HTTPException(status_code=401, detail="Oturum acilmadi")
    
    # 2. Takım Numarası Doğrulama
    # IP'deki takım ile paketteki takım uyuşuyor mu?
    # FIX: Localhost (127.0.0.1) testleri için IP çakışmasına izin ver
    # 2. Takım Numarası Doğrulama
    # DÜZELTME: Localhost testlerinde (aynı bilgisayarda) IP çakışmasını göz ardı et
    is_localhost = client_ip in ["127.0.0.1", "::1", "localhost"]
    
    if not is_localhost and ip_session_map[client_ip] != data.takim_numarasi:
         raise HTTPException(status_code=403, detail="IP ve Takim No uyusmuyor")
    # 3. Frekans Kontrolü [cite: 72]
    simdi_ms = int(time.time() * 1000)
    if data.takim_numarasi in son_telemetri_zamanlari:
        # 500ms'den daha sık gelirse (2 Hz üzeri)
        if (simdi_ms - son_telemetri_zamanlari[data.takim_numarasi]) < 490: # Tolerans payı
            # [cite: 72] 400 durum kodu ile sayfa içeriği olarak 3
            return JSONResponse(status_code=400, content=3)
            
    # 4. Veri Aralığı Kontrolü [cite: 77, 83-85]
    # Aralık dışı ise tüm paket hatalı sayılır. 
    # Döküman "hatalı sayılacaktır" diyor, format yanlış değilse mantıken 400 döneriz.
    valid_range = (
        (-90 <= data.iha_dikilme <= 90) and
        (0 <= data.iha_yonelme <= 360) and
        (-90 <= data.iha_yatis <= 90)
    )
    if not valid_range:
         return JSONResponse(status_code=400, content="Aralik Disi Veri")

    # Veritabanı İşlemleri
    conn = get_db()
    gps_ms = (data.gps_saati.saat * 3600000) + (data.gps_saati.dakika * 60000) + \
             (data.gps_saati.saniye * 1000) + data.gps_saati.milisaniye
             
    conn.execute("""INSERT INTO telemetri (
        takim_no, enlem, boylam, irtifa, dikilme, yonelme, yatis, hiz,
        batarya, otonom, kilitlenme, hedef_merkez_X, hedef_merkez_Y, 
        hedef_genislik, hedef_yukseklik, gps_saati_ms, sunucu_saati_ms
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", 
    (data.takim_numarasi, data.iha_enlem, data.iha_boylam, data.iha_irtifa,
     data.iha_dikilme, data.iha_yonelme, data.iha_yatis, data.iha_hiz,
     data.iha_batarya, data.iha_otonom, data.iha_kilitlenme, 
     data.hedef_merkez_X, data.hedef_merkez_Y, data.hedef_genislik, 
     data.hedef_yukseklik, gps_ms, simdi_ms))
    
    conn.commit()
    son_telemetri_zamanlari[data.takim_numarasi] = simdi_ms

    # 5. Cevap Oluşturma [cite: 132-162]
    TIMEOUT_MS = 5000
    esik_zaman = simdi_ms - TIMEOUT_MS
    rows = conn.execute("SELECT * FROM telemetri WHERE sunucu_saati_ms > ? GROUP BY takim_no HAVING MAX(sunucu_saati_ms)", (esik_zaman,)).fetchall()
    
    konumlar = []
    for r in rows:
        # --- EKLENECEK FİLTRE BAŞLANGICI ---
        # Eğer veritabanından gelen takım no, isteği gönderen takım no ile aynıysa;
        # bu benim kendi takımımdır, listeye ekleme ve sonraki satıra geç.
            
        konumlar.append({
            "takim_numarasi": r['takim_no'],
            "iha_enlem": r['enlem'],
            "iha_boylam": r['boylam'],
            "iha_irtifa": r['irtifa'],
            "iha_dikilme": r['dikilme'],
            "iha_yonelme": r['yonelme'],
            "iha_yatis": r['yatis'],
            "iha_hizi": r['hiz'],
            "zaman_farki": simdi_ms - r['sunucu_saati_ms']
        })

    return {"sunucusaati": mevcut_sunucu_saati(), "konumBilgileri": konumlar}
@app.post("/api/kilitlenme_bilgisi") # [cite: 166-182]
async def kilitlenme_bilgisi(data: KilitlenmeModel, request: Request):
    # Pakette Takım No YOK. IP'den buluyoruz.
    client_ip = request.client.host
    if client_ip not in ip_session_map:
        raise HTTPException(status_code=401, detail="Oturum acilmadi")
    
    takim_no = ip_session_map[client_ip]
    
    print(f"\n[KILITLENME] Takım {takim_no} kilitlendi.")
    print(json.dumps(data.dict(), indent=4))

    conn = get_db()
    bitis_str = format_time_str(data.kilitlenmeBitisZamani)
    
    conn.execute("INSERT INTO kilitlenmeler (takim_no, baslangic_saati, bitis_saati, otonom_mu) VALUES (?, ?, ?, ?)",
                 (takim_no, "Unknown", bitis_str, data.otonom_kilitlenme))
    conn.commit()
    return status.HTTP_200_OK

@app.post("/api/kamikaze_bilgisi") # [cite: 183-205]
async def kamikaze_bilgisi(data: KamikazeModel, request: Request):
    # Pakette Takım No YOK. IP'den buluyoruz.
    client_ip = request.client.host
    if client_ip not in ip_session_map:
        raise HTTPException(status_code=401, detail="Oturum acilmadi")
    
    takim_no = ip_session_map[client_ip]
    
    print(f"\n[KAMIKAZE] Takım {takim_no} kamikaze yaptı.")
    print(json.dumps(data.model_dump(), indent=4))

    conn = get_db()
    baslangic_str = format_time_str(data.kamikazeBaslangicZamani)
    bitis_str = format_time_str(data.kamikazeBitisZamani)
    
    conn.execute("INSERT INTO kamikaze (takim_no, baslangic_saati, bitis_saati, qr_metni) VALUES (?, ?, ?, ?)",
                 (takim_no, baslangic_str, bitis_str, data.qrMetni))
    conn.commit()
    return status.HTTP_200_OK

@app.get("/api/qr_koordinati") # [cite: 208-216]
async def qr_koordinati():
    return {"qrEnlem": 41.51238882, "qrBoylam": 36.11935778}

@app.get("/api/hss_koordinatlari") # [cite: 217-226]
async def hss_koordinatlari():
    # Hakemler duyuru yapana kadar boş liste dönebilir [cite: 225]
    # Test için dolu dönüyoruz
    hss_listesi = [
        {"id": 1, "hssEnlem": 41.5130, "hssBoylam": 36.1200, "hssYaricap": 50},
    ]
    return {"sunucusaati": mevcut_sunucu_saati(), "hss_koordinat_bilgileri": hss_listesi}

if __name__ == "__main__":
    # 127.0.0.25 Mac/Windows bazı durumlarda sorun çıkarabilir, localhost ile test edebilirsiniz.
    # Ancak kod mantığı IP kontrolü yaptığı için, client scriptiniz de aynı makinede ise
    # IP hep 127.0.0.1 görünecektir. Bu test için yeterlidir.
    uvicorn.run(app, host="localhost", port=8000)