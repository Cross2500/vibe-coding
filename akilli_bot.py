from google import genai
import json
import datetime

# 1. API Anahtarını Buraya Gir
API_KEY = "AQ.Ab8RN6J8rX9F-y7bUBPDBzPp32u6Yjfoqtks8PuYobKy6ZK15g"
client = genai.Client(api_key=API_KEY)

# 2. İstenilen Konular
konular = [
    {"id": "bolum-1", "baslik": "Algoritma Analizi ve Bellek Yönetimi", "ikon": "fa-microchip"},
    {"id": "bolum-2", "baslik": "Lineer Cebir: Matrislerin Kodlanması", "ikon": "fa-square-root-variable"},
    {"id": "bolum-3", "baslik": "Ayrık Matematik (Discrete Math)", "ikon": "fa-calculator"},
    {"id": "bolum-4", "baslik": "Yapay Zeka ve Veri Bilimi Temelleri", "ikon": "fa-database"}
]

elde_edilen_notlar = []

print("🧠 Yeni nesil Yapay Zeka asistanı devrede! İçerikler hazırlanıyor...\n")

for konu in konular:
    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Hazırlanıyor: {konu['baslik']}...")
    
    prompt = f"Sen bir bilgisayar mühendisliği profesörüsün. 1. sınıf öğrencisi için '{konu['baslik']}' konusunu akademik düzeyde detaylıca anlat. Arka plandaki matematiği, mühendislik vizyonunu ve mutlaka C veya Python dilinde bir kod örneğini ekle. Yazıyı anlaşılır tut. Sadece içeriği ver, en başa tekrar başlık yazma. Yanıtını doğrudan HTML formatında (sadece <p>, <h3>, <strong> ve kodlar için <pre><code class='language-c'> etiketleri) kullanarak ver. Markdown (*** veya ###) kullanma."

    try:
        # Yeni kütüphanenin veri çekme komutu
        response = client.models.generate_content(
            model='gemini-3.8-flash',
            contents=prompt,
        )
        
        # HTML temizliği
        uretilen_metin = response.text.replace("```html", "").replace("```", "").strip()

        bolum = {
            "id": konu["id"],
            "baslik": konu["baslik"],
            "icerik": uretilen_metin,
            "ikon": konu["ikon"]
        }
        elde_edilen_notlar.append(bolum)
        print(f"✅ {konu['baslik']} siteye eklendi.\n")

    except Exception as e:
        print(f"❌ {konu['baslik']} hazırlanamadı. Hata: {e}")

# Verileri json dosyasına kaydet
kayit_verisi = {
    "son_guncelleme": datetime.datetime.now().strftime("%d.%m.%Y %H:%M"),
    "bolumler": elde_edilen_notlar
}

with open("notlar.json", "w", encoding="utf-8") as dosya:
    json.dump(kayit_verisi, dosya, ensure_ascii=False, indent=4)

print("🚀 Tüm notlar güncellendi ve 'notlar.json' dosyası oluşturuldu!")