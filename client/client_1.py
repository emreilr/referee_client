import asyncio
import requests
import json
import random
import math
from datetime import datetime, timedelta
from fastapi import FastAPI
from pydantic import BaseModel
import uvicorn

# --- AYARLAR ---
SERVER_URL = "http://localhost:8000"
BRIDGE_PORT = 8001                    # 2. Takım için bunu 8002 yapın
TAKIM_KADI = "rota_takim"             # 2. Takım için "rota_takim2" yapın [cite: 52]
TAKIM_SIFRE = "parola123"             # [cite: 54]

# --- VERİ MODELLERİ ---
class IhaVerisi(BaseModel):
    """Döküman 7.1 referans alınmıştır."""
    iha_enlem: float = 41.508775      # [cite: 80]
    iha_boylam: float = 36.118335     # [cite: 81]
    iha_irtifa: float = 38.0          # [cite: 82]
    iha_dikilme: float = 0.0          # [cite: 83]
    iha_yonelme: float = 0.0          # [cite: 84]
    iha_yatis: float = 0.0            # [cite: 85]
    iha_hiz: float = 10.0             # [cite: 86]
    iha_batarya: float = 100.0        # [cite: 87]
    iha_otonom: int = 1               # [cite: 88]
    iha_kilitlenme: int = 0           # [cite: 89]
    hedef_merkez_X: int = 0           # [cite: 90]
    hedef_merkez_Y: int = 0           # [cite: 93]
    hedef_genislik: int = 0           # [cite: 95]
    hedef_yukseklik: int = 0          # [cite: 96]

class KamikazeIstegi(BaseModel):
    qr_metni: str = "teknofest2025"

class KilitlenmeIstegi(BaseModel):
    otonom_mu: int = 1

# --- GLOBAL DURUM ---
current_state = IhaVerisi()
latest_rival_data = []
session_info = {"takim_no": None, "logged_in": False}

app = FastAPI(title="Teknofest Simülasyon Client")

# --- YARDIMCI FONKSİYONLAR ---

def zaman_objesi_olustur(dt_obj):
    """Döküman formatına uygun saat objesi oluşturur."""
    return {
        "saat": dt_obj.hour,
        "dakika": dt_obj.minute,
        "saniye": dt_obj.second,
        "milisaniye": int(dt_obj.microsecond / 1000)
    }

def sunucuya_giris_yap():
    """Döküman Bölüm 5: Oturum Açma"""
    print("🔑 Yarışma sunucusuna giriş deneniyor...")
    try:
        payload = {"kadi": TAKIM_KADI, "sifre": TAKIM_SIFRE}
        response = requests.post(f"{SERVER_URL}/api/giris", json=payload, timeout=2)
        
        if response.status_code == 200:
            takim_no = response.json()
            session_info["takim_no"] = takim_no
            session_info["logged_in"] = True
            print(f"✅ GİRİŞ BAŞARILI! Takım Numaranız: {takim_no}")
            return True
        else:
            print(f"❌ Giriş Başarısız. Kod: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Sunucuya bağlanılamadı: {e}")
        return False

def rastgele_hareket_uret():
    """İHA'nın hareketini simüle eder (Random Walk)."""
    global current_state
    
    # Konumu küçük miktarlarda değiştir (Sanki uçuyor gibi)
    # 0.0001 derece yaklaşık 11 metreye denk gelir.
    current_state.iha_enlem += random.uniform(-0.0001, 0.0001)
    current_state.iha_boylam += random.uniform(-0.0001, 0.0001)
    
    # İrtifa değişimi (30m - 50m arası dalgalanma)
    current_state.iha_irtifa += random.uniform(-0.5, 0.5)
    current_state.iha_irtifa = max(30.0, min(50.0, current_state.iha_irtifa))
    
    # Açısal değişimler (Gürültü ekle)
    current_state.iha_dikilme = round(random.uniform(-5, 5), 2)
    current_state.iha_yatis = round(random.uniform(-10, 10), 2)
    current_state.iha_yonelme = (current_state.iha_yonelme + random.uniform(-2, 2)) % 360
    
    # Batarya simülasyonu (Yavaşça tükenir)
    current_state.iha_batarya = max(0, current_state.iha_batarya - 0.05)
    if current_state.iha_kilitlenme == 1:
        # Rastgele bir hedef kutucuğu uyduruyoruz
        current_state.hedef_merkez_X = random.randint(100, 500)
        current_state.hedef_merkez_Y = random.randint(100, 400)
        current_state.hedef_genislik = random.randint(20, 100)
        current_state.hedef_yukseklik = random.randint(20, 100)
    else:
        # Kilitlenme yoksa sıfırla
        current_state.hedef_merkez_X = 0
        current_state.hedef_merkez_Y = 0
        current_state.hedef_genislik = 0
        current_state.hedef_yukseklik = 0
