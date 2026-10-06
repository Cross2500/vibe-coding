import os
import sys
import json
import time
import logging
import tempfile
from datetime import datetime
from zoneinfo import ZoneInfo

from google import genai
from google.genai import types, errors
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Ayarlar
# ---------------------------------------------------------------------------
DOSYA_ADI = "notlar.json"
MODEL_ADI = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
YEDEK_MODEL = os.environ.get("GEMINI_FALLBACK_MODEL", "")  # boşsa yedek kullanılmaz
MAX_DENEME = 5
MIN_KELIME = 1000  # Prompt 1500 istiyor; bunun altı "çok kısa" sayılıp yeniden denenir
TZ = ZoneInfo("Europe/Istanbul")
AYLAR = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
         "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [%(levelname)s] - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


class Ders(BaseModel):
    """Modelden beklenen yanıt şeması."""
    baslik: str
    icerik: str


# ---------------------------------------------------------------------------
# Yardımcı fonksiyonlar
# ---------------------------------------------------------------------------
def okuma_suresi_hesapla(metin: str) -> int:
    return max(1, round(len(metin.split()) / 200))


def akademik_zorluk_hesapla(metin: str) -> str:
    kod_blok_sayisi = metin.count("```") / 2
    formul_sayisi = metin.count("$$") / 2
    kelime_sayisi = len(metin.split())
    puan = (formul_sayisi * 2.5) + (kod_blok_sayisi * 2.0) + (kelime_sayisi / 400)
    if puan >= 12:
        return "🔴 İleri Seviye (Uzman)"
    if puan >= 6:
        return "🟡 Orta Seviye (Lisans)"
    return "🟢 Temel Seviye (Giriş)"


def turkce_tarih(dt: datetime) -> str:
    return f"{dt.day} {AYLAR[dt.month - 1]} {dt.year}"


def istemci_olustur() -> genai.Client:
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        logger.error("KRİTİK HATA: GEMINI_API_KEY bulunamadı! GitHub Secrets'ı kontrol et.")
        sys.exit(1)
    # Tek bir istek 2 dakikadan uzun asılı kalırsa kesilir ve yeniden denenir (süre milisaniye)
    return genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(timeout=120_000),
    )


def veri_yukle() -> dict:
    """notlar.json'u okur. Okunamazsa mevcut veriyi ezmemek için DURUR."""
    veri = {"son_guncelleme": "", "bolumler": []}
    if not os.path.exists(DOSYA_ADI):
        return veri

    try:
        with open(DOSYA_ADI, "r", encoding="utf-8") as f:
            okunan = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.error(f"{DOSYA_ADI} okunamadı; veriyi ezmemek için duruyorum: {e}")
        sys.exit(1)

    if isinstance(okunan, list):
        veri["bolumler"] = okunan
    elif isinstance(okunan, dict) and isinstance(okunan.get("bolumler"), list):
        veri["bolumler"] = okunan["bolumler"]
    else:
        logger.error(f"{DOSYA_ADI} beklenmeyen bir yapıda; duruyorum.")
        sys.exit(1)
    return veri


