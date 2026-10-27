# راهنمای SEO — ایندکس‌شدن آیتم‌ها و اخبار در گوگل و بینگ

این سند یک‌بار اجرا می‌شود و بعد از آن، ربات `tools/seo_ping.py` به‌صورت خودکار
بعد از هر انتشار مقاله، گوگل و بینگ را از تغییرات باخبر می‌کند.

## چه چیزی اضافه شد؟

| قابلیت | توضیح |
|---|---|
| صفحهٔ اختصاصی هر آیتم | `docs/item/<item-name>.html` — عنوان، کیفیت (رنگ رَریتی)، تصویر، مشخصات فارسی و لینک اخبار مرتبط + JSON-LD (`ItemPage` + `BreadcrumbList`) |
| دانشنامهٔ آیتم‌ها | `docs/items.html` — لیست همهٔ آیتم‌ها با جستجوی زنده (این هابِ لینک داخلی برای گوگل است) |
| `sitemap.xml` بهبودیحافته | حالا `<lastmod>` دارد و آیتم‌ها و صفحهٔ دانشنامه را هم شامل می‌شود |
| `news-sitemap.xml` | sitemap مخصوص گوگل‌نیوز (اخبار ۴۸ ساعت اخیر با namespace استاندارد `news:`) |
| `robots.txt` | به هر دو sitemap اشاره می‌کند |
| ربات `tools/seo_ping.py` | بعد از هر push صفحات: ثبت sitemap در Search Console API + اعلان Indexing API + IndexNow (بینگ/یاندکس) با state و محدودیت نرخ |

## انتظار واقع‌بینانه (مهم)

- **ایندکس‌شدن ≠ رتبهٔ اول.** ربات ما سرعتِ «کشف و خزش» را بالا می‌برد؛ رتبه بستگی
  به محتوا، لینک‌های ورودی و تازگی دارد.
- برای اسم آیتم‌های انگلیسی، wowhead تقریباً همیشه اول است. شانس واقعی ما
  جست‌وجوهای **فارسی** و عبارت‌های دم‌بلند (long-tail) مثل
  «اسم آیتم + فارسی / wow / وارکرفت» است — چون منبع فارسی ساخت‌یافته تقریباً فقط ما هستیم.
- دکمهٔ «Request Indexing» در رابط کاربری Search Console هیچ API رسمی ندارد؛
  مسیر رسمی و خودکارِ ما: **Sitemaps API** (کاملاً پشتیبانی‌شده) + **Indexing API**
  (رسماً فقط برای صفحات JobPosting/BroadcastEvent — گوگل ممکن است بقیه را نادیده
  بگیرد؛ ضرری ندارد و ما فقط best-effort می‌زنیم) + **IndexNow** برای بینگ/یاندکس
  (رسمی و بدون محدودیت نوع محتوا).

---

## قدم ۱ — تأیید مالکیت در Google Search Console (۵ دقیقه)

