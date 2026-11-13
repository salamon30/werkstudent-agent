#!/usr/bin/env python3
"""
Werkstudent Job Search — Daily Email Digest
Her sabah 08:00'de launchd tarafından çalıştırılır.
"""

import os
import json
import smtplib
import re
import time
import requests
from bs4 import BeautifulSoup
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

GMAIL_USER = os.environ["GMAIL_USER"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
EMAIL_TO = os.environ["EMAIL_TO"]

SEEN_FILE = os.path.join(os.path.dirname(__file__), "seen_jobs.json")
SEEN_EXPIRY_DAYS = 45  # bu kadar gün sonra "eski" sayılır, tekrar görünebilir


def load_seen() -> dict:
    if not os.path.exists(SEEN_FILE):
        return {}
    with open(SEEN_FILE) as f:
        return json.load(f)


def save_seen(seen: dict) -> None:
    cutoff = (datetime.now() - timedelta(days=SEEN_EXPIRY_DAYS)).isoformat()
    pruned = {url: date for url, date in seen.items() if date > cutoff}
    with open(SEEN_FILE, "w") as f:
        json.dump(pruned, f, indent=2)

CITIES = ["München", "Nürnberg", "Regensburg", "Erlangen", "Forchheim", "Munich", "Nuremberg"]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9,de-DE;q=0.8,de;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

ENGLISH_SIGNALS = re.compile(
    r"\b(machine learning|data science|computer vision|deep learning|"
    r"embedded systems|working student|software engineer|software developer|"
    r"data engineer|data analyst|python|iot|automotive|adas|edge ai|"
    r"neural network|artificial intelligence|genai|robotics|intern|internship|english)\b",
    re.I,
)

# Başlıkta bu alanlar varsa ilan kesinlikle elenir (hukuk, finans, satış, HR, Senior/Lead/Manager vs.)
EXCLUDED_FIELDS = re.compile(
    r"\b(senior|sr\.|lead|principal|head.?of|director|manager|vp\b|chief|executive|staff.?engineer|"
    r"labour.?law|arbeitsrecht|arbeitnehmerrecht|jurist|jura\b|rechtswissen|"
    r"compliance.{0,15}(jur|legal|recht)|steuerberater|buchhaltu|finanzbuchhaltu|"
    r"lohnbuchhaltu|controlling(?!.{0,20}(data|analytics|software))|"
    r"vertrieb(?!.{0,20}(data|digital|tech|software))|"
    r"marketing(?!.{0,20}(data|digital|analytics|tech|software|ai))|"
    r"personalwesen|human.?resources?\b|hr.?generalist|"
    r"einkauf(?!.{0,20}(data|software|tech))|"
    r"logistik(?!.{0,20}(software|data|it|tech)))\b",
    re.I,
)

# Sadece Werkstudent, Working Student, Trainee veya Intern ilanları kabul edilir!
STUDENT_OR_TRAINEE_SIGNAL = re.compile(
    r"\b(werkstudent|working.?student|trainee|intern|internship|praktik|praktikant|graduate|junior|"
    r"new.?grad|entry.?level|early.?career|berufseinsteiger\w*|absolvent\w*)\b",
    re.I,
)

# Başlıkta en az bir teknik sinyal ŞART — yoksa ilan elenir
TECHNICAL_SIGNAL = re.compile(
    r"\b(machine.?learning|data.?sci|data.?eng|data.?anal|computer.?vision|"
    r"deep.?learning|neural.?net|nlp|llm|"
    r"software|developer|entwickl|programmer|coding|"
    r"python|java\b|c\+\+|javascript|typescript|sql|"
    r"embedded|firmware|fpga|microcontroller|hardware.?eng|"
    r"iot|cloud|devops|mlops|backend|frontend|fullstack|"
    r"ai\b|artificial.?intel|data\b|"
    r"automotive|adas|autonomous.?driv|"
    r"it.{0,10}(system|infra|support|sicherheit)|"
    r"cybersecurity|netzwerk|network.?eng)\b",
    re.I,
)

# StepStone: şehir isimleri
STEPSTONE_CITIES = ["München", "Nürnberg", "Erlangen", "Regensburg", "Ingolstadt", "Forchheim"]

STEPSTONE_KEYWORDS = [
    "working student machine learning",
    "working student data science",
    "working student ai",
    "working student software developer",
    "working student data analytics",
    "working student computer vision",
    "working student python",
    "working student embedded",
    "working student data engineer",
    "working student robotics",
    "working student genai",
    "working student english",
    # Yeni mezun / junior
    "junior data scientist",
    "junior machine learning engineer",
    "junior data analyst",
    "graduate ai engineer",
    "entry level software engineer",
]

# Arbeitnow API: (anahtar kelime, şehir) çiftleri
ARBEITNOW_PAIRS = [
    ("working student machine learning",    "München"),
    ("working student data science",        "München"),
    ("working student data science",        "Erlangen"),
    ("working student ai",                  "München"),
    ("working student ai",                  "Nürnberg"),
    ("working student software",            "München"),
    ("working student data analytics",      "München"),
    ("working student python",              "Erlangen"),
    ("working student computer vision",     "München"),
    ("working student robotics",            "München"),
    ("working student data engineer",       "München"),
    ("working student embedded",            "Erlangen"),
]

# Xing: (anahtar kelime, şehir) çiftleri
XING_PAIRS = [
    ("Working student machine learning",    "München"),
    ("Working student data science",        "München"),
    ("Working student data science",        "Erlangen"),
    ("Working student ai",                  "München"),
    ("Working student software",            "München"),
    ("Working student data analytics",      "München"),
    ("Working student embedded python",     "München"),
    ("Working student software developer",  "München"),
    ("Working student software developer",  "Nürnberg"),
    ("Working student robotics",            "München"),
    # Yeni mezun / junior
    ("Junior data scientist",               "München"),
    ("Junior machine learning engineer",    "München"),
    ("Junior data analyst",                 "München"),
    ("Junior data scientist",               "Nürnberg"),
    ("Graduate AI engineer",                "München"),
    ("Junior software engineer english",    "München"),
]


def fetch(url: str, timeout: int = 10, retries: int = 2) -> BeautifulSoup | None:
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=timeout)
            print(f"  HTTP {r.status_code}  {url[:80]}", flush=True)
            if r.status_code == 200:
                # Bayttan çözümle: charset başlığı eksikse "für" → "fÃ¼r" bozulması olmasın
                return BeautifulSoup(r.content, "html.parser")
        except Exception as e:
            if attempt == retries - 1:
                print(f"  FETCH ERROR: {e}  {url[:80]}", flush=True)
            else:
                time.sleep(2)
    return None