def guvenli_kaydet(veri: dict) -> None:
    """Önce geçici dosyaya yazar, sonra atomik olarak yerine koyar."""
    fd, tmp_yol = tempfile.mkstemp(dir=".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(veri, f, ensure_ascii=False, indent=4)
        os.chmod(tmp_yol, 0o644)
        os.replace(tmp_yol, DOSYA_ADI)
    except Exception:
        if os.path.exists(tmp_yol):
            os.unlink(tmp_yol)
        raise


def yeni_id_uret(bolumler: list) -> str:
    """Mevcut en büyük numaranın bir fazlasını verir (bolum-3 eksik olsa bile çakışmaz)."""
    sayilar = []
    for b in bolumler:
        try:
            sayilar.append(int(str(b.get("id", "")).split("-")[-1]))
        except ValueError:
            continue
    return f"bolum-{max(sayilar, default=0) + 1}"


def prompt_olustur(bolumler: list, simdi: datetime) -> str:
    islenenler = [b.get("baslik", "") for b in bolumler if b.get("baslik")]
    konu_gecmisi = ", ".join(islenenler) if islenenler else "Henüz hiç konu işlenmedi."

    return f"""
Sen MIT ve Stanford seviyesinde ders veren, vizyoner bir Bilgisayar Mühendisliği Profesörüsün.
Şu ana kadar müfredatta işlediğimiz konular şunlar: {konu_gecmisi}

GÖREV: Bu geçmişi analiz et ve müfredatta mantıksal olarak sıradaki, daha önce İŞLENMEMİŞ yeni bir konu seç.
Seçtiğin konu için en az 1500 kelimelik, öğrencilerin ufkunu açacak kapsamlı bir ders notu hazırla.

AKADEMİK KURALLAR:
1. İçerik Markdown formatında olsun (HTML kullanma), en az 3 detaylı alt başlık (##) içersin.
2. Python, C++ veya SQL kod blokları yaz (``` ile) ve mimariyi açıkla. Kodlarda hata/sınır kontrolü yap.
3. Matematiksel formüller için KaTeX formatı ($$ formül $$) kullan.
4. Notun sonuna "Gelecek Ders İçin İpucu" bölümü ekle.
5. İçeriğin en altına günün tarihini ({turkce_tarih(simdi)}) ve konuyu özetleyen 5 adet modern hashtag ekle.

YANIT FORMATI: Yalnızca "baslik" ve "icerik" alanlarını içeren geçerli JSON döndür.
"icerik" tüm ders içeriğini Markdown olarak taşır.
"""


def ders_uret(client: genai.Client, prompt: str, mevcut_basliklar: set) -> Ders:
    son_hata = None
    for deneme in range(1, MAX_DENEME + 1):
        # İlk 3 deneme ana modelle; yedek tanımlıysa kalanlar yedekle
        model = MODEL_ADI if (deneme <= 3 or not YEDEK_MODEL) else YEDEK_MODEL
        try:
            logger.info(f"Yapay zeka yeni konuyu hazırlıyor... (Deneme {deneme}/{MAX_DENEME}, model: {model})")
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=Ders,
                    max_output_tokens=16384,
                ),
            )

            if not response.text:
                raise ValueError("Boş yanıt geldi (güvenlik filtresi olabilir).")

            ders = Ders.model_validate_json(response.text)

            if not ders.baslik.strip():
                raise ValueError("Başlık boş.")
            if ders.baslik.strip().lower() in mevcut_basliklar:
                raise ValueError(f"Bu başlık zaten işlenmiş: {ders.baslik}")

            kelime = len(ders.icerik.split())
            if kelime < MIN_KELIME:
                raise ValueError(f"İçerik çok kısa ({kelime} kelime < {MIN_KELIME}).")

            return ders

        except errors.APIError as e:
            # Kalıcı hatalarda (anahtar, model adı, geçersiz istek) beklemeye gerek yok
            if e.code in (400, 401, 403, 404):
                raise RuntimeError(f"Kalıcı API hatası, tekrar denenmeyecek: {e}") from e
            son_hata = e
            logger.error(f"Geçici API hatası: {e}")
        except Exception as e:
            son_hata = e
            logger.error(f"Hata oluştu: {e}")

        if deneme < MAX_DENEME:
            bekleme = 15 * (2 ** (deneme - 1))  # 15, 30, 60, 120 sn
            logger.info(f"{bekleme} sn sonra tekrar denenecek.")
            time.sleep(bekleme)

    raise RuntimeError(f"{MAX_DENEME} denemede de ders üretilemedi: {son_hata}")


# ---------------------------------------------------------------------------
# Ana akış
# ---------------------------------------------------------------------------
def otonom_sistemi_baslat() -> None:
    logger.info("--- 🧠 CS101 Otonom Akademik Not Sistemi Başlatılıyor ---")
    client = istemci_olustur()
    simdi = datetime.now(TZ)

    veri = veri_yukle()
    mevcut_basliklar = {b.get("baslik", "").strip().lower() for b in veri["bolumler"]}

    ders = ders_uret(client, prompt_olustur(veri["bolumler"], simdi), mevcut_basliklar)

    sure = okuma_suresi_hesapla(ders.icerik)
    zorluk = akademik_zorluk_hesapla(ders.icerik)
    meta = f"> ⏱️ **Tahmini Okuma Süresi:** {sure} dakika | 🎚️ **Zorluk Derecesi:** {zorluk}\n\n---\n\n"

    veri["bolumler"].append({
        "id": yeni_id_uret(veri["bolumler"]),
        "baslik": ders.baslik.strip(),
        "icerik": meta + ders.icerik,
        "ikon": "fa-brain",
    })
    veri["son_guncelleme"] = simdi.strftime("%d.%m.%Y %H:%M")

    guvenli_kaydet(veri)
    logger.info(f"🚀 Başarılı! Yeni ders eklendi: {ders.baslik}")


if __name__ == "__main__":
    otonom_sistemi_baslat()
