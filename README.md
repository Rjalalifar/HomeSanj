# خانه‌سنج — جست‌وجوی عادی و پیشرفته

مرحلهٔ دوم روی همان معماری محلی توسعه یافته است: جست‌وجوی عادی با فیلتر مرورگر و SQLite، و جست‌وجوی پیشرفته با Qdrant و embedding چندزبانهٔ محلی. توضیح هوشمند AvalAI اختیاری است؛ بدون کلید، مقایسه از شواهد عددی ساخته می‌شود. راهنمای جامع قراردادها، محدودیت‌ها و تحویل: [handoff مرحلهٔ دوم](docs/handoff-phase-2.md).

برای سرویس معنایی، جدا از OTP موجود:

```powershell
docker compose -f compose.qdrant.yml up -d
.\.venv\Scripts\python.exe -m backend.app.semantic download-model --report docs/embedding-verification.json
.\.venv\Scripts\python.exe -m backend.app.semantic index --report docs/qdrant-index-report.json
.\.venv\Scripts\python.exe -m backend.app.semantic reconcile --report docs/qdrant-reconcile-report.json
```

مدل و ایندکس یک‌بار ایجاد و روی دیسک نگه‌داری می‌شوند؛ اجرای عادی برنامه seed یا دانلود مدل را تکرار نمی‌کند. در نبود Qdrant، جست‌وجوی عادی مستقل می‌ماند و جست‌وجوی پیشرفته وضعیت کاهش قابلیت را نشان می‌دهد. Qdrant فقط روی loopback پورت ۶۳۳۳ است و پورت ۸۸۲۱ برای OTP باقی می‌ماند.

جست‌وجوی فارسی اجارهٔ تهران با **React + TypeScript + Vite + Leaflet**، **FastAPI + Pydantic** و **SQLAlchemy 2 + SQLite**. عضویت مکانی در فرانت بررسی می‌شود؛ بک‌اند نیز هندسهٔ اصلی را برای صحت فیلتر و seed اعتبارسنجی می‌کند. state خود React برای این مرحله کافی است. کامنت‌ها و docstringهای کد انگلیسی و رابط فارسی است.

## اجرای PowerShell

