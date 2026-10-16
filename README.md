# Banka Kampanyaları Scraper

Açık ve herkese açık banka kampanya sayfalarından bilgileri **salt-okunur** biçimde toplayan, yerel web panelinden yönetilen Python + Playwright başlangıç projesi.

> **Kapsam:** Bu araç kampanya/marketing sayfaları içindir; internet bankacılığına girmez, giriş yapmaz, OTP/MFA/CAPTCHA çözmez, erişim kontrolünü atlatmaz ve tarayıcı profil dosyalarını okumaz/kopyalamaz. Bir sayfa kimlik doğrulama veya bot kontrolü istiyorsa durur ve bunu çalıştırma kaydına yazar. Kullanım öncesinde ilgili sitenin kullanım koşullarını ve erişim kurallarını kontrol edin.

## Özellikler

- FastAPI tabanlı yerel web arayüzü: banka kaynağı ekleme, etkin/pasif yapma, scrape çalıştırma, son çalıştırmaları ve bulunan kampanyaları görüntüleme.
- Playwright Chromium entegrasyonu: Chrome veya Brave gibi Chromium tarayıcılarına yalnızca loopback CDP portundan bağlanma; istenirse açıkça yapılandırılmış tarayıcı + profil yolu ile başlatma.
- Kaynak başına CSS seçicileri (kart, başlık, açıklama, link, başlangıç/bitiş tarihi) yapılandırma.
- SQLite ile kalıcı kayıt, URL/başlık bazlı tekilleştirme, çalıştırma geçmişi ve hata durumları.
- JSON/CSV dışa aktarma.
- Zaman aşımı, sayfa/öğe limitleri, alan adı kontrolü, eşzamanlı çalıştırma kilidi, hata izolasyonu ve temel testler.
- Agent’ların değiştirebileceği küçük modüller; kaynak yapılandırması ile çıkarım mantığı birbirinden ayrıdır.

## Kurulum

Python 3.11+ önerilir.

    python -m venv .venv
    # Windows PowerShell:
    .venv\Scripts\Activate.ps1
    # macOS/Linux:
    source .venv/bin/activate
    pip install -r requirements.txt
    playwright install chromium

Windows için .env.example dosyasını .env olarak kopyalayıp gerekiyorsa düzenleyin. Varsayılan olarak panel yalnızca 127.0.0.1:8000 üzerinde dinler.

    uvicorn app.main:app --host 127.0.0.1 --port 8000

Tarayıcıdan http://127.0.0.1:8000 adresini açın.

## Playwright ve tarayıcı profili

**Tercih edilen yöntem:** Chrome/Brave’i yalnızca yerel bir debugging portuyla kendiniz başlatın; ardından .env içindeki BROWSER_CDP_URL değerini ayarlayın. Mevcut profilin aynı anda başka bir tarayıcı işlemi tarafından kullanılması desteklenmeyebilir.

Örnek (Windows; yolları kendi kurulumuna göre değiştir):

    # Chrome/Brave bütün pencerelerini kapatın; tercihen ayrı bir profil kullanın.
    & "$env:ProgramFiles\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="$env:LOCALAPPDATA\BankCampaignScraper\ChromeProfile"

Brave için BROWSER_EXECUTABLE değerini Brave yürütülebilir dosyasına ayarlayın. Aynı tarayıcıyı başka bir CDP portunda çalıştırıyorsanız BROWSER_CDP_URL=http://127.0.0.1:9222 değerini güncelleyin.

İsteğe bağlı olarak uygulama tarayıcıyı başlatabilir:
- BROWSER_EXECUTABLE: Chrome/Brave çalıştırılabilir dosyasının tam yolu.
- BROWSER_USER_DATA_DIR: yalnızca bu araç için ayrılmış profil dizini.
- BROWSER_PROFILE_DIRECTORY: genelde Default.
- BROWSER_CDP_PORT: varsayılan 9222.
- AUTO_LAUNCH_BROWSER=true: CDP endpoint bulunmuyorsa yapılandırılmış tarayıcıyı başlatmayı dene.

Uygulama yalnızca 127.0.0.1 / localhost CDP endpoint'lerine bağlanır. Uzak ağlara debugging portu açmayın. Tarayıcı profilleri oturum çerezleri içerebilir; profil klasörünü Git'e eklemeyin, paylaşmayın veya yedek çıktılara koymayın. Güvenlik için ayrı, oturum açılmamış profil kullanılması tavsiye edilir.

## Kaynak ekleme

Panelde Banka ekle formundan kampanya liste sayfası URL'sini girin. Siteye göre CSS seçicileri belirtin. Örnek:

- Kart: .campaign-card
- Başlık: h2
- Açıklama: .campaign-description
- Link: a
- Son tarih: .campaign-end-date