def scrape_stepstone() -> list[dict]:
    results = []
    seen_jk: set[str] = set()

    for kw in STEPSTONE_KEYWORDS:
        for city_name in STEPSTONE_CITIES:
            # Yeni URL formatı: ?q=...&where=... — eski /jobs/{kw}/in-{slug}.html 410 döndürüyor
            url = (
                f"https://www.stepstone.de/jobs/"
                f"?q={requests.utils.quote(kw)}"
                f"&where={requests.utils.quote(city_name)}"
                f"&sort=2"
            )
            soup = fetch(url)
            if not soup:
                time.sleep(1)
                continue

            # StepStone job card — birden fazla olası seçici
            cards = (
                soup.select("article[data-at='job-item']")
                or soup.select("article[class*='ResultCard']")
                or soup.select("[data-at='job-item']")
                or soup.select("article")
            )

            for card in cards:
                # Doğrudan /stellenangebote/ linki bul
                a_tag = (
                    card.select_one("a[href*='/stellenangebote/']")
                    or card.select_one("a[href*='stepstone.de/stellenangebote']")
                )
                if not a_tag:
                    continue

                href = a_tag.get("href", "")
                if not href.startswith("http"):
                    href = "https://www.stepstone.de" + href

                # StepStone URL'inden ID'yi çek — dedup için
                jk_match = re.search(r"--(\d+)\.html", href)
                jk = jk_match.group(1) if jk_match else href
                if jk in seen_jk:
                    continue
                seen_jk.add(jk)

                title_el = (
                    card.select_one("[data-at='job-item-title']")
                    or card.select_one("h2")
                    or card.select_one("h3")
                )
                company_el = (
                    card.select_one("[data-at='job-item-company-name']")
                    or card.select_one("[class*='company-name']")
                    or card.select_one("[class*='companyName']")
                )
                title   = title_el.get_text(strip=True) if title_el else a_tag.get_text(strip=True)
                company = company_el.get_text(strip=True) if company_el else ""

                if not title:
                    continue

                results.append({
                    "title":   title,
                    "company": company,
                    "url":     href,
                    "lang":    "EN" if ENGLISH_SIGNALS.search(title) else "DE",
                    "city":    city_name,
                })

            time.sleep(0.6)

    return results


