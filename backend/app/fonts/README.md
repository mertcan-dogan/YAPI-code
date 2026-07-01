# PDF Fonts — Türkçe Karakter Desteği (CR-005-A)

`reports.py` PDF üretiminde Türkçe karakterlerin (ş, ğ, ı, İ, ü, ö, ç …) ■
sembolü olarak görünmemesi için bu klasördeki Unicode TrueType fontlar kullanılır.

- `DejaVuSans.ttf` — normal metin
- `DejaVuSans-Bold.ttf` — kalın metin
- `DejaVuSans-Oblique.ttf` — italik metin

> **Not:** Bu dosyalar, DejaVu ailesinin doğrudan üst kaynağı olan **Bitstream Vera**
> fontlarından (ReportLab paketiyle birlikte gelen `Vera.ttf` / `VeraBd.ttf` /
> `VeraIt.ttf`) elde edilmiştir. Kurulum ortamında internet erişimi olmadığından
> resmi DejaVu dağıtımı indirilemedi; Bitstream Vera tüm Türkçe karakter setini
> (Latin-1 + Latin Extended-A) eksiksiz kapsar, bu yüzden ■ sorunu çözülür.
> İnternet erişimi olan bir ortamda https://dejavu-fonts.github.io adresinden
> resmi DejaVu TTF dosyalarıyla bire bir değiştirilebilir (dosya adları aynı).

Bitstream Vera lisansı: serbest/açık kaynak (bitstream-vera-license.txt).

---

## Lato (CR-036 — PDF Tasarım Sistemi)

`lato/` klasörü, CR-036 "Heneka" PDF tasarım sistemi için kullanılan **Lato**
yazı tipi ailesinin 6 ağırlığını içerir:

- `Lato-Light.ttf` · `Lato-Regular.ttf` · `Lato-Medium.ttf`
- `Lato-Semibold.ttf` · `Lato-Bold.ttf` · `Lato-Black.ttf`

Lato, tüm Türkçe karakterleri (ş, ğ, ı, İ, ü, ö, ç) ve ₺ / € / $ sembollerini
eksiksiz kapsar; Aylık Yönetim Raporu'nda hem ReportLab metinlerinde hem de
matplotlib grafiklerinde (`font.family="Lato"`) kullanılır. DejaVu, yedek
(fallback) aile olarak kayıtlı kalır.

> **Lisans:** Lato, **SIL Open Font License, Version 1.1** (OFL) ile dağıtılır —
> tasarımcı: Łukasz Dziedzic. OFL, fontların yazılımla birlikte paketlenmesine ve
> belgelere (PDF) gömülmesine açıkça izin verir. Lisans metni:
> https://scripts.sil.org/OFL  ·  yazı tipi kaynağı: https://www.latofonts.com
