import streamlit as st
import openai
from github import Github
import json
from pathlib import Path
from typing import Dict, List

# Simple Aphex Architect Streamlit app
# Features:
# - Sidebar for OpenAI key, GitHub token, repo name and model selection
# - Chat interface using st.session_state for history
# - Build a JSON blueprint of the admin_tools/ folder
# - Deploy (create/update) a JSON blueprint file to a GitHub repo using PyGithub

st.set_page_config(page_title='Aphex Architect', layout='wide')

# ---- Session state initialization ----
if 'history' not in st.session_state:
    # history is a list of dicts: { 'role': 'user'|'assistant', 'content': '...'}
    st.session_state.history = []

if 'blueprint' not in st.session_state:
    st.session_state.blueprint = None

# ---- Sidebar ----
st.sidebar.title('Aphex Architect - Admin')
openai_key = st.sidebar.text_input('OpenAI API Key', type='password')
github_token = st.sidebar.text_input('GitHub Token', type='password')
repo_name = st.sidebar.text_input('GitHub Repo (owner/repo)')
branch = st.sidebar.text_input('Branch', value='main')
model = st.sidebar.selectbox('Model', ['gpt-5', 'gpt-4o', 'gpt-4', 'gpt-3.5-turbo'])

st.sidebar.markdown('---')
st.sidebar.markdown('Make sure your tokens have the required permissions for repo updates and the OpenAI quota is available.')

# ---- Helper functions ----

def generate_response(api_key: str, model_name: str, messages: List[Dict]) -> str:
    """Call OpenAI ChatCompletion and return assistant content.

    messages should be a list like [{'role': 'user', 'content': '...'}, ...]
    """
    if not api_key:
        raise ValueError('OpenAI API key is missing')
    openai.api_key = api_key
    # Use ChatCompletion API
    resp = openai.ChatCompletion.create(model=model_name, messages=messages)
    # Extract text from response
    content = ''
    if resp and getattr(resp, 'choices', None):
        choice = resp.choices[0]
        # older/newer SDKs may expose message in slightly different way
        msg = getattr(choice, 'message', None)
        if msg and getattr(msg, 'get', None):
            content = msg.get('content', '')
        else:
            # fallback for alternative shapes
            content = choice.text if hasattr(choice, 'text') else ''
    return content or ''


def build_blueprint_from_folder(folder: Path) -> Dict[str, str]:
    """Recursively read files under folder and return a mapping of relative path -> content."""
    blueprint = {}
    if not folder.exists() or not folder.is_dir():
        return blueprint
    for p in sorted(folder.rglob('*')):
        if p.is_file():
            # key should be posix path relative to project root (include folder name)
            rel = p.relative_to(folder.parent).as_posix()
            try:
                text = p.read_text(encoding='utf-8')
            except Exception:
                # binary or unreadable file: skip
                continue
            blueprint[rel] = text
    return blueprint


def deploy_to_github(token: str, repo_full_name: str, blueprint: Dict[str, str],
                     commit_message: str = 'Update admin_tools blueprint', branch_name: str = 'main') -> None:
    """Create or update a single file in the target repo containing the blueprint JSON."""
    if not token:
        raise ValueError('GitHub token is missing')
    if not repo_full_name:
        raise ValueError('Repo name is missing')
    g = Github(token)
    repo = g.get_repo(repo_full_name)
    target_path = 'admin_tools_blueprint.json'
    content_str = json.dumps(blueprint, indent=2, ensure_ascii=False)
    try:
        existing = repo.get_contents(target_path, ref=branch_name)
        repo.update_file(existing.path, commit_message, content_str, existing.sha, branch=branch_name)
    except Exception as e:
        # If file not found or other 404-style error, try to create it
        err_str = str(e)
        if '404' in err_str or 'not found' in err_str.lower():
            repo.create_file(target_path, commit_message, content_str, branch=branch_name)
        else:
            # re-raise for visibility in the UI
            raise

# ---- Layout ----
st.title('Aphex Architect')

left, right = st.columns([3, 1])

with left:
    st.header('Chat')

    # Display chat history
    for msg in st.session_state.history:
        role = msg.get('role', 'user')
        content = msg.get('content', '')
        if role == 'user':
            st.markdown(f"**You:** {content}")
        else:
            st.markdown(f"**Assistant:** {content}")

    # Input area
    user_input = st.text_area('Message', key='user_input', height=120)
    send = st.button('Send')

    if send:
        if not user_input or not user_input.strip():
            st.warning('Please enter a message before sending')
        elif not openai_key:
            st.error('OpenAI API key is required in the sidebar')
        else:
            # append user message
            st.session_state.history.append({'role': 'user', 'content': user_input})
            # prepare messages for API (convert history to chat format)
            messages = [{'role': m['role'], 'content': m['content']} for m in st.session_state.history]
            try:
                with st.spinner('Generating response...'):
                    assistant_text = generate_response(openai_key, model, messages)
                st.session_state.history.append({'role': 'assistant', 'content': assistant_text})
            except Exception as e:
                st.error(f'OpenAI request failed: {e}')

with right:
    st.header('Deployment')

    base_path = Path(__file__).parent
    admin_folder = base_path / 'admin_tools'

    if st.button('Build JSON blueprint from admin_tools/'):
        blueprint = build_blueprint_from_folder(admin_folder)
        if not blueprint:
            st.warning('No files found under admin_tools/. The blueprint will be empty')
        st.session_state.blueprint = blueprint
        st.success(f'Blueprint built with {len(blueprint)} file(s)')

    if st.session_state.blueprint is not None:
        st.markdown('Blueprint preview (first 1k chars of JSON)')
        try:
            preview = json.dumps(st.session_state.blueprint, ensure_ascii=False)
            st.code(preview[:1000])
        except Exception:
            st.write('Unable to preview blueprint')

    st.markdown('---')
    if st.button('Deploy blueprint to GitHub'):
        if not github_token or not repo_name:
            st.error('Provide GitHub token and repo name in the sidebar')
        elif st.session_state.blueprint is None:
            st.error('Build a blueprint first')
        else:
            try:
                with st.spinner('Deploying to GitHub...'):
                    deploy_to_github(github_token, repo_name, st.session_state.blueprint,
                                     commit_message='Automated admin_tools blueprint update',
                                     branch_name=branch)
                st.success('Deployed blueprint to GitHub successfully')
            except Exception as e:
                st.exception(e)

# ---- Utility: small controls ----
st.markdown('---')
col_a, col_b = st.columns(2)
with col_a:
    if st.button('Clear chat'):
        st.session_state.history = []
        st.success('Chat history cleared')
with col_b:
    if st.button('Download blueprint'):
        if st.session_state.blueprint is None:
            st.error('No blueprint to download')
        else:
            payload = json.dumps(st.session_state.blueprint, indent=2, ensure_ascii=False)
            st.download_button('Download JSON', data=payload, file_name='admin_tools_blueprint.json', mime='application/json')

# ---- End of file ----
