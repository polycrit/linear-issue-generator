import base64
import io
import json
from typing import Dict, List, Optional, Tuple

import requests
import streamlit as st
from openai import OpenAI
from PIL import Image

st.set_page_config(page_title="Linear Issue Creator", layout="wide")

# --- INITIALIZATION AND CONFIGURATION ---

try:
    OPENAI_API_KEY = st.secrets["OPENAI_API_KEY"]
    LINEAR_API_KEY = st.secrets["LINEAR_API_KEY"]
    DEFAULT_MODEL = st.secrets.get("OPENAI_MODEL", "gpt-4o")
    LINEAR_TEAM_ID_DEFAULT = st.secrets.get("LINEAR_TEAM_ID")
except KeyError as e:
    st.error(f"Missing secret: {e}. Please add it to your Streamlit secrets.")
    st.stop()

openai_client = OpenAI(api_key=OPENAI_API_KEY)

LINEAR_API_URL = "https://api.linear.app/graphql"
SYSTEM_PROMPT = (
    "You extract actionable issues from user input (text + screenshots). "
    "Return STRICT JSON only with this schema:\n"
    '{"issues":[{"title":"<short issue title>","description":"<1-3 bullet point summary>"}]}'
)

if "generated_issues" not in st.session_state:
    st.session_state.generated_issues = []


# --- CORE API & DATA FUNCTIONS ---


def linear_graphql_request(
    query: str, variables: Optional[Dict] = None
) -> Optional[Dict]:
    """Performs a GraphQL request to the Linear API."""
    headers = {"Authorization": LINEAR_API_KEY, "Content-Type": "application/json"}
    try:
        response = requests.post(
            LINEAR_API_URL,
            json={"query": query, "variables": variables or {}},
            headers=headers,
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        if "errors" in data:
            st.error(f"Linear API Error: {data['errors']}")
            return None
        return data.get("data")
    except requests.exceptions.RequestException as e:
        st.error(f"Failed to connect to Linear API: {e}")
        return None
    except json.JSONDecodeError:
        st.error(f"Failed to decode Linear API response: {response.text[:500]}")
        return None


@st.cache_data(ttl=3600)
def fetch_projects() -> Dict[str, str]:
    """Fetches all projects and returns a name-to-id mapping."""
    query = "query { projects(first: 250) { nodes { id name } } }"
    data = linear_graphql_request(query)
    return (
        {p["name"]: p["id"] for p in data["projects"]["nodes"]}
        if data and "projects" in data
        else {}
    )


@st.cache_data(ttl=600)
def fetch_project_details(project_id: str) -> Dict:
    """Fetches teams and milestones for a specific project."""
    query = """
    query($id: String!) {
      project(id: $id) {
        teams(first: 50) { nodes { id name } }
        projectMilestones(first: 100) { nodes { id name } }
      }
    }
    """
    data = linear_graphql_request(query, {"id": project_id})
    if not data or "project" not in data:
        return {"teams": {}, "milestones": {}}
    project = data["project"]
    teams = {t["name"]: t["id"] for t in project.get("teams", {}).get("nodes", [])}
    milestones = {
        m["name"]: m["id"]
        for m in project.get("projectMilestones", {}).get("nodes", [])
    }
    return {"teams": teams, "milestones": milestones}


@st.cache_data(ttl=3600)
def fetch_teams() -> Dict[str, str]:
    """Fetches all teams for the viewer and returns a name-to-id mapping."""
    query = "query { viewer { teams(first: 100) { nodes { id name } } } }"
    data = linear_graphql_request(query)
    return (
        {t["name"]: t["id"] for t in data["viewer"]["teams"]["nodes"]}
        if data and "viewer" in data
        else {}
    )


@st.cache_data(ttl=3600)
def fetch_workflow_states(team_id: str) -> Dict[str, str]:
    """Fetches all workflow states for a team and returns a name-to-id mapping."""
    query = """
    query TeamWorkflowStates($teamId: String!) {
        team(id: $teamId) {
            states(first: 50) {
                nodes { id name }
            }
        }
    }
    """
    data = linear_graphql_request(query, {"teamId": team_id})
    if data and "team" in data:
        return {s["name"]: s["id"] for s in data["team"]["states"]["nodes"]}
    return {}


def create_linear_issue(**kwargs) -> Optional[Dict]:
    """Creates a new issue in Linear with the given properties."""
    mutation = """
    mutation IssueCreate($input: IssueCreateInput!) {
      issueCreate(input: $input) {
        success
        issue { id identifier title project { name } }
      }
    }
    """
    input_payload = {k: v for k, v in kwargs.items() if v is not None}
    if "title" in input_payload:
        input_payload["title"] = input_payload["title"][:255]
    data = linear_graphql_request(mutation, {"input": input_payload})
    return (
        data["issueCreate"]["issue"]
        if data and data.get("issueCreate", {}).get("success")
        else None
    )


def extract_issues_with_gpt(user_text: str, image_data_urls: List[str]) -> List[Dict]:
    """Uses GPT to extract structured issue data from text and images."""
    content = [{"type": "text", "text": user_text or "No text provided."}]
    for url in image_data_urls:
        content.append({"type": "image_url", "image_url": {"url": url}})
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": content},
    ]
    try:
        response = openai_client.chat.completions.create(
            model=DEFAULT_MODEL,
            messages=messages,
            response_format={"type": "json_object"},
        )
        raw_content = response.choices[0].message.content
        data = json.loads(raw_content or "{}")
        issues = data.get("issues", [])
    except (json.JSONDecodeError, Exception) as e:
        st.warning(f"Could not parse AI response as JSON. Error: {e}")
        return []
    return [
        {
            "title": (i.get("title") or "").strip(),
            "description": (i.get("description") or "").strip(),
        }
        for i in issues
        if (i.get("title") or "").strip()
    ]


