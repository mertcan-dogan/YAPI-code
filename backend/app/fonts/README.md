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
