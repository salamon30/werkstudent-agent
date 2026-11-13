"""
Ek ilan kaynakları: dünya geneli remote ilanlar ve İsviçre.

Hepsi ücretsiz, hesap/anahtar gerektirmeyen açık API veya RSS akışlarıdır.
Her fonksiyon şu alanlara sahip sözlüklerin listesini döndürür:
  title, company, url, city, lang, source, note
Bir kaynak hata verirse boş liste döner; diğer kaynaklar çalışmaya devam eder.
"""

import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/126.0.0.0 Safari/537.36",
    "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
}

MAX_AGE_DAYS = 30

# Öğrenci / stajyer / yarı zamanlı sinyali (başlıkta)
STUDENT_TITLE = re.compile(
    r"\b(intern|interns|internship|working.?student|werkstudent(in)?|trainee|"
    r"praktik\w*|stagiaire|stage\b|student|part.?time|teilzeit|apprentice)\b",
    re.I,
)
JUNIOR_TITLE = re.compile(
    r"\b(junior|jr\.?|graduate|new.?grad|entry.?level|early.?career|associate|"
    r"berufseinsteiger\w*|absolvent\w*|trainee)\b",
    re.I,
)
GRAD_NOTE = "Yeni mezun"


def is_grad_title(title: str) -> bool:
    """Öğrenci ilanı değil, yeni mezun / junior ilanı mı?"""
    student = re.search(r"working.?student|werkstudent|intern(ship)?\b|praktik|stagiaire", title, re.I)
    return not student and bool(JUNIOR_TITLE.search(title))

# Kıdemli roller ve alakasız alanlar
EXCLUDED_TITLE = re.compile(
    r"\b(senior|sr\.?|lead|principal|head.?of|director|manager|vp|chief|staff|"
    r"internal|international|"            # "intern" ile karışan kelimeler
    r"data.?entry|sales|account.?exec|recruit\w*|customer.?(service|support|success)|"
    r"nurse|teacher|tutor|legal|paralegal|accountant|bookkeep\w*)\b",
    re.I,
)

TECH_TITLE = re.compile(
    r"\b(machine.?learning|ml\b|data.?sci\w*|data.?eng\w*|data.?anal\w*|analytics|"
    r"computer.?vision|deep.?learning|nlp|llm|genai|ai\b|ki\b|artificial.?intel\w*|"
    r"software|developer|entwickl\w*|engineer\w*|programm\w*|"
    r"python|java\b|c\+\+|javascript|typescript|sql|"
    r"embedded|firmware|iot|cloud|devops|mlops|backend|frontend|full.?stack|"
    r"data\b|robot\w*|sensor\w*|automation|qa\b|test\w*|"
    r"it\b|informatik\w*|research|bi\b|business.?intelligence|reporting)\b",
    re.I,
)

# Remote ilanın Almanya'dan yapılabileceğini gösteren bölge ifadeleri
REGION_OK = re.compile(
    r"world|anywhere|global|europe|emea|\beu\b|germany|deutschland|dach|"
    r"switzerland|schweiz|international",
    re.I,
)


GERMAN_TITLE = re.compile(
    r"werkstudent|praktik|pflichtpraktikum|abschlussarbeit|masterarbeit|bachelorarbeit|"
    r"m/w/d|w/m/d|m/w/x|mwd\b|entwickl|softwareentwicklung|informatik|"
    r"\b(im|für|und|mit|oder|als|bereich|schwerpunkt|unterstützung|mitarbeiter\w*|"
    r"studentische\w*|aushilfe|ausbildung|künstliche|ki)\b|:in\b|/in\b|[äöüß]",
    re.I,
)
FRENCH_TITLE = re.compile(
    r"stagiaire|\bstage\b|ingénieur|développeu|\b(en|de|des|et|pour|à)\b.*\b(données|projet|analyse)|[éèêàç]",
    re.I,
)

# Almanca ilan "çok önemli" sayılır mı: yalnızca profilin çekirdek alanları
CORE_FIELD = re.compile(
    r"machine.?learning|maschinelles.?lernen|deep.?learning|computer.?vision|bildverarbeitung|"
    r"data.?scien|\bai\b|\bki\b|künstliche.?intelligenz|artificial.?intel|"
    r"\bllm|genai|generative|\bnlp\b|mlops|edge.?ai|robot|sensor|digital.?twin|"
    r"data.?engineer|data.?analy",
    re.I,
)