از ریشهٔ پروژه، برای نصب اولیه:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
# Copy only if .env does not already exist.
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
.\.venv\Scripts\python.exe -m backend.app.geo
.\.venv\Scripts\python.exe -m backend.app.cli migrate
.\.venv\Scripts\python.exe -m backend.app.cli seed --seed 2026 --dataset-version tehran-2020-v1 --points-per-series-per-neighborhood 5
cd frontend
npm ci
npm run build
cd ..
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:create_app --factory --host 127.0.0.1 --port 8000
```

رابط تولیدی: **http://127.0.0.1:8000**؛ مستندات API: **http://127.0.0.1:8000/docs**.
برای توسعه، بک‌اند را نگه دارید و در ترمینال دیگر `cd frontend` سپس `npm run dev` را اجرا کنید؛ Vite روی پورت ۵۱۷۳ درخواست‌های `/api` را به بک‌اند می‌فرستد. پورت ۸۸۲۱ فقط برای OTP موجود است.

worker همراه سرور اجرا می‌شود. صف و نتایج در SQLite پایدارند و lease منقضی‌شده پس از restart بازیابی می‌شود. برای worker مستقل: `python -m backend.app.cli worker`. یک فرایند سرور برای این MVP کافی است.

## داده و صداقت نمایش

- ۳۷۷ عارضهٔ محله و ۲۲ منطقه؛ عدد ۳۷۶ در نام فایل خام، شمارش رسمی محلات امروز تهران نیست.
- commitهای فایل‌ها نوامبر ۲۰۲۰ هستند؛ تاریخ صحت مرزها معلوم نیست. این مجموعه استخراج تازهٔ OSM یا مرجع رسمی به‌روز نیست.
- نسخهٔ آمادهٔ توصیف‌شده در مشخصات دو خودتقاطع اصلاح‌شده، ۱۲۰ جفت هم‌پوشان بالای یک مترمربع، ۱۰۸ محله با بیش از ۱٪ خروج از منطقهٔ منتسب و ۱۱ مورد با بیش از ۵۰٪ خروج دارد. محاسبات همین پروژه در `data/validation-report.json` ثبت می‌شوند.
- `district_no` انتساب منبع است و خودکار تصحیح نمی‌شود. فیلتر منطقه از نقطه و هندسهٔ منطقه استفاده می‌کند. عضویت چندگانه مبهم است.
- محلات CRS84 دارند؛ WGS84 مناطق از مختصات و هم‌مکانی استنباط شده، چون metadata خالی است. GeoJSON خروجی `[longitude, latitude]` است.
- مجوز صریح داده در مخزن بررسی‌شده مشخص نشده است. provenance، اصل هندسه و روش اصلاح حفظ می‌شوند. attribution کاشی‌های مستقل OpenStreetMap باقی است.
- پوشش کامل شهر ادعا نمی‌شود. حفره و MultiPolygon پشتیبانی می‌شوند؛ فیلتر و seed از هندسهٔ معتبر اصلی استفاده می‌کنند.

[مخزن منبع](https://github.com/mjalalimanesh/tehran-districts-neighborhoods-map-geojson). فایل‌های نسخه‌ثابت، هش‌ها و گزارش تبدیل در `data/` نگه‌داری می‌شوند.

## seed و importer

سه سری `demo_a/demo_b/demo_c` فقط گروه داده‌اند؛ معنای قیمت/کیفیت/دسترسی ندارند. پیش‌فرض ۵ نقطه از هر سری در هر محله است. تعداد واقعی، کمبود و سقف تلاش در `data/seed-report.json` ثبت می‌شوند. seed پایدار است و دادهٔ ذخیره‌شده را بازنویسی نمی‌کند. refresh، sort و فیلتر تصادفی‌سازی ندارند. نقطهٔ چندمحله‌ای رد می‌شود و برای پرکردن تعداد نقطهٔ بیرون مرز ساخته نمی‌شود.

مسیر عمودی کوچک پیش از seed کامل:

```powershell
.\.venv\Scripts\python.exe -m backend.app.cli seed --seed 2026 --dataset-version tehran-2020-v1 --limit-neighborhoods 2 --report data/seed-small-report.json
```

قراردادهای ورود داده، اتصال زنده به سایت نیستند:

```powershell
.\.venv\Scripts\python.exe -m backend.app.cli import tests/fixtures/listings-a.csv --kind csv_a
.\.venv\Scripts\python.exe -m backend.app.cli import tests/fixtures/listings-b.json --kind json_b
```

fixtureها ناقص/تکراری و پیش‌فرض نمایشی‌اند. `--real` فقط برای دادهٔ واقعی است. منبع و شناسهٔ یکسان شاهد ادغام است؛ قیمت و تاریخ خام همهٔ رکوردها حفظ می‌شوند. نام مشابه یا نزدیکی مکانی کافی نیست. مقادیر مفقود null و پول صحیح تومان است. ودیعه و اجاره مستقل‌اند. قیمت فرضی، قیمت بازار معرفی نمی‌شود.

## OTP و شبکه

پیش‌فرض بک‌اند همین دستگاه `http://127.0.0.1:8821` است. ریشهٔ وب endpoint مسیریابی نیست. تا کشف API، `OTP_API_PATH` خالی و adapter برابر `not_configured` می‌ماند. هیچ OTP یا graph جدیدی نصب/ساخته نمی‌شود.

گزارش اتصال `root_reachable`، `routing_api_verified` و `fixture_mode` را جدا نگه می‌دارد. fixture فقط با تنظیم صریح فعال می‌شود. `live_otp` یعنی فراخوانی جاری، نه الزاماً realtime؛ cache با `recorded_otp` ثبت می‌شود. schedule و realtime مستقل‌اند. خطا و نبود مسیر جدا هستند و زمان ساختگی جای مسیر واقعی نمی‌نشیند.

در Docker Desktop فقط پس از آزمون از داخل همان کانتینر از `http://host.docker.internal:8821` استفاده کنید. loopback کانتینر خود کانتینر است. در Linux ممکن است `extra_hosts: ["host.docker.internal:host-gateway"]` لازم باشد؛ این نگاشت دسترسی به سرویسی با bind فقط loopback را تضمین نمی‌کند. bind/firewall را بررسی کنید. در شبکهٔ مشترک Docker نام سرویس و پورت داخلی را از تنظیمات واقعی بگیرید. cloud به loopback دستگاه کاربر وصل نمی‌شود؛ پروژه tunnel یا عمومی‌سازی نمی‌کند.