def image_to_data_url(file) -> str:
    """Converts an uploaded image file to a base64 data URL."""
    img = Image.open(file).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    b64_str = base64.b64encode(buf.getvalue()).decode("utf-8")
    return f"data:image/jpeg;base64,{b64_str}"


# --- UI RENDERING & WORKFLOW FUNCTIONS ---


def render_sidebar() -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Renders the sidebar selectors for project, milestone, and team."""
    st.sidebar.header("Assignment Options")
    projects_map = fetch_projects()
    project_names = ["None"] + sorted(projects_map.keys())
    project_choice = st.sidebar.selectbox("Project", project_names)
    selected_project_id = projects_map.get(project_choice)

    project_teams_map, milestones_map = {}, {}
    if selected_project_id:
        details = fetch_project_details(selected_project_id)
        project_teams_map = details.get("teams", {})
        milestones_map = details.get("milestones", {})

    milestone_names = ["None"] + sorted(milestones_map.keys())
    milestone_choice = st.sidebar.selectbox(
        "Milestone", milestone_names, disabled=not selected_project_id
    )
    selected_milestone_id = milestones_map.get(milestone_choice)

    team_id_to_use = None
    if selected_project_id and len(project_teams_map) == 1:
        team_name = next(iter(project_teams_map.keys()))
        team_id_to_use = project_teams_map[team_name]
        st.sidebar.info(f"Auto-selected team: {team_name}")
    elif selected_project_id and len(project_teams_map) > 1:
        team_choice = st.sidebar.selectbox(
            "Team (from project)", sorted(project_teams_map.keys())
        )
        team_id_to_use = project_teams_map.get(team_choice)
    else:
        if selected_project_id:
            st.sidebar.warning("Project has no teams. Select a team below.")
        all_teams_map = fetch_teams()
        if all_teams_map:
            team_names = sorted(all_teams_map.keys())
            default_index = 0
            if LINEAR_TEAM_ID_DEFAULT:
                try:
                    default_team_name = next(
                        n
                        for n, i in all_teams_map.items()
                        if i == LINEAR_TEAM_ID_DEFAULT
                    )
                    default_index = team_names.index(default_team_name)
                except (StopIteration, ValueError):
                    pass
            team_choice = st.sidebar.selectbox("Team", team_names, index=default_index)
            team_id_to_use = all_teams_map.get(team_choice)

    if not team_id_to_use:
        st.sidebar.error("A team is required to create issues.")
    return selected_project_id, selected_milestone_id, team_id_to_use


def render_editor_and_creator(
    team_id: str,
    project_id: Optional[str],
    milestone_id: Optional[str],
    state_id: Optional[str],
):
    """Renders the editable list of issues and handles the final creation step."""
    st.header("Step 2: Review and Edit Issues")
    st.caption(
        "Edit the generated titles and descriptions, or mark issues for deletion before creating them in Linear."
    )

    with st.form("edit_issues_form"):
        for i, issue in enumerate(st.session_state.generated_issues):
            st.divider()
            col1, col2 = st.columns([10, 1])
            with col1:
                issue["title"] = st.text_input(
                    "Title", value=issue["title"], key=f"title_{i}"
                )
            with col2:
                issue["delete"] = st.checkbox(
                    "Delete", key=f"delete_{i}", help="Mark this issue for deletion"
                )

            issue["description"] = st.text_area(
                "Description", value=issue["description"], key=f"desc_{i}", height=100
            )

        submitted = st.form_submit_button("Create Issues in Linear", type="primary")

        if submitted:
            issues_to_submit = [
                iss
                for iss in st.session_state.generated_issues
                if not iss.get("delete")
            ]
            if not issues_to_submit:
                st.warning("No issues were selected for creation.")
                return

            progress_bar = st.progress(0, "Creating issues...")
            created_count = 0
            for i, issue in enumerate(issues_to_submit):
                created = create_linear_issue(
                    teamId=team_id,
                    title=issue["title"],
                    description=issue.get("description"),
                    projectId=project_id,
                    projectMilestoneId=milestone_id,
                    stateId=state_id,  # Assigns the "Todo" status
                )
                if created:
                    created_count += 1
                    proj = created.get("project", {}).get("name")
                    details = f" (Project: {proj})" if proj else ""
                    st.write(
                        f"Success: {created['identifier']} - {created['title']}{details}"
                    )
                else:
                    st.write(f"Failed to create: {issue['title']}")

                progress_bar.progress((i + 1) / len(issues_to_submit))

            st.success(
                f"Process Complete. Created {created_count} of {len(issues_to_submit)} issues."
            )
            st.session_state.generated_issues = []


# --- MAIN APP WORKFLOW ---


def main():
    st.title("Linear Issue Creator")
    st.caption("Describe tasks or upload screenshots to generate issues for Linear.")

    project_id, milestone_id, team_id = render_sidebar()

    # Fetch the state ID for "Todo" for the selected team
    todo_state_id = None
    if team_id:
        workflow_states = fetch_workflow_states(team_id)
        todo_state_id = workflow_states.get("Todo")
        if not todo_state_id:
            st.sidebar.warning(
                "Could not find 'Todo' state for this team. Issues will be created with the default status."
            )

    st.header("Step 1: Describe the Work")
    user_text = st.text_area(
        "Description",
        height=150,
        placeholder="e.g., The login button is broken on Safari.\nUsers are getting a 500 error when trying to reset their password.",
    )
    uploaded_files = st.file_uploader(
        "Upload Screenshots (Optional)",
        type=["png", "jpg", "jpeg"],
        accept_multiple_files=True,
    )

    if st.button("Generate Issues", type="secondary", disabled=not team_id):
        if not user_text and not uploaded_files:
            st.warning("Please enter a description or upload a file.")
            return

        with st.spinner("Analyzing input..."):
            img_urls = [image_to_data_url(f) for f in uploaded_files or []]
            st.session_state.generated_issues = extract_issues_with_gpt(
                user_text, img_urls
            )

        if not st.session_state.generated_issues:
            st.warning("No actionable issues could be extracted from the input.")

    st.divider()

    if st.session_state.generated_issues and team_id:
        render_editor_and_creator(team_id, project_id, milestone_id, todo_state_id)


if __name__ == "__main__":
    main()