def detect_lang(title: str) -> str:
    """İlan başlığının dili: EN, DE veya FR (başlığa bakarak kaba tahmin)."""
    if GERMAN_TITLE.search(title):
        return "DE"
    if FRENCH_TITLE.search(title):
        return "FR"
    return "EN"


def is_core_field(title: str) -> bool:
    return bool(CORE_FIELD.search(title))


# Yeni mezun bölümü için: yalnızca veri / AI / Python başlıkları
DATA_AI_PYTHON = re.compile(r"\bpython\b|\bdata\b|\bdaten\b|analytics|\bml\b|business.?intelligence|\bbi\b", re.I)


def is_data_ai_python(title: str) -> bool:
    return is_core_field(title) or bool(DATA_AI_PYTHON.search(title))


def _get(url: str, name: str, timeout: int = 20):
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        print(f"  {name} HTTP {r.status_code}", flush=True)
        if r.status_code == 200:
            return r
    except Exception as e:
        print(f"  {name} ERROR: {e}", flush=True)
    return None


def _json(url: str, name: str):
    r = _get(url, name)
    if r is None:
        return None
    try:
        return r.json()
    except Exception as e:
        print(f"  {name} JSON ERROR: {e}", flush=True)
        return None


def _fresh(value) -> bool:
    """Tarih okunabiliyorsa son MAX_AGE_DAYS gün içinde mi? Okunamıyorsa True."""
    if value in (None, ""):
        return True
    try:
        if isinstance(value, (int, float)) or str(value).isdigit():
            dt = datetime.fromtimestamp(int(value), tz=timezone.utc)
        else:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
    except Exception:
        return True
    return dt > datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)


def _region_ok(region: str) -> bool:
    """Bölge boşsa veya Avrupa/dünya geneli ise kabul et."""
    region = (region or "").strip()
    return not region or bool(REGION_OK.search(region))


def _student_fit(title: str, job_type: str = "") -> str | None:
    """İlan öğrenciye uygunsa kısa bir etiket, değilse None döndürür."""
    if EXCLUDED_TITLE.search(title) or not TECH_TITLE.search(title):
        return None
    kind = f"{title} {job_type}".lower()
    if re.search(r"working.?student|werkstudent", kind):
        return "Working Student"
    if re.search(r"intern|praktik|stagiaire", kind):
        return "Staj"
    if re.search(r"part.?time|teilzeit", kind):
        return "Part-time"
    if is_grad_title(title):
        return GRAD_NOTE
    if STUDENT_TITLE.search(title):
        return "Öğrenci"
    return None


def _region_label(region: str) -> str:
    parts = [p.strip() for p in (region or "").split(",") if p.strip()]
    if len(parts) > 4:
        return f"{len(parts)} ülke (Almanya dahil)" if "Germany" in parts else f"{len(parts)} ülke"
    return region or "Worldwide"


def _job(title, company, url, city, source, note, lang=None):
    lang = lang or detect_lang(str(title))
    return {
        "title": " ".join(str(title).split()),
        "company": " ".join(str(company or "").split()),
        "url": str(url).strip(),
        "city": _region_label(" ".join(str(city or "").split()))[:60],
        "lang": lang,
        "source": source,
        "note": note,
    }


# ── Remote kaynakları ──────────────────────────────────────────────────────

def remotive() -> list[dict]:
    out = []
    for q in ("intern", "internship", "part-time", "working student", "junior", "graduate", "entry level"):
        data = _json(f"https://remotive.com/api/remote-jobs?search={requests.utils.quote(q)}", f"Remotive '{q}'")
        for it in (data or {}).get("jobs", []):
            fit = _student_fit(it.get("title", ""), it.get("job_type", ""))
            region = it.get("candidate_required_location", "")
            if fit and _region_ok(region) and _fresh(it.get("publication_date")):
                out.append(_job(it["title"], it.get("company_name"), it["url"], region or "Worldwide", "Remotive", fit))
        time.sleep(0.5)
    return out