def fetch_arbeitnow(query: str, city: str) -> list[dict]:
    """Arbeitnow ücretsiz API'sinden ilanları çeker."""
    url = (
        "https://www.arbeitnow.com/api/job-board-api"
        f"?search={requests.utils.quote(query)}"
        f"&location={requests.utils.quote(city)}"
        "&page=1"
    )
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        print(f"  Arbeitnow HTTP {r.status_code}  {query[:40]} @ {city}", flush=True)
        if r.status_code != 200:
            return []
        data = r.json()
    except Exception as e:
        print(f"  Arbeitnow ERROR: {e}", flush=True)
        return []

    items = data.get("data", [])
    print(f"  Arbeitnow items: {len(items)} for '{query}' in {city}", flush=True)

    results = []
    for item in items:
        title   = (item.get("title") or "").strip()
        company = (item.get("company_name") or "").strip()
        link    = (item.get("url") or "").strip()
        location = (item.get("location") or city).strip()

        if not title or not link:
            continue

        # Sadece werkstudent ilanlarını al
        if not re.search(r"werkstudent|working.?student", title, re.I):
            continue

        results.append({
            "title":   title,
            "company": company,
            "url":     link,
            "lang":    "EN" if ENGLISH_SIGNALS.search(title + " " + company) else "DE",
            "city":    location,
        })

    return results


def scrape_arbeitnow() -> list[dict]:
    results = []
    seen_urls: set[str] = set()

    for query, city in ARBEITNOW_PAIRS:
        for job in fetch_arbeitnow(query, city):
            if job["url"] not in seen_urls:
                seen_urls.add(job["url"])
                results.append(job)
        time.sleep(0.5)

    return results


def scrape_xing() -> list[dict]:
    results = []
    seen_ids: set[str] = set()
    job_href_re = re.compile(r"^/jobs/[a-z][a-z0-9\-]+-(\d+)$")

    for query, city in XING_PAIRS:
        url = (
            "https://www.xing.com/jobs/search"
            f"?keywords={requests.utils.quote(query)}"
            f"&location={requests.utils.quote(city)}"
        )
        try:
            r = requests.get(url, headers=HEADERS, timeout=12, allow_redirects=True)
            print(f"  Xing HTTP {r.status_code}  {query[:35]} @ {city}", flush=True)
            if r.status_code != 200:
                time.sleep(1)
                continue
            soup = BeautifulSoup(r.content, "html.parser")
        except Exception as e:
            print(f"  Xing ERROR: {e}", flush=True)
            time.sleep(1)
            continue

        job_anchors = soup.find_all("a", href=job_href_re)
        print(f"  Xing links: {len(job_anchors)} for '{query}' @ {city}", flush=True)

        for a in job_anchors:
            href = a.get("href", "")
            m = job_href_re.match(href)
            if not m:
                continue
            job_id = m.group(1)
            if job_id in seen_ids:
                continue
            seen_ids.add(job_id)

            # Kart metnini üst elementten al: "Başlık|Şirket|Şehir|..."
            parts = []
            parent = a.parent
            for _ in range(6):
                if parent is None:
                    break
                text = parent.get_text(separator="|", strip=True)
                segments = [s.strip() for s in text.split("|") if s.strip()]
                # En az 2 segment ve ilki gerçek bir başlık gibi görünüyorsa dur
                if len(segments) >= 2 and len(segments[0]) > 8 and not segments[0].isdigit():
                    parts = segments
                    break
                parent = parent.parent

            if not parts:
                # Slug'dan başlık çıkar: /jobs/muenchen-werkstudent-ml-engineer-123
                slug = href.rsplit("-", 1)[0].split("/jobs/", 1)[-1]
                title = slug.replace("-", " ").title()
                company = ""
            else:
                title   = parts[0]
                company = parts[1] if len(parts) > 1 else ""

            full_url = f"https://www.xing.com{href}"
            results.append({
                "title":   title,
                "company": company,
                "url":     full_url,
                "lang":    "EN" if ENGLISH_SIGNALS.search(title + " " + company) else "DE",
                "city":    city,
            })

        time.sleep(0.8)

    return results