def paket_hazirla_ve_gonder():
    """Döküman Bölüm 7: Telemetri Gönderimi"""
    if not session_info["logged_in"]:
        return

    # 1. Verileri güncelle (Rastgele hareket)
    rastgele_hareket_uret()

    now = datetime.now()
    
    # 2. Payload Hazırla
    # Pydantic v2 için model_dump(), v1 için dict()
    payload = current_state.model_dump() 
    payload["takim_numarasi"] = session_info["takim_no"]
    payload["gps_saati"] = zaman_objesi_olustur(now)

    try:
        resp = requests.post(f"{SERVER_URL}/api/telemetri_gonder", json=payload, timeout=0.5)
        
        if resp.status_code == 200:
            data = resp.json()
            
            # --- TERMİNAL ÇIKTISI (Şelale Görünümü) ---
            print("\n" + "-"*50)
            print(f"📡 [TELEMETRİ] Gönderildi | Saat: {now.strftime('%H:%M:%S')}")
            print(f"   Benim Konum: {current_state.iha_enlem:.6f}, {current_state.iha_boylam:.6f}")
            print(f"📥 [CEVAP] Sunucudan Gelen Rakipler:")
            print(json.dumps(data, indent=4, ensure_ascii=False))
            print("-"*50)
            # ------------------------------------------

            global latest_rival_data
            latest_rival_data = data.get("konumBilgileri", [])
            
        elif resp.status_code == 400:
            print("⚠️ Sunucu: 400 (Hız Sınırı veya Veri Hatası)")
            
    except Exception as e:
        print(f"❌ Telemetri Hatası: {e}")

# --- API ENDPOINTLERİ (Tetikleyiciler) ---

@app.post("/kamikaze/tetikle")
async def kamikaze_tetikle(istek: KamikazeIstegi):
    """Kamikaze verisi gönderir [cite: 183-205]."""
    if not session_info["logged_in"]: return {"hata": "Giriş yapılmadı"}

    print("\n" + "!"*40)
    print("🚀 [KAMIKAZE] Simülasyon Başlatıldı...")
    
    now = datetime.now()
    baslangic = zaman_objesi_olustur(now)
    # Kamikaze 5 saniye sürmüş gibi bitiş zamanı ayarla
    bitis = zaman_objesi_olustur(now + timedelta(seconds=5))

    payload = {
        "kamikazeBaslangicZamani": baslangic,
        "kamikazeBitisZamani": bitis,
        "qrMetni": istek.qr_metni
    }

    try:
        resp = requests.post(f"{SERVER_URL}/api/kamikaze_bilgisi", json=payload, timeout=2)
        print(f"📤 Gönderilen Metin: {istek.qr_metni}")
        
        if resp.status_code == 200:
            print("✅ [BAŞARILI] Kamikaze sunucuya işlendi.")
            print("!"*40 + "\n")
            return {"durum": "Başarılı"}
        else:
            print(f"❌ [HATA] Kod: {resp.status_code}")
            return {"durum": "Hata", "kod": resp.status_code}
    except Exception as e:
        print(f"❌ Hata: {e}")
        return {"durum": "Bağlantı Hatası"}