def remoteok() -> list[dict]:
    data = _json("https://remoteok.com/api", "RemoteOK")
    out = []
    for it in (data or [])[1:]:
        title = it.get("position") or ""
        tags = " ".join(it.get("tags") or [])
        fit = _student_fit(title, tags if re.search(r"part.?time|intern", tags, re.I) else "")
        region = it.get("location", "")
        if fit and _region_ok(region) and _fresh(it.get("epoch")):
            out.append(_job(title, it.get("company"), it.get("url", ""), region or "Worldwide", "RemoteOK", fit))
    return out


def jobicy() -> list[dict]:
    data = _json("https://jobicy.com/api/v2/remote-jobs?count=100", "Jobicy")
    out = []
    for it in (data or {}).get("jobs", []):
        title = it.get("jobTitle") or ""
        jtype = it.get("jobType")
        jtype = " ".join(jtype) if isinstance(jtype, list) else str(jtype or "")
        fit = _student_fit(title, jtype)
        region = it.get("jobGeo", "")
        if fit and _region_ok(region) and _fresh(it.get("pubDate")):
            out.append(_job(title, it.get("companyName"), it["url"], region or "Worldwide", "Jobicy", fit))
    return out


def himalayas() -> list[dict]:
    out = []
    for etype in ("Intern", "Part Time", "Full Time"):
        for q in ("data", "software", "ai", "python"):
            url = ("https://himalayas.app/jobs/api/search"
                   f"?q={q}&employment_type={requests.utils.quote(etype)}")
            if etype == "Full Time":   # yeni mezun: yalnızca giriş seviyesi
                url = f"https://himalayas.app/jobs/api/search?q={q}&seniority=Entry-level"
            data = _json(url, f"Himalayas {etype}/{q}")
            for it in (data or {}).get("jobs", []):
                title = it.get("title") or ""
                fit = _student_fit(title, it.get("employmentType", ""))
                region = ", ".join(it.get("locationRestrictions") or [])
                link = it.get("guid") or it.get("applicationLink") or ""
                if fit and link and _region_ok(region) and _fresh(it.get("pubDate")):
                    out.append(_job(title, it.get("companyName"), link, region or "Worldwide", "Himalayas", fit))
            time.sleep(0.5)
    return out


def workingnomads() -> list[dict]:
    data = _json("https://www.workingnomads.com/api/exposed_jobs/", "WorkingNomads")
    out = []
    for it in data or []:
        title = it.get("title") or ""
        fit = _student_fit(title)
        region = it.get("location", "")
        if fit and _region_ok(region) and _fresh(it.get("pub_date")):
            out.append(_job(title, it.get("company_name"), it["url"], region or "Worldwide", "Working Nomads", fit))
    return out


def weworkremotely() -> list[dict]:
    r = _get("https://weworkremotely.com/remote-jobs.rss", "WeWorkRemotely")
    out = []
    if r is None:
        return out
    try:
        root = ET.fromstring(r.content)
    except Exception as e:
        print(f"  WeWorkRemotely XML ERROR: {e}", flush=True)
        return out
    for item in root.iter("item"):
        raw = item.findtext("title") or ""
        company, _, title = raw.partition(": ")
        if not title:
            title, company = raw, ""
        fit = _student_fit(title, item.findtext("type") or "")
        region = item.findtext("region") or ""
        link = item.findtext("link") or ""
        if fit and link and _region_ok(region):
            out.append(_job(title, company, link, region or "Worldwide", "We Work Remotely", fit))
    return out


def arbeitnow_remote() -> list[dict]:
    """Arbeitnow (Almanya ağırlıklı) akışındaki remote öğrenci ilanları."""
    out = []
    for page in (1, 2, 3):
        data = _json(f"https://www.arbeitnow.com/api/job-board-api?page={page}", f"Arbeitnow remote p{page}")
        for it in (data or {}).get("data", []):
            if not it.get("remote"):
                continue
            title = it.get("title") or ""
            fit = _student_fit(title, " ".join(it.get("job_types") or []))
            if fit and _fresh(it.get("created_at")):
                out.append(_job(title, it.get("company_name"), it["url"],
                                f"Remote · {it.get('location', '')}", "Arbeitnow", fit))
        time.sleep(0.5)
    return out


def remote_jobs() -> list[dict]:
    jobs = []
    for fn in (remotive, remoteok, jobicy, himalayas, workingnomads, weworkremotely, arbeitnow_remote):
        try:
            found = fn()
        except Exception as e:  # bir kaynak bozulursa diğerleri sürsün
            print(f"  {fn.__name__} FAILED: {e}", flush=True)
            found = []
        print(f"  → {fn.__name__}: {len(found)} uygun ilan", flush=True)
        jobs += found
    return jobs