1. به [search.google.com/search-console](https://search.google.com/search-console) برو با اکانت گوگل خودت.
2. **Add property → URL prefix** و این را بزن (کل زیرها را پوشش می‌دهد):
   `https://pvwvuow.github.io/wowheadFA/`
3. در صفحهٔ تأیید مالکیت، روش **HTML tag** را انتخاب کن. یک متاتگ شبیه این می‌دهد:
   `<meta name="google-site-verification" content="abc123..." />`
   فقط محتوای `content` (توکن) را کپی کن.
4. در گیت‌هاب ریپوی `wowheadFA`: **Settings → Secrets and variables → Actions →
   New repository secret** به نام `GSC_VERIFY_TOKEN` و توکن را بگذار.
5. یک اجرای دستی بزن: **Actions → build-site → Run workflow**. بعد از اتمام،
   در Search Console روی **Verify** بزن (چون build ما متاتگ را در `<head>` همهٔ
   صفحات تزریق می‌کند و با هر rebuild هم می‌ماند).
6. (اختیاری ولی توصیه‌شده) پراپرتی دوم برای سایت اصلی:
   `https://pvwvuow.github.io/wow/` — همان مراحل؛ متاتگ باید در HTMLهای آن ریپو
   هم اضافه شود (می‌توانی صفحه‌به‌صفحه دستی بگذاری یا از من بخواهی تا اضافه کنم).

## قدم ۲ — سرویس‌اککانت گوگل برای ربات (۱۰ دقیقه)

1. به [console.cloud.google.com](https://console.cloud.google.com) برو →
   **ساخت پروژه** (مثلاً `wowfarsi-seo`).
2. **APIs & Services → Library** → این دو را Enable کن:
   - `Indexing API`
   - `Search Console API` (نام قدیمی: Webmaster Tools)
3. **APIs & Services → Credentials → Create Credentials → Service account**
   (اسم دلخواه، مثلاً `seo-bot`) → بعد در تب بالای صفحهٔ سرویس‌اککانت:
   **Keys → Add key → Create new key → JSON** → فایل JSON دانلود می‌شود.
4. در Search Console، برای **هر دو** پراپرتی:
   **Settings → Users and permissions → Add user** → ایمیل سرویس‌اککانت
   (چیزی شبیه `seo-bot@wowfarsi-seo.iam.gserviceaccount.com`) با نقش **Owner**.
   ⚠️ بدون این قدم، API خطای 403 می‌دهد.
5. محتوای کامل فایل JSON را در secret جدیدی به نام `GSC_SA_JSON` بگذار.

## قدم ۳ — متغیر پراپرتی‌ها و کلید IndexNow

- در **Settings → Secrets and variables → Actions → تب Variables** یک متغیر
  `GSC_SITES` بساز با مقدار (اگر پراپرتی دوم را هم ساختی):
  ```
  https://pvwvuow.github.io/wowheadFA/,https://pvwvuow.github.io/wow/
  ```
  (اگر فقط wowheadFA را داری: فقط همان یکی.)
- در تب **Secrets** یک secret به نام `INDEXNOW_KEY` با این مقدار بساز:
  ```
  4d2cddeaa148499eb4c321ad054836bd
  ```
  این کلید عمومی است (طراحی IndexNow این‌طور است)؛ فایل `docs/<key>.txt` هم با
  هر build خودکار ساخته می‌شود تا بینگ مالکیت را چک کند. این کلید هم برای
  wow و هم wowheadFA (هم‌هاست) کار می‌کند.

## قدم ۴ — تست

1. **Actions → build-site → Run workflow** (دستی).
2. لاگ استپِ «SEO ping (GSC sitemaps + Indexing API + IndexNow)» را باز کن —
   باید چنین چیزهایی ببینی:
   ```
   seo: N changed URL(s) of M to submit
   seo: GSC sitemap submitted: https://.../sitemap.xml -> property ...
   seo: IndexNow accepted N URLs (HTTP 200)
   ```
3. در Search Console: **Sitemaps** — هر دو sitemap باید ثبت و «Success» باشند.
4. بعد از ۲۴ تا ۷۲ ساعت در **Performance** و با کوئری `site:pvwvuow.github.io/wowheadFA`
   در خود گوگل، شروعِ ایندکس را می‌بینی.
5. برای بینگ: [bing.com/webmasters](https://bing.com/webmasters) → Add site →
   import از Search Console (یا sitemap را دستی بده).

## نگهداری

- ربات هر بار فقط URLهای «تغییریافته» را می‌فرستد (state در `data/seo_state.json`
  با فاصلهٔ حداقل ۱ ساعت بین هر URL) — بدون اسپم و بدون خطای quota.
- اگر secretها را خالی بگذاری، ربات بدون خطا skip می‌کند؛ چیزی خراب نمی‌شود.
- محدودیت Indexing API گوگل حدود ۲۰۰ درخواست/روز است؛ ما سقف ۱۰ در هر اجرا
  گذاشته‌ایم که خیلی پایین‌تر از quota است.
- برای حذف یک URL از گوگل: Search Console → Removals (دستی، چون عملیات حساسی است).

## چرا با این ساختار «اسم آیتم در گوگل» جواب می‌دهد؟

1. هر آیتم حالا یک URL مستقل با `<h1>` انگلیسی، عنوان صفحهٔ شامل اسم آیتم و
   توضیحات فارسی دارد — دقیقاً همان چیزی که گوگل برای کوئری «اسم آیتم + فارسی»
   لازم دارد.
2. JSON-LD (`ItemPage` + `BreadcrumbList`) به گوگل می‌گوید این صفحهٔ موجودیت
   است، نه پست متفرقه.
3. دانشنامهٔ `items.html` همهٔ آیتم‌ها را به هم لینک می‌دهد (hub Page) و از
   مقالات هم به آیتم‌ها لینک هست — خزنده‌ها از هر دو طرف می‌رسند.
4. news-sitemap مقاله‌های تازه را در صف خزش سریع گوگل می‌گذارد و از همان‌جا
   لینک‌های آیتم هم دنبال می‌شوند.
