import asyncio
import requests
import json
from datetime import datetime
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import uvicorn

# --- AYARLAR ---
SERVER_URL = "http://localhost:8000"
BRIDGE_PORT = 8002                    # Bu scriptin çalışacağı port
TAKIM_KADI = "rota_takim2"             # [cite: 52]
TAKIM_SIFRE = "parola123"             # [cite: 54]

# --- VERİ MODELLERİ ---
class IhaVerisi(BaseModel):
    """
    ROS veya MAVLink olmadan veriyi dışarıdan güncellemek için kullanılacak model.
    Döküman 7.1 referans alınmıştır.
    """
    iha_enlem: float = 41.508775      # [cite: 80]
    iha_boylam: float = 36.118335     # [cite: 81]
    iha_irtifa: float = 38.0          # [cite: 82]
    iha_dikilme: float = 0.0          # Pitch [cite: 83]
    iha_yonelme: float = 0.0          # Yaw/Heading [cite: 84]
    iha_yatis: float = 0.0            # Roll [cite: 85]
    iha_hiz: float = 10.0             # m/s [cite: 86]
    iha_batarya: float = 100.0        # % [cite: 87]
    iha_otonom: int = 1               # [cite: 88]
    iha_kilitlenme: int = 0           # [cite: 89]
    hedef_merkez_X: int = 0           # [cite: 90]
    hedef_merkez_Y: int = 0           # [cite: 93]
    hedef_genislik: int = 0           # [cite: 95]
    hedef_yukseklik: int = 0          # [cite: 96]

# --- GLOBAL DURUM ---
# İHA'nın o anki durumu burada tutulur.
current_state = IhaVerisi()
# Sunucudan gelen rakip verileri burada tutulur.
latest_rival_data = []
# Oturum bilgisi
session_info = {"token": None, "takim_no": None, "logged_in": False}

app = FastAPI(title="Teknofest No-ROS Bridge")

# --- YARDIMCI FONKSİYONLAR ---

def sunucuya_giris_yap():
    """Döküman Bölüm 5: Oturum Açma"""
    print("Yarışma sunucusuna giriş deneniyor...")
    try:
        payload = {"kadi": TAKIM_KADI, "sifre": TAKIM_SIFRE} # [cite: 51-55]
        response = requests.post(f"{SERVER_URL}/api/giris", json=payload, timeout=2)
        
        if response.status_code == 200:
            takim_no = response.json() # [cite: 56]
            session_info["takim_no"] = takim_no
            session_info["logged_in"] = True
            print(f"GİRİŞ BAŞARILI! Takım Numaranız: {takim_no}")
            return True
        else:
            print(f"Giriş Başarısız. Kod: {response.status_code}")
            return False
    except Exception as e:
        print(f"Sunucuya bağlanılamadı: {e}")
        return False

def paket_hazirla_ve_gonder():
    """Döküman Bölüm 7: Telemetri Gönderimi"""
    if not session_info["logged_in"]:
        return

    # Şu anki zamanı al (GPS saati simülasyonu için)
    now = datetime.now()
    
    # Döküman formatına uygun JSON oluştur [cite: 99-122]
    # Pydantic modelini dict'e çevirip üzerine zaman ve takım no ekliyoruz.
    payload = current_state.model_dump()
    payload["takim_numarasi"] = session_info["takim_no"] # [cite: 79]
    
    # GPS Saati Objesi [cite: 97, 117-122]
    payload["gps_saati"] = {
        "saat": now.hour,
        "dakika": now.minute,
        "saniye": now.second,
        "milisaniye": int(now.microsecond / 1000)
    }

    try:
        # POST İsteği [cite: 74]
        resp = requests.post(f"{SERVER_URL}/api/telemetri_gonder", json=payload, timeout=0.5)
        
        if resp.status_code == 200:
            # Başarılı ise rakip verilerini kaydet [cite: 75, 132]
            global latest_rival_data
            data = resp.json()
            latest_rival_data = data.get("konumBilgileri", [])
            # print(f"Telemetri gitti. {len(latest_rival_data)} rakip verisi alındı.")
            
        elif resp.status_code == 400:
            # 2 Hz sınırı aşılırsa veya format hatalıysa [cite: 72]
            print("Sunucu Uyarısı: 400 (Hatalı İstek veya Hız Sınırı)")
            
    except Exception as e:
        print(f"Gönderim hatası: {e}")

# --- ARKAPLAN DÖNGÜSÜ ---
async def telemetri_dongusu():
    """Saniyede 1 kez veriyi sunucuya gönderir."""
    # Başlangıçta giriş yapmayı dene
    while not session_info["logged_in"]:
        sunucuya_giris_yap()
        await asyncio.sleep(2)
    
    print("Telemetri akışı başlatıldı (1 Hz)...")
    
    while True:
        # Senkron request işlemini bloklamadan çalıştır
        await asyncio.to_thread(paket_hazirla_ve_gonder)
        
        # Döküman kuralı: En az 1 Hz, yani 1 saniyede 1 paket 
        await asyncio.sleep(1.0)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(telemetri_dongusu())

# --- API ENDPOINTLERİ (Senin Kullanacağın Kısım) ---

@app.post("/iha/guncelle")
async def iha_veri_guncelle(yeni_veri: IhaVerisi):
    """
    ROS veya MAVLink yokken, test scriptinden buraya veri basarak
    İHA'nın konumunu güncelleyebilirsin.
    """
    global current_state
    current_state = yeni_veri
    return {"durum": "Veri güncellendi", "yeni_veri": current_state}

@app.get("/iha/durum")
async def iha_durum_oku():
    """İHA'nın şu an hafızadaki verisini okur."""
    return current_state

@app.get("/rakipler")
async def rakipleri_getir():
    """
    Sunucudan en son dönen rakip listesini verir.
    [cite: 132-162]
    """
    return {"timestamp": datetime.now(), "rakipler": latest_rival_data}

if __name__ == "__main__":
    # Bridge API 8001 portunda çalışacak
    uvicorn.run(app, host="0.0.0.0", port=BRIDGE_PORT)