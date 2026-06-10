#!/usr/bin/env python3
"""
Werkstudent Application Agent
Reads a job posting (URL or pasted text), reads your profile, and writes a tailored cover letter.
"""

import anthropic
import json
import sys
import os
import csv
import re
from datetime import date
from pathlib import Path

# ── Setup ──────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
PROFILE_PATH = BASE_DIR / "profile.md"
LETTERS_DIR = BASE_DIR / "letters"
CSV_PATH = BASE_DIR / "applications.csv"

LETTERS_DIR.mkdir(exist_ok=True)

client = anthropic.Anthropic()

# ── Tool definitions ───────────────────────────────────────────────────────────
tools = [
    {
        "name": "fetch_url",
        "description": (
            "Fetches the text content of a URL (job posting page). "
            "Returns the visible text or an error message. "
            "If the page is JavaScript-rendered and returns empty/garbled content, "
            "return a message asking the user to paste the JD manually."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The URL to fetch"}
            },
            "required": ["url"],
        },
    },
    {
        "name": "read_profile",
        "description": "Reads the applicant's profile from profile.md. Call this before writing any cover letter.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "save_cover_letter",
        "description": "Saves the finished cover letter to the letters/ folder as a markdown file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "company": {"type": "string", "description": "Company name (used in filename)"},
                "role": {"type": "string", "description": "Role / position title"},
                "language": {
                    "type": "string",
                    "enum": ["de", "en"],
                    "description": "Language of the cover letter: 'de' for German, 'en' for English",
                },
                "content": {"type": "string", "description": "Full cover letter text in markdown"},
            },
            "required": ["company", "role", "language", "content"],
        },
    },
    {
        "name": "log_application",
        "description": "Appends a row to applications.csv to track the application.",
        "input_schema": {
            "type": "object",
            "properties": {
                "company": {"type": "string"},
                "role": {"type": "string"},
                "language": {"type": "string"},
                "match_score": {
                    "type": "string",
                    "description": "Subjective match rating: 'high', 'medium', or 'low'",
                },
                "top_matches": {
                    "type": "string",
                    "description": "Comma-separated list of 2-3 key matching points between JD and profile",
                },
                "letter_path": {"type": "string", "description": "Path to the saved cover letter file"},
                "notes": {"type": "string", "description": "Any extra notes or flags (optional)"},
            },
            "required": ["company", "role", "language", "match_score", "top_matches", "letter_path"],
        },
    },
]

# ── Tool implementations ───────────────────────────────────────────────────────
def fetch_url(url: str) -> str:
    try:
        import requests
        from bs4 import BeautifulSoup

        headers = {"User-Agent": "Mozilla/5.0 (compatible; job-agent/1.0)"}
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()

        text = soup.get_text(separator="\n", strip=True)
        lines = [l for l in text.splitlines() if len(l.strip()) > 20]
        result = "\n".join(lines[:300])  # cap at ~300 meaningful lines

        if len(result.strip()) < 200:
            return (
                "PAGE_EMPTY: The page appears to be JavaScript-rendered and returned no useful text. "
                "Please ask the user to copy-paste the job description text directly."
            )
        return result

    except Exception as e:
        return f"FETCH_ERROR: {e}. Please ask the user to paste the job description manually."


def read_profile() -> str:
    if not PROFILE_PATH.exists():
        return "ERROR: profile.md not found. Please create it at " + str(PROFILE_PATH)
    return PROFILE_PATH.read_text(encoding="utf-8")


def save_cover_letter(company: str, role: str, language: str, content: str) -> str:
    safe_company = re.sub(r"[^\w\s-]", "", company).strip().replace(" ", "_")
    safe_role = re.sub(r"[^\w\s-]", "", role).strip().replace(" ", "_")[:40]
    filename = f"{date.today()}_{safe_company}_{safe_role}_{language}.md"
    path = LETTERS_DIR / filename
    path.write_text(content, encoding="utf-8")
    return str(path)


def log_application(
    company: str,
    role: str,
    language: str,
    match_score: str,
    top_matches: str,
    letter_path: str,
    notes: str = "",
) -> str:
    file_exists = CSV_PATH.exists()
    with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["date", "company", "role", "language", "match_score", "top_matches", "letter_path", "status", "notes"],
        )
        if not file_exists:
            writer.writeheader()
        writer.writerow(
            {
                "date": date.today().isoformat(),
                "company": company,
                "role": role,
                "language": language,
                "match_score": match_score,
                "top_matches": top_matches,
                "letter_path": letter_path,
                "status": "prepared",
                "notes": notes,
            }
        )
    return f"Logged to {CSV_PATH}"