def is_relevant(job: dict) -> bool:
    """Kara liste, kıdemli (Senior/Lead) pozisyonlar veya öğrenci/trainee olmayan ilanları eler."""
    title = job.get("title", "")
    if EXCLUDED_FIELDS.search(title):
        return False
    if not STUDENT_OR_TRAINEE_SIGNAL.search(title):
        return False
    if not TECHNICAL_SIGNAL.search(title):
        return False
    return True


SECTION_LIMIT = 25      # bir bölümde mail başına en fazla ilan (kalanı ertesi güne kalır)
GERMAN_LIMIT = 5        # Almanca ilanlardan mail başına en fazla kaç tane

SECTIONS = [
    ("en",     "🇩🇪 Almanya – İngilizce ilanlar",            "Bavyera bölgesindeki İngilizce başlıklı Working Student / staj ilanları."),
    ("remote", "🌍 Remote – dünya geneli (part-time / staj)", "Almanya'dan yapılabilecek uzaktan part-time ve staj ilanları."),
    ("grad",   "🎓 Yeni mezun / junior (Almanya + remote)",  "İngilizce başlıklı, veri / AI / Python alanındaki giriş seviyesi ilanlar. Mezuniyet tarihine göre değerlendir."),
    ("swiss",  "🇨🇭 İsviçre",                                 "İsviçre'de durumuna az da olsa uyan her ilan. Dil sütununa dikkat et."),
    ("de",     "🇩🇪 Almanca ilanlar – yalnızca alanına çok uygun olanlar", "Başlığı Almanca ama doğrudan AI / ML / veri alanında olan ilanlar."),
]


def _dedupe(jobs: list[dict]) -> list[dict]:
    """Aynı URL'yi ve aynı başlık+şirket çiftini tekrar etme."""
    seen_keys: set = set()
    out = []
    for j in jobs:
        keys = {j["url"], (j["title"].lower(), j.get("company", "").lower())}
        if keys & seen_keys:
            continue
        seen_keys |= keys
        out.append(j)
    return out


def search_jobs() -> dict[str, list[dict]]:
    """Tüm kaynakları tarar ve ilanları mail bölümlerine ayırır."""
    from extra_sources import (GRAD_NOTE, detect_lang, is_core_field, is_data_ai_python,
                               is_grad_title, remote_jobs, swiss_jobs)

    # 1) Almanya (Bavyera) — StepStone, Arbeitnow, Xing
    local = [j for j in _dedupe(scrape_stepstone() + scrape_arbeitnow() + scrape_xing()) if is_relevant(j)]
    for j in local:
        j["lang"] = detect_lang(j["title"])
        j.setdefault("source", "")
        j.setdefault("note", GRAD_NOTE if is_grad_title(j["title"]) else "")

    # 2) Remote — dünya geneli
    remote = _dedupe(remote_jobs())

    # 3) İsviçre
    swiss = _dedupe(swiss_jobs())

    is_grad = lambda j: j.get("note") == GRAD_NOTE
    english = [j for j in local if j["lang"] == "EN" and not is_grad(j)]
    # Yeni mezun bölümü yalnızca veri / AI / Python başlıklarını gösterir
    grad = [j for j in local + remote
            if j["lang"] == "EN" and is_grad(j) and is_data_ai_python(j["title"])]
    # Almanca başlıklı ilanlar: yalnızca çekirdek alandaysa (AI/ML/veri)
    german = [j for j in local + remote if j["lang"] == "DE" and is_core_field(j["title"])]
    remote = [j for j in remote if j["lang"] != "DE" and not is_grad(j)]
    # İsviçre: önce İngilizce, sonra Almanca/Fransızca; çekirdek alan üstte
    swiss.sort(key=lambda j: (j["lang"] != "EN", not is_core_field(j["title"])))
    for group in (english, remote, grad, german):
        group.sort(key=lambda j: not is_core_field(j["title"]))

    return {"en": english, "remote": remote, "grad": _dedupe(grad), "swiss": swiss, "de": _dedupe(german)}


