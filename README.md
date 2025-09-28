# Linear Issue Creator

This is a personal tool I built to speed up creating issues in Linear. It lets the user paste a short description, optionally upload screenshots (emails, bug reports, etc.), and then uses ChatGPT‑5 to extract actionable issues which are created in Linear automatically.

## Features

-   Create Linear issues from **text + screenshots** (multimodal).
-   Pick **Project**, its **Milestone**, and the **Team** to assign.
-   Uses the **Linear GraphQL API**.
-   Shows created issue **identifiers** (e.g., `ENG‑123`).

## Prerequisites

-   Python 3.10+
-   A Linear account + **Linear API key**
-   An OpenAI account + **OpenAI API key** (with access to ChatGPT‑5)

## Quick Start

```bash
pip install -r requirements.txt
streamlit run app.py
```

Create `.streamlit/secrets.toml`:

```toml
OPENAI_API_KEY = "sk-..."
LINEAR_API_KEY = "lin_api_..."
# Optional defaults:
# LINEAR_TEAM_ID = "team_id_here"
# OPENAI_MODEL = "gpt-5"
```

## Usage

1. Choose a **Project** (then optionally a **Milestone**).
2. If no project or the project has multiple teams, pick a **Team**.
3. Enter text and/or upload screenshots.
4. Click **“Generate & Create Issues”**.
5. The app prints created issues with their Linear identifiers.

## Notes

-   Runs locally with Streamlit; your keys live in `.streamlit/secrets.toml`.
-   Images you upload are sent to OpenAI when generating issues.
-   This repository is for **personal use**; no warranty or affiliation with Linear or OpenAI.
