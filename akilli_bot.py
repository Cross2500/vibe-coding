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

# MEVCUT MODÜL: Algoritmik Okuma Süresi Hesaplayıcı
def okuma_suresi_hesapla(metin: str) -> int:
    """Metnin kelime sayısını analiz edip insan için ortalama okuma süresini (dakika) döndürür."""
    kelime_sayisi = len(metin.split())
    dakika = max(1, round(kelime_sayisi / 200)) 
    logger.info(f"Metin analizi: Toplam {kelime_sayisi} kelime, {dakika} dakikalık okuma süresi hesaplandı.")
    return dakika

# YENİ EKLENEN EXTRA MODÜL: Akademik Zorluk Seviyesi Analizörü
def akademik_zorluk_hesapla(metin: str) -> str:
    """Metindeki karmaşık öğeleri (formül, kod bloğu) sayarak zorluk derecesini belirler."""
    kod_blok_sayisi = metin.count("```") / 2
    formul_sayisi = metin.count("$$") / 2
    kelime_sayisi = len(metin.split())
    
    # Özel algoritma: Formüller ve kodlar zorluğu çok artırır, uzunluk az artırır
    karmasiklik_puani = (formul_sayisi * 2.5) + (kod_blok_sayisi * 2.0) + (kelime_sayisi / 400)
    
    logger.info(f"Karmaşıklık Skoru: Puan={karmasiklik_puani:.1f} (Kod: {int(kod_blok_sayisi)}, Formül: {int(formul_sayisi)})")
    
    if karmasiklik_puani >= 12:
        return "🔴 İleri Seviye (Uzman)"
    elif karmasiklik_puani >= 6:
        return "🟡 Orta Seviye (Lisans)"
    else:
        return "🟢 Temel Seviye (Giriş)"

def otonom_sistemi_baslat():
    logger.info("--- 🧠 CS101 Otonom Akademik Not Sistemi Başlatılıyor ---")
    dosya_adi = 'notlar.json'
    mevcut_notlar = {}
    
    # MODÜL 1: Eski Notları Oku ve Güvenlik Yedeği Al
    if os.path.exists(dosya_adi):
        shutil.copy2(dosya_adi, f"{dosya_adi}.backup") 
        logger.info("Veritabanı güvenlik yedeği alındı.")
        try:
            with open(dosya_adi, 'r', encoding='utf-8') as f:
                mevcut_notlar = json.load(f)
        except json.JSONDecodeError:
            logger.warning("Mevcut JSON bozuk, sistem kurtarma modunda sıfırdan başlıyor.")
            
    islenen_konular = list(mevcut_notlar.keys())
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
        "icerik": "Tüm ders içeriği (Markdown formatında, satır atlamaları için \\n kullan)"
    }}
    """
    
    # MODÜL 3: Yapay Zekadan İçerik Üretme (Retry Mekanizması)
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
            
            logger.info(f"✨ Harika! Yapay zeka şu konuyu üretti: '{baslik}'")
            
            # GÜNCELLENMİŞ ENTEGRASYON: Okuma Süresi ve Zorluk Derecesi birleştirildi
            hesaplanan_sure = okuma_suresi_hesapla(ham_icerik)
            zorluk_etiketi = akademik_zorluk_hesapla(ham_icerik)
            
            # İki analiz modülünün sonucunu tek bir şık panelde birleştiriyoruz
            meta_panel = f"> ⏱️ **Tahmini Okuma Süresi:** {hesaplanan_sure} dakika | 🎚️ **Zorluk Derecesi:** {zorluk_etiketi}\n\n---\n\n"
            son_icerik = meta_panel + ham_icerik
            
            # MODÜL 4: Yeni Konuyu Sisteme Kaydet
            mevcut_notlar[baslik] = son_icerik
            
            with open(dosya_adi, 'w', encoding='utf-8') as f:
                json.dump(mevcut_notlar, f, ensure_ascii=False, indent=4)
                
            logger.info("🚀 BAŞARILI: Yeni ders siteye eklendi ve veritabanı güncellendi!")
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