@app.post("/kilitlenme/tetikle")
async def kilitlenme_tetikle(istek: KilitlenmeIstegi):
    """Kilitlenme verisi gönderir [cite: 166-182]."""
    if not session_info["logged_in"]: return {"hata": "Giriş yapılmadı"}

    print("\n" + "*"*40)
    print("🎯 [KİLİTLENME] Simülasyon Başlatıldı...")
    
    now = datetime.now()
    bitis = zaman_objesi_olustur(now)

    payload = {
        "kilitlenmeBitisZamani": bitis,
        "otonom_kilitlenme": istek.otonom_mu
    }

    try:
        resp = requests.post(f"{SERVER_URL}/api/kilitlenme_bilgisi", json=payload, timeout=2)
        
        if resp.status_code == 200:
            print("✅ [BAŞARILI] Kilitlenme sunucuya işlendi.")
            print("*"*40 + "\n")
            return {"durum": "Başarılı"}
        else:
            print(f"❌ [HATA] Kod: {resp.status_code}")
            return {"durum": "Hata", "kod": resp.status_code}
    except Exception as e:
        print(f"❌ Hata: {e}")
        return {"durum": "Bağlantı Hatası"}

# --- ARKAPLAN DÖNGÜSÜ ---
async def telemetri_dongusu():
    while not session_info["logged_in"]:
        sunucuya_giris_yap()
        await asyncio.sleep(2)
    
    print("📡 Telemetri akışı başlatıldı (1 Hz)...")
    while True:
        await asyncio.to_thread(paket_hazirla_ve_gonder)
        await asyncio.sleep(1.0) # 1 Hz kuralı

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(telemetri_dongusu())

# ... diğer kodların altına ...

def qr_hedefini_ogren():
    """
    Sunucudan Kamikaze yapılacak hedefin (QR Kodun) koordinatlarını çeker.
    Döküman Bölüm 10 referans alınmıştır.
    """
    if not session_info["logged_in"]:
        print("❌ Önce giriş yapmalısınız!")
        return None

    print("\n" + "?"*40)
    print("🔍 [SORGULAMA] Hedef QR Kodunun Konumu İsteniyor...")

    try:
        # GET isteği ile koordinatları al 
        resp = requests.get(f"{SERVER_URL}/api/qr_koordinati", timeout=2)
        
        if resp.status_code == 200:
            data = resp.json()
            qr_enlem = data.get("qrEnlem") # [cite: 214]
            qr_boylam = data.get("qrBoylam") # [cite: 216]
            
            print(f"✅ [HEDEF BULUNDU] QR Kodu Şurada:")
            print(f"   Enlem : {qr_enlem}")
            print(f"   Boylam: {qr_boylam}")
            print("?"*40 + "\n")
            
            # Bu koordinatları otonom uçuş fonksiyonuna döndürebilirsiniz
            return (qr_enlem, qr_boylam)
        else:
            print(f"❌ Sunucu Hatası: {resp.status_code}")
            return None
            

    except Exception as e:
        print(f"❌ Bağlantı Hatası: {e}")
        return None

# --- API Tetikleyici (Manuel Test İçin) ---
@app.get("/kamikaze/hedef_getir")
async def hedef_getir_api():
    koordinat = qr_hedefini_ogren()
    if koordinat:
        return {"durum": "Hedef Alındı", "enlem": koordinat[0], "boylam": koordinat[1]}
    return {"durum": "Hata"}
def hss_verilerini_guncelle():
    """
    Sunucudan Hava Savunma Sistemi (Yasak Bölge) koordinatlarını çeker.
    Döküman Bölüm 11 [cite: 217-226].
    """
    if not session_info["logged_in"]: return

    try:
        resp = requests.get(f"{SERVER_URL}/api/hss_koordinatlari", timeout=2)
        if resp.status_code == 200:
            data = resp.json()
            hss_listesi = data.get("hss_koordinat_bilgileri", [])
            
            # Eğer liste boş değilse terminale bas
            if hss_listesi:
                print(f"⚠️ [UYARI] {len(hss_listesi)} Adet Hava Savunma Sistemi Aktif!")
                for hss in hss_listesi:
                    print(f"   - ID: {hss['id']} | Yarıçap: {hss['hssYaricap']}m | Konum: {hss['hssEnlem']},{hss['hssBoylam']}")
            else:
                # Hakemler henüz aktif etmediyse boş döner [cite: 225]
                print("ℹ️ [BİLGİ] Aktif HSS Bulunmamaktadır.")
                
            return hss_listesi
    except Exception as e:
        print(f"❌ HSS Sorgu Hatası: {e}")
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=BRIDGE_PORT)