# ── İsviçre ────────────────────────────────────────────────────────────────

JOBSCH_QUERIES = [
    "intern data", "intern software", "intern machine learning", "intern AI",
    "internship engineering", "internship python", "working student",
    "werkstudent", "praktikum informatik", "praktikum data", "trainee IT",
    "junior data scientist", "junior machine learning", "student assistant",
    "junior data analyst", "junior software engineer", "graduate program", "junior AI engineer",
]

LANG_LEVEL = {1: "temel", 2: "orta", 3: "iyi", 4: "çok iyi", 5: "ana dil"}


def jobs_ch() -> list[dict]:
    out = []
    for q in JOBSCH_QUERIES:
        for page in (1, 2):
            url = ("https://www.jobs.ch/api/v1/public/search"
                   f"?query={requests.utils.quote(q)}&rows=20&page={page}")
            data = _json(url, f"jobs.ch '{q}' p{page}")
            docs = (data or {}).get("documents", [])
            for it in docs:
                title = it.get("title") or ""
                if EXCLUDED_TITLE.search(title) or not TECH_TITLE.search(title):
                    continue
                fit = _student_fit(title)
                if not fit or not _fresh(it.get("publication_date")):
                    continue
                links = it.get("_links") or {}
                link = (links.get("detail_en") or links.get("detail_de") or {}).get("href")
                if not link:
                    continue
                langs = [f"{s.get('language', '').upper()} {LANG_LEVEL.get(s.get('level'), '')}".strip()
                         for s in it.get("language_skills") or []]
                grades = it.get("employment_grades") or []
                pct = f"%{min(grades)}–{max(grades)}" if len(set(grades)) > 1 else (f"%{grades[0]}" if grades else "")
                note = " · ".join(x for x in (fit, pct, ("Dil: " + ", ".join(langs)) if langs else "") if x)
                needs_de = any(s.get("language") == "de" and (s.get("level") or 0) >= 3
                               for s in it.get("language_skills") or [])
                needs_fr = any(s.get("language") == "fr" and (s.get("level") or 0) >= 3
                               for s in it.get("language_skills") or [])
                lang = "DE" if needs_de else "FR" if needs_fr else detect_lang(title)
                out.append(_job(title, it.get("company_name"), link, it.get("place"), "jobs.ch", note, lang=lang))
            if len(docs) < 20:
                break
            time.sleep(0.4)
    return out


def swissdevjobs() -> list[dict]:
    data = _json("https://swissdevjobs.ch/api/jobsLight", "SwissDevJobs")
    out = []
    for it in data or []:
        if it.get("isPaused"):
            continue
        title = it.get("name") or ""
        level = str(it.get("expLevel") or "")
        if EXCLUDED_TITLE.search(title):
            continue
        fit = _student_fit(title)
        if not fit and (level.lower() == "junior" or JUNIOR_TITLE.search(title)):
            fit = GRAD_NOTE
        if not fit or not it.get("jobUrl"):
            continue
        lang = str(it.get("language") or "")
        note = " · ".join(x for x in (fit, it.get("workplace"), f"Dil: {lang}" if lang else "") if x)
        out.append(_job(title, it.get("company"), f"https://swissdevjobs.ch/jobs/{it['jobUrl']}",
                        it.get("actualCity") or it.get("cityCategory"), "SwissDevJobs", note,
                        lang={"german": "DE", "french": "FR"}.get(lang.lower(), detect_lang(title))))
    return out


def swiss_jobs() -> list[dict]:
    jobs = []
    for fn in (jobs_ch, swissdevjobs):
        try:
            found = fn()
        except Exception as e:
            print(f"  {fn.__name__} FAILED: {e}", flush=True)
            found = []
        print(f"  → {fn.__name__}: {len(found)} uygun ilan", flush=True)
        jobs += found
    return jobs


if __name__ == "__main__":
    for label, jobs in (("REMOTE", remote_jobs()), ("İSVİÇRE", swiss_jobs())):
        print(f"\n===== {label}: {len(jobs)} =====")
        for j in jobs:
            print(f"[{j['source']}] {j['title']} — {j['company']} | {j['city']} | {j['note']} | {j['lang']}\n    {j['url']}")
