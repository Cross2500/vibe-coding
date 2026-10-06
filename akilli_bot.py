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
MODEL_ADI = os.environ.get("GEMINI_MODEL", "gemini-3-flash-preview")
YEDEK_MODEL = os.environ.get("GEMINI_FALLBACK_MODEL", "gemini-3.8-flash")
MAX_DENEME = 5
MIN_KELIME = 700   # Bunun altı "çok kısa" sayılıp yeniden denenir
HEDEF_BOLUM = 10   # Her dersin toplam bölüm sayısı (dolunca o ders atlanır)
TZ = ZoneInfo("Europe/Istanbul")
AYLAR = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
         "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]

# Dersler: yeni ders eklemek için buraya bir blok daha ekleyebilirsin.
DERSLER = [
    {
        "ad": "Algoritmalar ve Bellek Yönetimi",
        "aciklama": "Algoritma analizi, asimptotik notasyon, veri yapıları, bellek modeli, "
                    "arama ve sıralama, özyineleme, graf algoritmaları, dinamik programlama.",
    },
    {
        "ad": "Lineer Cebir",
        "aciklama": "Vektörler, matrisler, lineer denklem sistemleri, determinant, "
                    "özdeğer ve özvektörler, matris ayrışımları (LU, SVD) ve mühendislik uygulamaları.",
    },
    {
        "ad": "Yapay Zeka ve Veri Bilimi",
        "aciklama": "Veri ön işleme, istatistik, regresyon, sınıflandırma, gradyan inişi, "
                    "sinir ağları, değerlendirme metrikleri, derin öğrenme ve modern mimariler.",
    },
]

# Derssiz kalan eski bölümlerin hangi derse ve kaçıncı sıraya gireceği
ESKI_BOLUMLER = {
    "bolum-1": ("Algoritmalar ve Bellek Yönetimi", 1),
    "bolum-2": ("Lineer Cebir", 1),
    "bolum-4": ("Yapay Zeka ve Veri Bilimi", 1),
}

SEVIYELER = {
    "temel": ("🟢 Temel Seviye",
              "Kavramları ve sezgiyi sıfırdan kur. Küçük, basit örnekler kullan; önkoşul bilgiyi minimumda tut."),
    "orta": ("🟡 Orta Seviye",
             "Önceki bölümlerin bilindiğini varsay. Formal tanımlar, analiz ve gerçekçi uygulamalar ekle."),
    "ileri": ("🔴 İleri Seviye",
              "İleri teknikler, optimizasyon, uç durumlar ve gerçek dünya mühendislik uygulamalarına gir."),
}

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


def seviye_anahtari(sira: int) -> str:
    oran = sira / HEDEF_BOLUM
    if oran <= 0.3:
        return "temel"
    if oran <= 0.7:
        return "orta"
    return "ileri"


def turkce_tarih(dt: datetime) -> str:
    return f"{dt.day} {AYLAR[dt.month - 1]} {dt.year}"


def istemci_olustur() -> genai.Client:
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        logger.error("KRİTİK HATA: GEMINI_API_KEY bulunamadı! GitHub Secrets'ı kontrol et.")
        sys.exit(1)
    # Tek bir istek 5 dakikadan uzun asılı kalırsa kesilir ve yeniden denenir (milisaniye)
    return genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(timeout=300_000),
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
        veri["son_guncelleme"] = okunan.get("son_guncelleme", "")
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


def eski_bolumleri_duzenle(bolumler: list) -> bool:
    """Ders bilgisi olmayan eski bölümlere ders, sıra ve seviye ekler."""
    degisti = False
    for b in bolumler:
        if b.get("ders"):
            continue
        ders, sira = ESKI_BOLUMLER.get(b.get("id"), ("Diğer Notlar", 1))
        b["ders"] = ders
        b["sira"] = sira
        b["seviye"] = SEVIYELER[seviye_anahtari(sira)][0]
        degisti = True
    return degisti


def siradaki_ders_sec(bolumler: list):
    """En az bölümü olan (tamamlanmamış) dersi ve yazılacak bölüm sırasını döndürür."""
    son_sira = {d["ad"]: 0 for d in DERSLER}
    for b in bolumler:
        ad = b.get("ders")
        if ad in son_sira:
            son_sira[ad] = max(son_sira[ad], int(b.get("sira", 0) or 0))

    adaylar = [d for d in DERSLER if son_sira[d["ad"]] < HEDEF_BOLUM]
    if not adaylar:
        return None, 0
    ders = min(adaylar, key=lambda d: son_sira[d["ad"]])  # eşitlikte listedeki sıra kazanır
    return ders, son_sira[ders["ad"]] + 1


