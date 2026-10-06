import os
import json
import time
import logging
import shutil
from datetime import datetime
from google import genai
from google.genai import types

# 1. PROFESYONEL LOGLAMA SİSTEMİ
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [%(levelname)s] - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

# 2. GÜVENLİK VE API BAĞLANTISI
API_KEY = os.environ.get("GEMINI_API_KEY")
if not API_KEY:
    logger.error("KRİTİK HATA: GEMINI_API_KEY bulunamadı! GitHub Secrets'ı kontrol et.")
    exit(1)

client = genai.Client(api_key=API_KEY)

# EKSTRA MODÜL 1: Okuma Süresi Hesaplayıcı
def okuma_suresi_hesapla(metin: str) -> int:
    kelime_sayisi = len(metin.split())
    return max(1, round(kelime_sayisi / 200))

# EKSTRA MODÜL 2: Akademik Zorluk Seviyesi Analizörü
def akademik_zorluk_hesapla(metin: str) -> str:
    kod_blok_sayisi = metin.count("```") / 2
    formul_sayisi = metin.count("$$") / 2
    kelime_sayisi = len(metin.split())
    
    karmasiklik_puani = (formul_sayisi * 2.5) + (kod_blok_sayisi * 2.0) + (kelime_sayisi / 400)
    
    if karmasiklik_puani >= 12:
        return "🔴 İleri Seviye (Uzman)"
    elif karmasiklik_puani >= 6:
        return "🟡 Orta Seviye (Lisans)"
    else:
        return "🟢 Temel Seviye (Giriş)"

def otonom_sistemi_baslat():
    logger.info("--- 🧠 CS101 Otonom Akademik Not Sistemi Başlatılıyor ---")
    dosya_adi = 'notlar.json'
    mevcut_liste = []
    
    # MODÜL 1: Eski Notları Dizi (Array) Formatında Oku ve Yedekle
    if os.path.exists(dosya_adi):
        shutil.copy2(dosya_adi, f"{dosya_adi}.backup")
        logger.info("Veritabanı güvenlik yedeği alındı.")
        try:
            with open(dosya_adi, 'r', encoding='utf-8') as f:
                veri = json.load(f)
                # Frontend doğrudan dizi beklediği için veriyi güvenle çekiyoruz
                if isinstance(veri, list):
                    mevcut_liste = veri
                elif isinstance(veri, dict) and "bolumler" in veri:
                    mevcut_liste = veri["bolumler"]
        except json.JSONDecodeError:
            logger.warning("Mevcut JSON okunamadı, sıfırdan başlanıyor.")
            
    islenen_konular = [item.get("baslik", "") for item in mevcut_liste]
    konu_gecmisi = ", ".join(islenen_konular) if islenen_konular else "Henüz hiç konu işlenmedi."
    gunun_tarihi = datetime.now().strftime("%d %B %Y")
    
    # MODÜL 2: Dinamik Akademik Prompt
    prompt = f"""
    Sen MIT ve Stanford seviyesinde ders veren, vizyoner bir Bilgisayar Mühendisliği Profesörüsün.
    Şu ana kadar müfredatta işlediğimiz konular şunlar: {konu_gecmisi}
    
    GÖREV: Bu geçmişi analiz et ve müfredatta mantıksal olarak sıradaki EN İLERİ SEVİYE yepyeni konuyu seç.
    Seçtiğin bu konu için en az 1500 kelimelik, öğrencilerin ufkunu açacak devasa bir ders notu hazırla.
    
    AKADEMİK KURALLAR:
    1. İçerik Markdown formatında olsun, en az 3 detaylı alt başlık (##) içer.
    2. İleri seviye Python, C++ veya SQL kod blokları yaz ve mimariyi açıkla.
    3. Matematiksel formüller için KaTeX formatı ($$ formül $$) kullan.
    4. Notun en sonuna "Gelecek Ders İçin İpucu" bölümü ekle.
    5. İÇERİĞİN EN ALTINA günün tarihini ({gunun_tarihi}) ve konuyu özetleyen 5 adet modern hashtag ekle.
    
    YANIT FORMATI: 
    SADECE geçerli bir JSON döndür. Başka hiçbir açıklama yazma. Format KESİNLİKLE şu olmalı:
    {{
        "baslik": "Seçtiğin Yeni Konu Başlığı",
        "icerik": "Tüm ders içeriği (Markdown formatında, satır allamaları için \\n kullan)"
    }}
    """
    
    # MODÜL 3: Yapay Zekadan İçerik Üretme (Gemini 3.8 Flash)
    max_deneme = 3
    for deneme in range(max_deneme):
        try:
            logger.info(f"Yapay zeka analiz yapıyor... (Deneme {deneme+1}/{max_deneme})")
            
            response = client.models.generate_content(
                model='gemini-3.8-flash', 
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                )
            )
            
            yeni_konu = json.loads(response.text)
            baslik = yeni_konu["baslik"]
            ham_icerik = yeni_konu["icerik"]
            
            # Entegrasyonlar
            hesaplanan_sure = okuma_suresi_hesapla(ham_icerik)
            zorluk_etiketi = akademik_zorluk_hesapla(ham_icerik)
            meta_panel = f"> ⏱️ **Tahmini Okuma Süresi:** {hesaplanan_sure} dakika | 🎚️ **Zorluk Derecesi:** {zorluk_etiketi}\n\n---\n\n"
            son_icerik = meta_panel + ham_icerik
            
            # Yeni konuyu frontend'in kusursuz okuyacağı dizi yapısına ekle
            yeni_oge = {
                "baslik": baslik,
                "icerik": son_icerik
            }
            mevcut_liste.append(yeni_oge)
            
            with open(dosya_adi, 'w', encoding='utf-8') as f:
                json.dump(mevcut_liste, f, ensure_ascii=False, indent=4)
                
            logger.info(f"🚀 BAŞARILI: '{baslik}' siteye eklendi ve veritabanı güncellendi!")
            break 
            
        except Exception as e:
            logger.error(f"Üretim sırasında hata oluştu: {e}")
            if deneme < max_deneme - 1:
                logger.info("Sunucu meşgul olabilir. 5 saniye beklenip tekrar deneniyor...")
                time.sleep(5)
            else:
                logger.error("Maksimum deneme sayısına ulaşıldı. Bugünkü otonom döngü iptal edildi.")

if __name__ == "__main__":
    otonom_sistemi_baslat()