مراجع: [Docker networking](https://docs.docker.com/desktop/features/networking/)، [host-gateway](https://docs.docker.com/reference/cli/docker/container/run/#add-entries-to-container-hosts-file---add-host).

## AvalAI

پیش‌فرض `LLM_ENABLED=false` است. بدون کلید، فرم و parser محدود با برچسب «حالت نمونه بدون LLM» کار می‌کنند. مثال: «اجاره تا ۱۵ میلیون تومان و حداقل ۲ اتاق و پارکینگ الزامی». متن درک‌نشده نمایش داده می‌شود و مقصد حدس زده نمی‌شود. پیشنهاد patch پیش از اعمال نمایش داده می‌شود.

SDK سازگار OpenAI از `https://api.avalai.ir/v1`، `chat/completions` و فهرست مدل حساب در `models` استفاده می‌کند. مدل هر نقش `gemini-3.6-flash` است؛ جایگزینی بی‌صدا و alias latest نداریم. json_schema ادعا نمی‌شود؛ JSON محدود با Pydantic و یک اصلاح محدود اعتبارسنجی می‌شود. هر تلاش/ retry حتی پس از timeout بودجه رزرو می‌کند؛ 401/403 retry نمی‌شوند. کلید در مرورگر/URL/گزارش نیست.

smoke واقعی نیاز به کلید backend، `LLM_ENABLED=true` و فرمان صریح زیر دارد و ممکن است هزینه داشته باشد:

```powershell
.\.venv\Scripts\python.exe -m backend.app.cli avalai-smoke --allow-paid --max-requests 1
```

سقف خروجی smoke برای هر مدل ۶۴ token، retry خاموش و سقف رزرو روزانه برقرار است. seed و آزمون‌های عادی پولی نیستند. parser/explainer/judge/improvement تنظیم و نسخهٔ مستقل دارند؛ judge و پیشنهاد آزمایش خودکار در این مرحله اجرا نمی‌شود.

## بررسی و handoff

```powershell
.\.venv\Scripts\python.exe -m pytest -q
cd frontend
npm test
npm run build
```

آزمون‌های واحد آفلاین‌اند. [قرارداد state و API](docs/phase-1-contract.md) و [تحویل مرحلهٔ اول](docs/handoff-phase-1.md) مستقل از تاریخچهٔ گفتگو قابل استفاده‌اند. برای تولید مجدد schema و typeها: `python -m backend.app.export_schema`.


## تحویل مرحلهٔ سوم

پیاده‌سازی ارزیابی، بازبینی داخلی، دادهٔ برچسب‌گذاری نسخه‌دار، worker آفلاین و مقایسه/rollback کنترل‌شده تکمیل شده است. پنل در `/internal` از همان برنامه اجرا می‌شود؛ دسترسی آن نیازمند `REVIEW_API_TOKEN` یا توکن مستقل هر بازبین در تنظیمات backend است. کامنت‌های کد انگلیسی‌اند.

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:create_app --factory --host 127.0.0.1 --port 8000
```

[راهنمای تحویل مرحلهٔ سوم](docs/handoff-phase-3.md)، [ماتریس پذیرش](docs/phase-3-acceptance-matrix.md) و [نتایج واقعی بررسی‌ها](docs/phase-3-verification-report.json) مرجع وضعیت فعلی‌اند. راهنمای مراحل پیشین: [مرحلهٔ اول](docs/handoff-phase-1.md) و [مرحلهٔ دوم](docs/handoff-phase-2.md).

۵۶۵۵ آگهی نمایشی ذخیره شده‌اند؛ اتصال واقعی OTP در `/otp/transmodel/v3` با پنج مسیر و سلامت ایندکس Qdrant بررسی شده‌اند. کلید backend مربوط به AvalAI موجود است، اما همهٔ نقش‌های مدل غیرفعال‌اند و آزمون پولی اجرا نشده است. شمارش تعویض و مبنای schedule همچنان تابع شواهد همان پاسخ مسیریابی‌اند.

چرخهٔ تغییر وزن رتبه‌بندی و rollback در محدودهٔ آزمایشی بررسی شده است. تعداد برچسب مستقل انسانی صفر است؛ بهبود واقعی کیفیت، QS کاربران واقعی و انتشار رتبه‌بندی جدید در محیط اصلی ادعا یا انجام نشده‌اند. دادهٔ خروجی بازبینی مرورگر با منشأ `test_fixture` نگه‌داری می‌شود.

[Automatic accessibility handoff, API and cache policy](docs/handoff-accessibility.md).
