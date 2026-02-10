import urllib.request
import urllib.parse
import json
import time
from datetime import datetime

class CompetitorClient:
    def __init__(self, base_url="http://localhost:8000", username="rota_takim", password="parola123"):
        self.base_url = base_url
        self.username = username
        self.password = password
        self.takim_no = None
        self.headers = {'Content-Type': 'application/json'}

    def _send_request(self, endpoint, method="GET", data=None):
        url = f"{self.base_url}{endpoint}"
        try:
            if data:
                data_bytes = json.dumps(data).encode('utf-8')
                req = urllib.request.Request(url, data=data_bytes, headers=self.headers, method=method)
            else:
                req = urllib.request.Request(url, headers=self.headers, method=method)
            
            with urllib.request.urlopen(req) as response:
                resp_body = response.read().decode('utf-8')
                return response.status, json.loads(resp_body) if resp_body else None
        except urllib.error.HTTPError as e:
            error_body = e.read().decode('utf-8')
            print(f"Server Error ({e.code}): {error_body}")
            return e.code, None
        except Exception as e:
            print(f"Connection Error: {e}")
            return 0, None

    def login(self):
        """Bölüm 5: Sisteme Giriş"""
        print(f"Logging in as {self.username}...")
        status, body = self._send_request("/api/giris", "POST", {
            "kadi": self.username, 
            "sifre": self.password
        })
        
        if status == 200:
            self.takim_no = body
            print(f"Login Successful! Takim No: {self.takim_no}")
            return True
        else:
            print("Login Failed.")
            return False

    def get_server_time(self):
        """Bölüm 6: Sunucu Saati"""
        status, body = self._send_request("/api/sunucusaati", "GET")
        return body if status == 200 else None

    def send_telemetry(self, lat, lon, alt, pitch, heading, roll, speed, battery, autonomous, locked, target_info=None):
        """Bölüm 7: Telemetri Gönderimi"""
        if self.takim_no is None:
            print("Error: Must login first!")
            return None

        # Prepare default target info if not provided
        if target_info is None:
            target_info = {
                "hedef_merkez_X": 0, "hedef_merkez_Y": 0,
                "hedef_genislik": 0, "hedef_yukseklik": 0
            }

        # Current time for GPS example
        now = datetime.now()
        
        telemetry_data = {
            "takim_numarasi": self.takim_no,
            "iha_enlem": lat, "iha_boylam": lon, "iha_irtifa": alt,
            "iha_dikilme": pitch, "iha_yonelme": heading, "iha_yatis": roll, "iha_hiz": speed,
            "iha_batarya": battery, "iha_otonom": autonomous, "iha_kilitlenme": locked,
            "hedef_merkez_X": target_info.get("hedef_merkez_X", 0),
            "hedef_merkez_Y": target_info.get("hedef_merkez_Y", 0),
            "hedef_genislik": target_info.get("hedef_genislik", 0),
            "hedef_yukseklik": target_info.get("hedef_yukseklik", 0),
            "gps_saati": {
                "saat": now.hour, "dakika": now.minute, 
                "saniye": now.second, "milisaniye": now.microsecond // 1000
            }
        }
        
        
        # Dökümanda (7.2) belirtildiği gibi gönderilen veriyi konsolda gösterelim
        print(f"\n[TELEMETRI GONDERILIYOR - Takım {self.takim_no}]:")
        print(json.dumps(telemetry_data, indent=4, ensure_ascii=False))

        status, body = self._send_request("/api/telemetri_gonder", "POST", telemetry_data)
        if status == 200:
            return body # Contains other teams' locations
        elif status == 400 and body == 3:
            print("Rate Limit Exceeded (Wait 500ms)")
        return None

    def send_lock_info(self, end_time_dt, is_autonomous):
        """Bölüm 8: Kilitlenme Bilgisi"""
        # Format time as nested dict
        end_time_dict = {
            "saat": end_time_dt.hour, 
            "dakika": end_time_dt.minute, 
            "saniye": end_time_dt.second, 
            "milisaniye": end_time_dt.microsecond // 1000
        }

        data = {
            "takim_numarasi": self.takim_no,
            "kilitlenmeBitisZamani": end_time_dict,
            "otonom_kilitlenme": 1 if is_autonomous else 0
        }

        # Dökümanda (8.1) belirtildiği gibi gönderilen veriyi konsolda gösterelim (takim_numarasi haric)
        print(f"\n[KILITLENME BILGISI GONDERILIYOR - Takım {self.takim_no}]:")
        display_data = {k: v for k, v in data.items() if k != 'takim_numarasi'}
        print(json.dumps(display_data, indent=4, ensure_ascii=False))

        status, _ = self._send_request("/api/kilitlenme_bilgisi", "POST", data)
        return status == 200

    def send_kamikaze_info(self, start_dt, end_dt, qr_text):
        """Bölüm 9: Kamikaze Bilgisi"""
        def format_dt(dt):
            return {
                "saat": dt.hour, "dakika": dt.minute,
                "saniye": dt.second, "milisaniye": dt.microsecond // 1000
            }

        data = {
            "takim_numarasi": self.takim_no,
            "kamikazeBaslangicZamani": format_dt(start_dt),
            "kamikazeBitisZamani": format_dt(end_dt),
            "qrMetni": qr_text
        }

        # Dökümanda (9) belirtildiği gibi gönderilen veriyi konsolda gösterelim (takim_numarasi haric)
        print(f"\n[KAMIKAZE BILGISI GONDERILIYOR - Takım {self.takim_no}]:")
        display_data = {k: v for k, v in data.items() if k != 'takim_numarasi'}
        print(json.dumps(display_data, indent=4, ensure_ascii=False))

        status, _ = self._send_request("/api/kamikaze_bilgisi", "POST", data)
        return status == 200

    def get_qr_coordinate(self):
        """Bölüm 10: QR Koordinatı"""
        status, body = self._send_request("/api/qr_koordinati", "GET")
        return body if status == 200 else None

    def get_hss_coordinates(self):
        """Bölüm 11: HSS Koordinatları"""
        status, body = self._send_request("/api/hss_koordinatlari", "GET")
        return body if status == 200 else None

if __name__ == "__main__":
    # Örnek Kullanım
    client = CompetitorClient(username="rota_takim", password="parola123")
    
    if client.login():
        # Sunucu Saatini Al
        print("Sunucu Saati:", client.get_server_time())
        
        # Telemetri Gönder (Örnek Döngü)
        print("\nSending telemetry packet...")
        response = client.send_telemetry(
            lat=41.123, lon=29.456, alt=100.5,
            pitch=10, heading=90, roll=0, 
            speed=15.5, battery=85, 
            autonomous=1, locked=0
        )
        if response:
            print("Telemetry sent! Other teams:", response.get("konumBilgileri"))

        # QR Koordinatını Al
        print("\nQR Coordinate:", client.get_qr_coordinate())
        
        # HSS Koordinatlarını Al
        print("HSS Coordinates:", client.get_hss_coordinates())