Seçiciler her bankanın HTML yapısına göre değişir. Önce hedef sayfayı normal tarayıcıda inceleyip doğru seçicileri belirleyin. Seçici boş bırakılırsa genel çıkarım denenir; genel çıkarımın kusursuz olması beklenmemelidir. Üretimde her banka için küçük, özel bir adapter veya doğrulanmış seçiciler kullanın. Tarihler ham metin olarak korunur.

Kaynak JSON dosyası config/sources.json içindedir. Panelden değişiklik yapmak bu dosyayı atomik şekilde günceller.

## Verinin saklanması

- Varsayılan SQLite: data/campaigns.sqlite3
- JSON: GET /api/export?format=json
- CSV: GET /api/export?format=csv
- Liste API'si: GET /api/campaigns
- Çalıştırmalar: GET /api/runs
- Durum: GET /api/status

SQLite dosyası kampanya metaverisi ve çalıştırma durumlarını saklar. Ham HTML, çerezler, local storage, form alanları veya profil dosyaları kaydedilmez.

## Mimari

    app/main.py        FastAPI UI/API, çalışma kilidi ve orkestrasyon
    app/config.py      Ortam değişkenleri ve yollar
    app/models.py      Pydantic veri sözleşmeleri + URL/selector doğrulaması
    app/browser.py     Loopback CDP bağlantısı ve isteğe bağlı tarayıcı başlatma
    app/scraper.py     Sayfa gezintisi, erişim-kontrolü tespiti, CSS/genel çıkarım
    app/storage.py     SQLite, tekilleştirme ve geçmiş
    app/static/        Yerel web paneli
    config/            Banka/kampanya kaynakları
    tests/             Ağ gerektirmeyen birim testleri

Bir scrape akışı: etkin kaynakları yükle → tarayıcıya bağlan → kaynakları sırayla gez → yalnızca herkese açık sayfa içeriğini çıkar → tekilleştirip SQLite'a kaydet → çalıştırma özetini tamamla. Bir bankadaki hata diğer bankaları durdurmaz.

## Operasyonel sınırlar ve kontrol listesi

1. Kaynakları yalnızca kampanya/duyuru alan adlarıyla sınırla; portal, hesap, ödeme veya müşteri sayfaları ekleme.
2. Kullanım koşulları, robots kuralları ve istek sıklığını kontrol et; düşük hızla ve elle başlatılan çalıştırmalarla başla.
3. CAPTCHA, bot kontrolü, giriş, MFA/OTP veya erişim reddi olduğunda otomasyonu durdur; korumayı aşmaya çalışma.
4. Paneli internete açma. Varsayılan loopback bağlamasını değiştirme; erişim kontrolü olmayan bu panel yerel geliştirme aracıdır.
5. Profil klasörlerini, veritabanını, .env dosyasını ve gerçek kullanıcı verilerini commit etme.
6. Kampanya verisini yayınlamadan önce kaynağa, güncelliğe, tarih aralığına ve yinelenen kayıtlara karşı doğrula.
7. Tarayıcı/Playwright güncellemelerinde testleri çalıştır; selector değişikliklerini banka bazlı test fixture'larıyla yakala.

## Testler

    pytest -q

Testler varsayılan olarak gerçek banka sitelerine bağlanmaz.

## Agent'lar için genişletme noktaları

- Yeni banka: panelden kaynak ekle veya config/sources.json dosyasına kayıt ekle.
- HTML değişti: kaynağın CSS seçicilerini düzenle; genel çıkarımı ilk çözüm olarak büyütmek yerine banka-özel adapter ekle.
- Yeni alan: app/models.py içindeki CampaignRecord, app/storage.py şeması/serileştirme ve app/static/index.html tablosunu birlikte güncelle; migration ekle.
- Farklı veritabanı: yalnızca app/storage.py arayüzünü değiştir; scraper doğrudan SQL çalıştırmamalı.
- Planlayıcı / kuyruk: app/main.py içine uzun ömürlü scheduler koymak yerine ayrı worker/queue katmanı ekle.
- Daha iyi çıkarım: app/scraper.py içindeki çıkarım mantığını küçük fonksiyonlara ayır; her adapter için fixture ve test ekle.
- Yeni çıktı: /api/export route'una format ekle; verinin doğruluğunu UI'dan bağımsız test et.

## Sınırlamalar

Bankaların sayfa HTML'leri ve kampanya kartları birbirinden farklıdır. Proje çalışır bir iskelet ve genel çıkarım sunar; ilk kullanımda kaynak başına seçici doğrulaması gerekir. Gerçek web sitelerinde canlı uçtan uca test, kullanıcı ortamı ve sayfaların güncel DOM yapısına bağlıdır.