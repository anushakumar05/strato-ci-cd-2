# Streamlit UI for Multi-Agent Pipeline

This is a web-based user interface for the multi-agent codebase pipeline that allows you to:
- Execute multi-file operations through a simple form
- Review code for quality and security
- Generate repository summaries
- Manage version control
- Monitor system status

## 🚀 Quick Start

### 1. Install Streamlit Dependencies

```bash
pip install -r requirements-streamlit.txt
```

If that did not work, install Streamlit only:
```bash
pip install streamlit
```

### 2. Run the Streamlit App

```bash
streamlit run streamlit_app.py   --server.port 8502   --server.address localhost   --server.enableCORS false   --server.enableXsrfProtection false
```

The app will automatically open in your browser at `http://localhost:8502`
https://ondemand.anvil.rcac.purdue.edu/rnode/a240.anvil.rcac.purdue.edu/8224/proxy/8502/ is the link to view UI through the Anvil Server

## 📋 Features

### Multi-File Operations Tab
- Enter natural language requests to create/edit/delete files
- View implementation plan before execution
- Auto-approve or manually confirm changes
- See detailed execution logs
- Direct links to GitHub repository

### Code Review Tab
- Paste code or specify file path for review
- Choose between quick or comprehensive review
- Set minimum acceptable score threshold
- View findings organized by severity (Critical, Warning, Suggestion)
- Get actionable suggestions for improvements

### Repository Summary Tab
- Generate AI-powered summaries of your entire codebase
- Option to force full re-summarization
- Save summaries locally or push to GitHub
- Incremental updates (only re-summarize changed files)

### Version Control Tab
- View version history for all tracked files
- Browse past versions with metadata
- Rollback to previous versions
- Track which agent made each change
- Monitor sync status with GitHub

### Settings Tab
- View GitHub configuration
- Check API status (Gemini, GitHub)
- System information
- Cache management

## 🎨 UI Features

- **Responsive Design**: Works on desktop and tablet
- **Dark/Light Mode**: Automatic theme detection
- **Real-time Feedback**: Progress indicators and status updates
- **Error Handling**: Graceful error messages with details
- **Expandable Sections**: Collapsible logs and details

## 🔧 Configuration

The app uses your existing `.env` configuration:

```env
GEMINI_API_KEY=your_gemini_api_key
GITHUB_TOKEN=your_github_token
GITHUB_OWNER=your_username
GITHUB_REPO=your_repo_name
GITHUB_BRANCH=main
```

Make sure these are set before running the app.

## 📁 Project Structure

```
your-project/
├── streamlit_app.py          # Main Streamlit application
├── requirements-streamlit.txt # Streamlit dependencies
├── src/                       # Your existing source code
│   ├── multi_file_agent.py
│   ├── repo_summary.py
│   ├── langchain_agent/
│   └── ...
└── .env                       # Configuration file
```

## Customization

### Change Theme
Create `.streamlit/config.toml`:
```toml
[theme]
primaryColor = "#1f77b4"
backgroundColor = "#ffffff"
secondaryBackgroundColor = "#f0f2f6"
textColor = "#262730"
font = "sans serif"
```

### Adjust Layout
Edit `streamlit_app.py` and modify:
```python
st.set_page_config(
    page_title="Your Title",
    page_icon="🚀",
    layout="wide"  # or "centered"
)
```

## Advanced Features

### Run in Production

For production deployment:

```bash
# With specific config
streamlit run streamlit_app.py --server.port 80 --server.address 0.0.0.0

# Or use environment variables
export STREAMLIT_SERVER_PORT=8501
streamlit run streamlit_app.py
```

## Resources

- [Streamlit Documentation](https://docs.streamlit.io)