def prompt_olustur(ders: dict, sira: int, bolumler: list, simdi: datetime) -> str:
    oncekiler = sorted(
        [b for b in bolumler if b.get("ders") == ders["ad"]],
        key=lambda b: b.get("sira", 0),
    )
    onceki_liste = "\n".join(f"{b.get('sira')}. {b.get('baslik')}" for b in oncekiler) \
        or "Henüz bölüm yok."
    etiket, yonerge = SEVIYELER[seviye_anahtari(sira)]

    return f"""
Sen MIT ve Stanford seviyesinde ders veren, vizyoner bir Bilgisayar Mühendisliği Profesörüsün.
Bir ders müfredatını temelden zora doğru, bölüm bölüm yazıyorsun.

DERS: {ders["ad"]}
DERSİN KAPSAMI: {ders["aciklama"]}

Bu derste şimdiye kadar işlenen bölümler (sırayla):
{onceki_liste}

GÖREV: Bu dersin {sira}. bölümünü yaz ({HEDEF_BOLUM} bölümlük müfredatın {sira}/{HEDEF_BOLUM}. adımı).
SEVİYE: {etiket}. {yonerge}
Önceki bölümlerin üzerine inşa et: yukarıdaki listeden bir adım daha ileri, daha önce İŞLENMEMİŞ yeni bir konu seç.
Konuyu seçerken dersin kapsamındaki konuları mantıklı bir öğrenme sırasında ilerlet.
Yaklaşık 1200 kelimelik, öğrencilerin ufkunu açacak kapsamlı bir ders notu hazırla.

AKADEMİK KURALLAR:
1. İçerik Markdown formatında olsun (HTML kullanma), en az 3 detaylı alt başlık (##) içersin.
2. Python, C++ veya SQL kod blokları yaz (``` ile) ve mimariyi açıkla. Kodlarda hata/sınır kontrolü yap.
3. Matematiksel formüller için KaTeX formatı ($$ formül $$) kullan.
4. Notun sonuna "Gelecek Ders İçin İpucu" bölümü ekle.
5. İçeriğin en altına günün tarihini ({turkce_tarih(simdi)}) ve konuyu özetleyen 5 adet modern hashtag ekle.

YANIT FORMATI: Yalnızca "baslik" ve "icerik" alanlarını içeren geçerli JSON döndür.
"baslik" sadece konunun adı olsun (ders adını ve bölüm numarasını yazma).
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
            # Kalıcı hatalarda (anahtar, geçersiz istek) beklemeye gerek yok.
            # 404 (model yok) ise yedek model denenebilsin diye sadece ana modelde atlanır.
            if e.code in (400, 401, 403):
                raise RuntimeError(f"Kalıcı API hatası, tekrar denenmeyecek: {e}") from e
            if e.code == 404 and model == YEDEK_MODEL:
                raise RuntimeError(f"Yedek model de bulunamadı: {e}") from e
            son_hata = e
            logger.error(f"API hatası ({model}): {e}")
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
    duzenlendi = eski_bolumleri_duzenle(veri["bolumler"])

    ders_tanimi, sira = siradaki_ders_sec(veri["bolumler"])
    if ders_tanimi is None:
        logger.info(f"Tüm dersler {HEDEF_BOLUM} bölüme ulaştı. Yeni ders yazılmayacak.")
        if duzenlendi:
            guvenli_kaydet(veri)
        return

    logger.info(f"Seçilen ders: {ders_tanimi['ad']} | Bölüm: {sira}/{HEDEF_BOLUM}")

    mevcut_basliklar = {b.get("baslik", "").strip().lower() for b in veri["bolumler"]}
    prompt = prompt_olustur(ders_tanimi, sira, veri["bolumler"], simdi)
    ders = ders_uret(client, prompt, mevcut_basliklar)

    seviye_etiketi = SEVIYELER[seviye_anahtari(sira)][0]
    sure = okuma_suresi_hesapla(ders.icerik)
    meta = f"> ⏱️ **Tahmini Okuma Süresi:** {sure} dakika | 🎚️ **Seviye:** {seviye_etiketi}\n\n---\n\n"

    veri["bolumler"].append({
        "id": yeni_id_uret(veri["bolumler"]),
        "ders": ders_tanimi["ad"],
        "sira": sira,
        "seviye": seviye_etiketi,
        "baslik": ders.baslik.strip(),
        "icerik": meta + ders.icerik,
        "ikon": "fa-book",
    })
    veri["son_guncelleme"] = simdi.strftime("%d.%m.%Y %H:%M")

    guvenli_kaydet(veri)
    logger.info(f"🚀 Başarılı! Yeni bölüm eklendi: {ders_tanimi['ad']} / {ders.baslik}")


if __name__ == "__main__":
    otonom_sistemi_baslat()