def _esc(text: str) -> str:
    return str(text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


LANG_STYLE = {
    "EN": ("#e6f4ea", "#137333"),
    "DE": ("#feefc3", "#b06000"),
    "FR": ("#fde7e9", "#b3261e"),
}


def build_html(sections: dict[str, list[dict]], date_str: str, leftover: int = 0) -> str:
    total = sum(len(v) for v in sections.values())
    blocks = ""
    for key, heading, hint in SECTIONS:
        jobs = sections.get(key, [])
        if not jobs:
            if key == "swiss":
                blocks += f"<h3 style='margin:28px 0 6px 0'>{heading}</h3><p style='color:#777;font-size:13px'>Bugün İsviçre'de yeni ilan yok.</p>"
            continue
        rows = ""
        for i, j in enumerate(jobs, 1):
            bg, fg = LANG_STYLE.get(j.get("lang", "EN"), LANG_STYLE["EN"])
            detail = " · ".join(_esc(x) for x in (j.get("note"), j.get("source")) if x)
            rows += f"""
            <tr style="background:{'#f9f9f9' if i % 2 == 0 else 'white'}">
              <td style="text-align:center;color:#888">{i}</td>
              <td><b>{_esc(j['title'])}</b><br><span style="color:#555;font-size:13px">{_esc(j.get('company'))}</span>
                  {f'<br><span style="color:#777;font-size:12px">{detail}</span>' if detail else ''}</td>
              <td style="text-align:center;color:#555;font-size:13px">{_esc(j.get('city'))}</td>
              <td style="text-align:center"><span style="background:{bg};color:{fg};padding:2px 8px;border-radius:3px;font-size:12px;font-weight:bold">{_esc(j.get('lang'))}</span></td>
              <td style="text-align:center"><a href="{_esc(j['url'])}" style="background:#1a73e8;color:white;padding:5px 12px;border-radius:4px;text-decoration:none">İlana git</a></td>
            </tr>"""
        blocks += f"""
  <h3 style="margin:28px 0 4px 0">{heading} <span style="color:#888;font-weight:normal">({len(jobs)})</span></h3>
  <p style="color:#777;font-size:13px;margin:0 0 8px 0">{hint}</p>
  <table border="1" cellpadding="9" cellspacing="0" style="border-collapse:collapse;width:100%;border-color:#e0e0e0">
    <thead><tr style="background:#f1f3f4;color:#333">
      <th width="4%">#</th><th>Pozisyon</th><th width="18%">Yer</th><th width="6%">Dil</th><th width="11%">Link</th>
    </tr></thead>
    <tbody>{rows}</tbody>
  </table>"""

    summary = " · ".join(f"{heading.split(' – ')[0].split(' (')[0]}: <b>{len(sections.get(key, []))}</b>"
                         for key, heading, _ in SECTIONS)
    more = (f"<br><span style='color:#777;font-size:12px'>{leftover} ilan daha sırada; yarınki mailde gelecek.</span>"
            if leftover else "")

    return f"""
<html><body style="font-family:Arial,sans-serif;max-width:950px;margin:auto;padding:20px;color:#333">
  <div style="background:#1a73e8;color:white;padding:20px;border-radius:8px;margin-bottom:20px">
    <h2 style="margin:0">🎯 İlan Raporu — {date_str}</h2>
    <p style="margin:5px 0 0 0;opacity:0.9">Almanya (İngilizce) · Remote · Yeni mezun · İsviçre</p>
  </div>

  <div style="background:#f8f9fa;border-left:4px solid #1a73e8;padding:12px 16px;margin-bottom:8px;border-radius:0 4px 4px 0">
    <b>Bugün {total} yeni ilan.</b> {summary}{more}
  </div>
  {blocks}

  <p style="color:#999;font-size:11px;margin-top:24px">Dil sütunu ilan başlığına (jobs.ch ve SwissDevJobs'ta ilanın dil alanına) göre tahmindir; başvurmadan önce ilanı kontrol et.<br>
  Kaynaklar: StepStone, Xing, Arbeitnow, Remotive, Remote OK, Jobicy, Himalayas, Working Nomads, We Work Remotely, jobs.ch, SwissDevJobs.</p>
</body></html>"""


def wait_for_network(max_retries: int = 60, delay: int = 10) -> bool:
    """Ağ bağlantısı ve DNS tam hazır olana kadar bekler."""
    import socket
    for attempt in range(max_retries):
        try:
            socket.gethostbyname("www.stepstone.de")
            r = requests.head("https://www.google.com", timeout=5)
            if r.status_code in [200, 301, 302, 304]:
                return True
        except Exception:
            pass
        print(f"[{datetime.now().isoformat()}] Ağ ve DNS bekleniyor... ({attempt+1}/{max_retries})", flush=True)
        time.sleep(delay)
    return False


def send_email(html_body: str, subject: str, retries: int = 4) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = GMAIL_USER
    msg["To"] = EMAIL_TO
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    last_err = None
    for attempt in range(retries):
        try:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as server:
                server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
                server.sendmail(GMAIL_USER, EMAIL_TO, msg.as_string())
            return
        except Exception as e:
            last_err = e
            time.sleep(15 * (attempt + 1))
    raise RuntimeError(f"Email gönderilemedi ({retries} deneme): {last_err}")


def main():
    # DRY_RUN=1: mail atmaz, görülenler listesini değiştirmez, HTML'i dosyaya yazar.
    dry_run = os.environ.get("DRY_RUN") == "1"

    print(f"[{datetime.now().isoformat()}] Başlıyor...", flush=True)
    if not dry_run:
        time.sleep(60)  # Mac uyanışından sonra DNS'in hazır olması için bekle

    if not wait_for_network():
        print(f"[{datetime.now().isoformat()}] HATA: Ağ bağlantısı kurulamadı, çıkılıyor.", flush=True)
        return

    print(f"[{datetime.now().isoformat()}] Ağ hazır. Arama başlıyor...", flush=True)
    date_str = datetime.now().strftime("%-d %B %Y")

    seen = load_seen()
    found = search_jobs()

    # Daha önce gönderilmemiş olanları al; bölüm sınırını aşanlar ertesi güne kalır
    # (görüldü olarak işaretlenmez).
    sections: dict[str, list[dict]] = {}
    leftover = 0
    for key, jobs in found.items():
        fresh = [j for j in jobs if j["url"] not in seen]
        limit = GERMAN_LIMIT if key == "de" else SECTION_LIMIT
        sections[key] = fresh[:limit]
        leftover += max(0, len(fresh) - limit)

    count = sum(len(v) for v in sections.values())
    per_section = ", ".join(f"{k}={len(v)}" for k, v in sections.items())
    print(f"[{datetime.now().isoformat()}] {count} yeni ilan ({per_section}; sırada {leftover})", flush=True)

    if count == 0:
        print(f"[{datetime.now().isoformat()}] Yeni ilan yok, email atlanıyor.", flush=True)
        return

    subject = (f"🎯 İlanlar – {date_str} | {len(sections['en'])} Almanya (EN) · "
               f"{len(sections['remote'])} remote · {len(sections['grad'])} yeni mezun · {len(sections['swiss'])} İsviçre")
    html_body = build_html(sections, date_str, leftover)

    if dry_run:
        out = os.environ.get("DRY_RUN_OUT", "job_search_preview.html")
        with open(out, "w", encoding="utf-8") as f:
            f.write(html_body)
        print(f"[DRY RUN] Mail atılmadı. Konu: {subject}\n[DRY RUN] Önizleme: {out}", flush=True)
        return

    send_email(html_body, subject)

    # Yalnızca gerçekten gönderilen ilanları görüldü olarak işaretle
    now = datetime.now().isoformat()
    for jobs in sections.values():
        for j in jobs:
            seen[j["url"]] = now
    save_seen(seen)
    print(f"[{datetime.now().isoformat()}] Gönderildi: {count} yeni ilan — {EMAIL_TO}")


if __name__ == "__main__":
    main()

