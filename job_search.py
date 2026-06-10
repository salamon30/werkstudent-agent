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
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

ENGLISH_SIGNALS = re.compile(
    r"\b(machine learning|data science|computer vision|deep learning|"
    r"embedded systems|working student|software engineer|data engineer|"
    r"python|iot|automotive|adas|edge ai|neural network|artificial intelligence)\b",
    re.I,
)

# Başlıkta bu alanlar varsa ilan kesinlikle elenir (hukuk, finans, satış, HR vs.)
EXCLUDED_FIELDS = re.compile(
    r"\b(labour.?law|arbeitsrecht|arbeitnehmerrecht|jurist|jura\b|rechtswissen|"
    r"compliance.{0,15}(jur|legal|recht)|steuerberater|buchhaltu|finanzbuchhaltu|"
    r"lohnbuchhaltu|controlling(?!.{0,20}(data|analytics|software))|"
    r"vertrieb(?!.{0,20}(data|digital|tech|software))|"
    r"marketing(?!.{0,20}(data|digital|analytics|tech|software|ai))|"
    r"personalwesen|human.?resources?\b|hr.?generalist|"
    r"einkauf(?!.{0,20}(data|software|tech))|"
    r"logistik(?!.{0,20}(software|data|it|tech)))\b",
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

# StepStone: şehir isimleri (yeni URL formatı: ?q=...&where=...)
STEPSTONE_CITIES = ["München", "Nürnberg", "Erlangen", "Regensburg", "Forchheim"]

STEPSTONE_KEYWORDS = [
    "werkstudent machine learning",
    "werkstudent data science",
    "werkstudent embedded python",
    "werkstudent software developer",
    "werkstudent automotive",
    "werkstudent artificial intelligence",
    "werkstudent IoT",
]

# Arbeitnow API: (anahtar kelime, şehir) çiftleri — ücretsiz, bot koruması yok
ARBEITNOW_PAIRS = [
    ("werkstudent machine learning",        "München"),
    ("werkstudent machine learning",        "Nürnberg"),
    ("werkstudent machine learning",        "Erlangen"),
    ("werkstudent data science",            "München"),
    ("werkstudent data science",            "Erlangen"),
    ("werkstudent embedded python",         "München"),
    ("werkstudent embedded python",         "Erlangen"),
    ("werkstudent embedded python",         "Regensburg"),
    ("werkstudent software developer",      "München"),
    ("werkstudent software developer",      "Nürnberg"),
    ("werkstudent automotive",              "München"),
    ("werkstudent automotive",              "Nürnberg"),
    ("werkstudent artificial intelligence", "München"),
    ("werkstudent IoT",                     "München"),
    ("werkstudent IoT",                     "Erlangen"),
    ("werkstudent python",                  "Erlangen"),
    ("werkstudent data",                    "Erlangen"),
]

# Xing: (anahtar kelime, şehir) çiftleri
XING_PAIRS = [
    ("Werkstudent machine learning",        "München"),
    ("Werkstudent machine learning",        "Nürnberg"),
    ("Werkstudent machine learning",        "Erlangen"),
    ("Werkstudent data science",            "München"),
    ("Werkstudent data science",            "Erlangen"),
    ("Werkstudent embedded python",         "München"),
    ("Werkstudent software developer",      "München"),
    ("Werkstudent software developer",      "Nürnberg"),
    ("Werkstudent automotive",              "München"),
    ("Werkstudent automotive",              "Nürnberg"),
    ("Werkstudent artificial intelligence", "München"),
    ("Werkstudent IoT",                     "Erlangen"),
]


def fetch(url: str, timeout: int = 10) -> BeautifulSoup | None:
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        print(f"  HTTP {r.status_code}  {url[:80]}", flush=True)
        if r.status_code == 200:
            return BeautifulSoup(r.text, "html.parser")
    except Exception as e:
        print(f"  FETCH ERROR: {e}  {url[:80]}", flush=True)
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
            soup = BeautifulSoup(r.text, "html.parser")
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
    """Kara liste veya teknik sinyal eksikliği varsa False döner."""
    title = job.get("title", "")
    if EXCLUDED_FIELDS.search(title):
        return False
    if not TECHNICAL_SIGNAL.search(title):
        return False
    return True


def search_jobs() -> list[dict]:
    all_jobs = scrape_stepstone() + scrape_arbeitnow() + scrape_xing()

    # URL'ye göre deduplicate
    seen_urls: set[str] = set()
    unique: list[dict] = []
    for j in all_jobs:
        if j["url"] not in seen_urls:
            seen_urls.add(j["url"])
            unique.append(j)

    # Alakasız alanları ele
    relevant = [j for j in unique if is_relevant(j)]

    # İngilizce önce, Almanca sonra
    english = [j for j in relevant if j["lang"] == "EN"]
    german  = [j for j in relevant if j["lang"] == "DE"]
    return (english + german)[:25]


def build_html(jobs: list[dict], date_str: str) -> str:
    if not jobs:
        rows = "<tr><td colspan='5' style='text-align:center;padding:20px;color:#666'>Bugün uygun ilan bulunamadı.</td></tr>"
    else:
        rows = ""
        for i, j in enumerate(jobs, 1):
            title   = j["title"].replace("<", "&lt;").replace(">", "&gt;")
            company = j.get("company", "").replace("<", "&lt;").replace(">", "&gt;")
            city    = j.get("city", "").replace("<", "&lt;").replace(">", "&gt;")
            rows += f"""
            <tr style="background:{'#f9f9f9' if i % 2 == 0 else 'white'}">
              <td style="text-align:center;font-weight:bold">{i}</td>
              <td><b>{title}</b><br><span style="color:#555;font-size:13px">{company}</span></td>
              <td style="text-align:center;color:#555">{city}</td>
              <td style="text-align:center"><span style="background:#e8f0fe;color:#1a73e8;padding:2px 8px;border-radius:3px;font-size:12px">{j['lang']}</span></td>
              <td style="text-align:center"><a href="{j['url']}" style="background:#1a73e8;color:white;padding:5px 12px;border-radius:4px;text-decoration:none">🔗 Başvur</a></td>
            </tr>"""

    count = len(jobs)
    return f"""
<html><body style="font-family:Arial,sans-serif;max-width:900px;margin:auto;padding:20px">
  <h2 style="color:#1a73e8">🎯 Werkstudent İlanları — {date_str}</h2>
  <p>Arama bölgesi: <b>München · Nürnberg · Regensburg · Erlangen</b></p>
  <table border="1" cellpadding="10" cellspacing="0"
         style="border-collapse:collapse;width:100%;border-color:#e0e0e0">
    <thead>
      <tr style="background:#1a73e8;color:white">
        <th width="4%">#</th>
        <th>Pozisyon</th>
        <th width="12%">Şehir</th>
        <th width="6%">Dil</th>
        <th width="10%">Link</th>
      </tr>
    </thead>
    <tbody>{rows}</tbody>
  </table>
  <p style="margin-top:16px"><b>Toplam {count} ilan bulundu.</b></p>
  <p style="color:#999;font-size:11px">Bu özet otomatik olarak oluşturulmuştur — {date_str}</p>
</body></html>"""


def wait_for_network(max_wait: int = 1800) -> bool:
    """Ağ bağlantısı hazır olana kadar bekler (max_wait saniye)."""
    deadline = time.time() + max_wait
    while time.time() < deadline:
        try:
            requests.head("https://www.google.com", timeout=5)
            return True
        except Exception:
            print(f"[{datetime.now().isoformat()}] Ağ bekleniyor...", flush=True)
            time.sleep(20)
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
    print(f"[{datetime.now().isoformat()}] Başlıyor...", flush=True)
    time.sleep(60)  # Mac uyanışından sonra DNS'in hazır olması için bekle

    if not wait_for_network():
        print(f"[{datetime.now().isoformat()}] HATA: Ağ bağlantısı kurulamadı, çıkılıyor.", flush=True)
        return

    print(f"[{datetime.now().isoformat()}] Ağ hazır. Arama başlıyor...", flush=True)
    date_str = datetime.now().strftime("%-d %B %Y")

    seen = load_seen()
    all_jobs = search_jobs()

    # Daha önce gönderilmemiş olanları filtrele
    new_jobs = [j for j in all_jobs if j["url"] not in seen]

    # Yeni ilanları seen'e ekle
    now = datetime.now().isoformat()
    for j in new_jobs:
        seen[j["url"]] = now
    save_seen(seen)

    count = len(new_jobs)
    print(f"[{datetime.now().isoformat()}] {count} yeni ilan (toplam {len(all_jobs)} bulundu)", flush=True)

    if count == 0:
        print(f"[{datetime.now().isoformat()}] Yeni ilan yok, email atlanıyor.", flush=True)
        return

    subject = f"🎯 Werkstudent İlanları – {date_str} | {count} yeni ilan"
    html_body = build_html(new_jobs, date_str)
    send_email(html_body, subject)
    print(f"[{datetime.now().isoformat()}] Gönderildi: {count} yeni ilan — {EMAIL_TO}")


if __name__ == "__main__":
    main()