# ── Tool dispatcher ────────────────────────────────────────────────────────────
def run_tool(name: str, inputs: dict) -> str:
    if name == "fetch_url":
        return fetch_url(inputs["url"])
    elif name == "read_profile":
        return read_profile()
    elif name == "save_cover_letter":
        return save_cover_letter(
            inputs["company"], inputs["role"], inputs["language"], inputs["content"]
        )
    elif name == "log_application":
        return log_application(
            inputs["company"],
            inputs["role"],
            inputs["language"],
            inputs["match_score"],
            inputs["top_matches"],
            inputs["letter_path"],
            inputs.get("notes", ""),
        )
    else:
        return f"ERROR: unknown tool '{name}'"


# ── Agent loop ─────────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are a professional Werkstudent job application assistant. Your job is to:

1. Get the job description (either from a URL or text the user provides).
2. Read the applicant's profile from profile.md.
3. Analyze the match between the profile and the job description.
4. Write a tailored, professional cover letter (Anschreiben) in the same language as the job posting
   (German if the JD is in German, English if in English). The letter should:
   - Be 3-4 paragraphs, concise and professional
   - Open with genuine interest in THIS specific company/role
   - Highlight the 2-3 strongest matches from the applicant's profile
   - Close with a clear call to action
   - NOT use generic filler phrases
5. Save the cover letter and log the application.
6. Give the user a short final summary: company, role, file path, top 2-3 match points, match score.

Important: If fetch_url returns PAGE_EMPTY or FETCH_ERROR, tell the user to paste the job description
text and wait — do NOT make up a cover letter without real JD content.
"""


def run_agent(job_input: str):
    print("\n=== Werkstudent Application Agent ===\n")

    messages = [
        {
            "role": "user",
            "content": (
                f"Here is the job posting input (URL or text):\n\n{job_input}\n\n"
                "Please process this job application: fetch/read the JD, read my profile, "
                "write a tailored cover letter, save it, and log the application."
            ),
        }
    ]

    iteration = 0
    max_iterations = 10

    while iteration < max_iterations:
        iteration += 1
        print(f"[turn {iteration}] calling Claude...", flush=True)

        response = client.messages.create(
            model="claude-opus-4-7",
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=tools,
            messages=messages,
        )

        # Append assistant message
        messages.append({"role": "assistant", "content": response.content})

        # Check stop reason
        if response.stop_reason == "end_turn":
            # Extract and print final text
            for block in response.content:
                if hasattr(block, "text"):
                    print("\n=== Agent Summary ===")
                    print(block.text)
            break

        if response.stop_reason != "tool_use":
            print(f"Unexpected stop_reason: {response.stop_reason}")
            break

        # Run all requested tools
        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue

            print(f"  → tool: {block.name}({json.dumps({k: v[:80] + '...' if isinstance(v, str) and len(v) > 80 else v for k, v in block.input.items()})})")
            result = run_tool(block.name, block.input)

            # If the agent needs user input (JS-rendered page), pause and ask
            if "PAGE_EMPTY" in result or "FETCH_ERROR" in result:
                print("\n[!] Could not fetch the page automatically.")
                print("    Please open the job posting in your browser,")
                print("    copy the full job description text, paste it below,")
                print("    and press Ctrl+D (Mac/Linux) or Ctrl+Z then Enter (Windows):\n")
                lines = []
                try:
                    while True:
                        lines.append(input())
                except EOFError:
                    pass
                pasted_text = "\n".join(lines)
                result = pasted_text if pasted_text.strip() else "ERROR: No text provided."

            short_result = result[:200] + "..." if len(result) > 200 else result
            print(f"     result: {short_result}")

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": result,
            })

        messages.append({"role": "user", "content": tool_results})

    else:
        print("Max iterations reached without completing.")


# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if len(sys.argv) > 1:
        job_input = sys.argv[1]
    else:
        print("Paste the job URL or job description text below.")
        print("Press Ctrl+D (Mac/Linux) when done:\n")
        lines = []
        try:
            while True:
                lines.append(input())
        except EOFError:
            pass
        job_input = "\n".join(lines)

    if not job_input.strip():
        print("No input provided. Exiting.")
        sys.exit(1)

    run_agent(job_input)
