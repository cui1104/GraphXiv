"""
Command-line interface for deepxiv.
"""
import json
import os
import sys
import click
import requests
from pathlib import Path
from uuid import uuid4
from .reader import Reader, APIError, AuthenticationError, BadRequestError, RateLimitError

# Try to load .env file if python-dotenv is available
try:
    from dotenv import load_dotenv
    # Load from home directory first (global config), then current directory (project config)
    # Later files override earlier ones
    env_paths = [
        Path.home() / ".env",  # Home directory (global)
        Path.cwd() / ".env",   # Current directory (project-specific, can override global)
    ]
    for env_path in env_paths:
        if env_path.exists():
            load_dotenv(env_path, override=False)  # Don't override already set env vars
except ImportError:
    # python-dotenv not installed, skip loading .env file
    pass


DEFAULT_BASE_URL = "https://data.rag.ac.cn"
REGISTER_ENDPOINT = f"{DEFAULT_BASE_URL}/api/register"
SDK_REGISTER_ENDPOINT = f"{DEFAULT_BASE_URL}/api/register/sdk"
DEFAULT_DAILY_LIMIT = 10000
# Shared secret for SDK auto-registration (no SMS required).
# Must match SDK_REGISTRATION_SECRET on the server.
_SDK_SECRET = "UuZp0i83svQU7_naUEexczc-X3NWv7lvNkD8e3sPyng"


def get_token(token_option):
    """Get token from option or environment variable."""
    if token_option:
        return token_option
    return os.environ.get("DEEPXIV_TOKEN")


def _upsert_env_value(env_file: Path, key: str, value: str):
    """Insert or update a key=value pair in an env file."""
    env_line = f"{key}={value}\n"

    if env_file.exists():
        with open(env_file, "r") as f:
            lines = f.readlines()

        key_exists = False
        for i, line in enumerate(lines):
            if line.strip().startswith(f"{key}="):
                lines[i] = env_line
                key_exists = True
                break

        if not key_exists:
            lines.append(env_line)

        with open(env_file, "w") as f:
            f.writelines(lines)
    else:
        with open(env_file, "w") as f:
            f.write(env_line)


def save_token(token: str, is_global: bool = True) -> Path:
    """Persist DEEPXIV_TOKEN to the selected env file."""
    env_file = Path.home() / ".env" if is_global else Path.cwd() / ".env"
    _upsert_env_value(env_file, "DEEPXIV_TOKEN", token)
    os.environ["DEEPXIV_TOKEN"] = token
    return env_file


def generate_registration_payload() -> dict:
    """Generate random registration data for automatic token provisioning."""
    suffix = uuid4().hex[:10]
    return {
        "sdk_secret": _SDK_SECRET,
        "name": f"deepxiv_{suffix}",
        "email": f"{suffix}@example.com",
    }


def auto_register_token() -> tuple[str | None, int | None]:
    """Automatically register for a token and persist it."""
    payload = generate_registration_payload()

    try:
        response = requests.post(SDK_REGISTER_ENDPOINT, json=payload, timeout=30)
        response.raise_for_status()
        result = response.json()
    except requests.exceptions.RequestException as e:
        click.echo(f"\n❌ Failed to auto-register DEEPXIV token: {e}\n", err=True)
        return None, None
    except ValueError as e:
        click.echo(f"\n❌ Failed to parse registration response: {e}\n", err=True)
        return None, None

    if not result.get("success"):
        click.echo("\n❌ Failed to auto-register DEEPXIV token.\n", err=True)
        message = result.get("message", "Unknown error")
        click.echo(f"Server message: {message}\n", err=True)
        return None, None

    data = result.get("data", {})
    token = data.get("token")
    daily_limit = data.get("daily_limit", DEFAULT_DAILY_LIMIT)
    if not token:
        click.echo("\n❌ Registration succeeded but no token was returned.\n", err=True)
        return None, None

    env_file = save_token(token, is_global=True)
    click.echo(f"已自动申请 token，并已保存到 {env_file}")
    click.echo(f"当前 daily limit: {daily_limit}\n")
    return token, daily_limit


def ensure_token(token_option=None, auto_create: bool = True):
    """Get an existing token or auto-create one on first use."""
    token = get_token(token_option)
    if token:
        return token

    if not auto_create:
        return None

    token, _ = auto_register_token()
    return token


def check_token_and_warn(token):
    """Check if token is configured and warn if not."""
    if not token:
        click.echo("⚠️  Warning: DEEPXIV_TOKEN not configured.", err=True)
        click.echo("   Some features may not work without authentication.\n", err=True)
        click.echo("   Get your free token at: https://data.rag.ac.cn/register", err=True)
        click.echo("   Then configure it with: deepxiv config\n", err=True)
        return False
    return True


def handle_auth_error():
    """Handle authentication errors with helpful message."""
    click.echo("\n❌ 认证失败（401 Unauthorized） / Authentication failed (401 Unauthorized)\n", err=True)
    click.echo("当前 API token 缺失或无效。 / Your API token is missing or invalid.\n", err=True)
    click.echo("你可以重新运行任意 deepxiv 命令自动注册新 token。 / Try running any deepxiv command again to auto-register a new token.", err=True)
    click.echo("或手动设置：export DEEPXIV_TOKEN=your_token / Or set it directly: export DEEPXIV_TOKEN=your_token", err=True)
    click.echo("使用 `deepxiv token` 查看当前 token。 / Use `deepxiv token` to inspect the current token.\n", err=True)


def handle_rate_limit_error():
    """Handle daily limit errors with a friendly message."""
    click.echo("\n❌ 当前 token 已到日使用上限。 / Your token has reached its daily usage limit.\n", err=True)
    click.echo("请访问 https://data.rag.ac.cn/register 注册，以获得更高 limit。 / Visit https://data.rag.ac.cn/register to get a higher limit.\n", err=True)


def handle_bad_request_error(command_name="command"):
    """Handle invalid requests with command-specific hints."""
    click.echo("\n❌ 请求参数有误。 / Invalid request arguments.\n", err=True)

    if command_name == "paper":
        click.echo("`deepxiv paper` 需要传入 arXiv ID，例如 `2409.05591`。 / `deepxiv paper` expects an arXiv ID such as `2409.05591`.\n", err=True)
        click.echo("如果你输入的是关键词，请先使用 `deepxiv search \"keyword\"` 查到论文 ID 再读取。 / If you entered a keyword, use `deepxiv search \"keyword\"` first to find the paper ID.\n", err=True)
    elif command_name == "pmc":
        click.echo("`deepxiv pmc` 需要传入 PMC ID，例如 `PMC544940`。 / `deepxiv pmc` expects a PMC ID such as `PMC544940`.\n", err=True)
    elif command_name == "search":
        click.echo("请检查搜索关键词和筛选参数是否正确。 / Please check your search query and filters.\n", err=True)
    elif command_name in ("biorxiv", "medrxiv"):
        click.echo(f"`deepxiv {command_name}` 需要传入 DOI，例如 `10.1101/2021.02.26.433129`。 / `deepxiv {command_name}` expects a DOI such as `10.1101/2021.02.26.433129`.\n", err=True)
    else:
        click.echo("请检查命令参数、论文 ID 或筛选条件是否正确。 / Please check your command arguments, paper ID, or filters.\n", err=True)


def run_reader_call(fn, command_name="command"):
    """Run a reader call and convert API exceptions into friendly CLI output."""
    try:
        return fn()
    except BadRequestError:
        handle_bad_request_error(command_name)
        sys.exit(1)
    except AuthenticationError:
        handle_auth_error()
        sys.exit(1)
    except RateLimitError:
        handle_rate_limit_error()
        sys.exit(1)
    except APIError as e:
        click.echo(f"\n❌ Error: {e}\n", err=True)
        sys.exit(1)


def get_agent_config():
    """Get agent LLM configuration from environment or config file."""
    config = {}

    # Try environment variables first
    config["api_key"] = os.environ.get("DEEPXIV_AGENT_API_KEY")
    config["base_url"] = os.environ.get("DEEPXIV_AGENT_BASE_URL")
    config["model"] = os.environ.get("DEEPXIV_AGENT_MODEL")

    # If not in env, try to load from config file
    if not config["api_key"]:
        config_file = Path.home() / ".deepxiv_agent_config.json"
        if config_file.exists():
            try:
                with open(config_file, "r") as f:
                    file_config = json.load(f)
                    config["api_key"] = config["api_key"] or file_config.get("api_key")
                    config["base_url"] = config["base_url"] or file_config.get("base_url")
                    config["model"] = config["model"] or file_config.get("model", "gpt-4")
            except Exception:
                pass
    return config


def save_agent_config(api_key, base_url=None, model="gpt-4"):
    """Save agent LLM configuration to config file."""
    config_file = Path.home() / ".deepxiv_agent_config.json"
    config = {
        "api_key": api_key,
        "base_url": base_url,
        "model": model
    }

    with open(config_file, "w") as f:
        json.dump(config, f, indent=2)

    click.echo(f"✅ Agent configuration saved to {config_file}")
    click.echo("   This file stays on your local machine only.")


def check_agent_config():
    """Check if agent is configured and warn if not."""
    config = get_agent_config()
    if not config.get("api_key"):
        click.echo("⚠️  Warning: Agent LLM API not configured.", err=True)
        click.echo("   Please configure it with: deepxiv agent config\n", err=True)
        return False
    return True


@click.group()
@click.version_option()
def main():
    """deepxiv - Access arXiv papers from the command line.

    Set token via --token option or DEEPXIV_TOKEN environment variable.
    """
    pass


@main.command()
@click.argument("query")
@click.option("--token", "-t", default=None, envvar="DEEPXIV_TOKEN", help="API token (or set DEEPXIV_TOKEN env var)")
@click.option("--limit", "-l", default=10, help="Number of results to return (default: 10)")
@click.option("--mode", "-m", default="hybrid", type=click.Choice(["bm25", "vector", "hybrid"]),
              help="Search mode (default: hybrid)")
@click.option("--format", "-f", "output_format", default="text", type=click.Choice(["text", "json"]),
              help="Output format (default: text)")
@click.option("--categories", "-c", default=None, help="Filter by categories (comma-separated, e.g., cs.AI,cs.CL)")
@click.option("--min-citations", default=None, type=int, help="Minimum citation count")
@click.option("--date-from", default=None, help="Publication date from (YYYY-MM-DD or YYYY-MM)")
@click.option("--date-to", default=None, help="Publication date to (YYYY-MM-DD or YYYY-MM)")
@click.option("--biorxiv", "source", flag_value="biorxiv", default=False, help="Search bioRxiv preprints")
@click.option("--medrxiv", "source", flag_value="medrxiv", default=False, help="Search medRxiv preprints")
def search(query, token, limit, mode, output_format, categories, min_citations, date_from, date_to, source):
    """Search for papers (arXiv by default; use --biorxiv or --medrxiv for preprints).

    Example:
        deepxiv search "agent memory" --limit 5
        deepxiv search "transformer" --mode bm25 --format json
        deepxiv search "protein design" --biorxiv --limit 5
        deepxiv search "Alzheimer" --medrxiv --date-from 2024-01
    """
    token = ensure_token(token)
    if not token:
        sys.exit(1)

    reader = Reader(token=token)

    # ── bioRxiv / medRxiv search ──────────────────────────────────────────────
    if source in ("biorxiv", "medrxiv"):
        date_search_type = None
        date_str = None
        if date_from and date_to:
            date_search_type = "between"
            date_str = [date_from, date_to]
        elif date_from:
            date_search_type = "after"
            date_str = date_from
        elif date_to:
            date_search_type = "before"
            date_str = date_to

        results = run_reader_call(
            lambda: reader.biomed_search(
                query=query,
                source=source,
                top_k=limit,
                date_search_type=date_search_type,
                date_str=date_str,
            ),
            command_name="search",
        )

        if output_format == "json":
            click.echo(json.dumps(results, indent=2))
            return

        result_list = results.get("result", [])
        total = results.get("total_count", len(result_list))
        label = "bioRxiv" if source == "biorxiv" else "medRxiv"
        click.echo(f"\nFound {total} {label} papers for '{query}' (showing {len(result_list)}):\n")

        for i, paper in enumerate(result_list, 1):
            paper_id = paper.get("biorxiv_id", paper.get("medrxiv_id", "Unknown"))
            title = paper.get("title", "No title")
            abstract = paper.get("abstract", paper.get("tldr", ""))[:200]
            score = paper.get("score", 0)
            date = paper.get("date", "N/A")

            click.echo(f"{i}. {title}")
            click.echo(f"   ID: {paper_id} | Score: {score:.3f} | Date: {date}")
            if abstract:
                click.echo(f"   {abstract}...")
            click.echo()
        return

    # ── arXiv search (default) ────────────────────────────────────────────────
    cat_list = None
    if categories:
        cat_list = [c.strip() for c in categories.split(",")]

    results = run_reader_call(
        lambda: reader.search(
            query=query,
            size=limit,
            search_mode=mode,
            categories=cat_list,
            min_citation=min_citations,
            date_from=date_from,
            date_to=date_to,
        ),
        command_name="search",
    )

    if not results:
        handle_auth_error()
        sys.exit(1)

    if output_format == "json":
        click.echo(json.dumps(results, indent=2))
    else:
        total = results.get("total", 0)
        result_list = results.get("results", [])

        click.echo(f"\nFound {total} papers for '{query}' (showing {len(result_list)}):\n")

        for i, paper in enumerate(result_list, 1):
            arxiv_id = paper.get("arxiv_id", "Unknown")
            title = paper.get("title", "No title")
            abstract = paper.get("abstract", "")[:200]
            score = paper.get("score", 0)
            citations = paper.get("citation", 0)

            click.echo(f"{i}. {title}")
            click.echo(f"   arXiv: {arxiv_id} | Score: {score:.3f} | Citations: {citations}")
            click.echo(f"   {abstract}...")
            click.echo()


@main.command(name="wsearch")
@click.argument("query")
@click.option("--token", "-t", default=None, envvar="DEEPXIV_TOKEN", help="API token (or set DEEPXIV_TOKEN env var)")
@click.option("--output", "-o", "output_format", type=click.Choice(["text", "json"]),
              default="text", help="Output format (default: text)")
@click.option("--json", "json_output", is_flag=True, help="Shorthand for --output json")
def websearch_command(query, token, output_format, json_output):
    """Search the web.

    Example:
        deepxiv wsearch "karpathy"
        deepxiv wsearch "karpathy" --json
    """
    if json_output:
        output_format = "json"

    token = ensure_token(token)
    if not token:
        sys.exit(1)

    reader = Reader(token=token)
    result = run_reader_call(
        lambda: reader.websearch(query),
        command_name="search",
    )

    if output_format == "json":
        click.echo(json.dumps(result, indent=2, ensure_ascii=False))
        return

    if not result:
        click.echo("ℹ️  No web search results found.")
        return

    click.echo(f"\n🌐 Web Search Results for '{query}'\n")
    click.echo(json.dumps(result, indent=2, ensure_ascii=False))


@main.command(name="sc")
@click.argument("semantic_scholar_id")
@click.option("--token", "-t", default=None, envvar="DEEPXIV_TOKEN", help="API token (or set DEEPXIV_TOKEN env var)")
@click.option("--output", "-o", "output_format", type=click.Choice(["text", "json"]),
              default="json", help="Output format (default: json)")
@click.option("--json", "json_output", is_flag=True, help="Shorthand for --output json")
def semantic_scholar_command(semantic_scholar_id, token, output_format, json_output):
    """Get paper data by Semantic Scholar ID.

    Example:
        deepxiv sc 258001
        deepxiv sc 258001 --json
    """
    if json_output:
        output_format = "json"

    token = ensure_token(token)
    if not token:
        sys.exit(1)

    reader = Reader(token=token)
    result = run_reader_call(
        lambda: reader.semantic_scholar(semantic_scholar_id),
        command_name="search",
    )

    if output_format == "json":
        click.echo(json.dumps(result, indent=2, ensure_ascii=False))
        return

    if not result:
        click.echo("ℹ️  No Semantic Scholar result found.")
        return

    click.echo(f"\n🧠 Semantic Scholar Result for '{semantic_scholar_id}'\n")
    click.echo(json.dumps(result, indent=2, ensure_ascii=False))


@main.command()
@click.argument("arxiv_id")
@click.option("--token", "-t", default=None, envvar="DEEPXIV_TOKEN", help="API token (or set DEEPXIV_TOKEN env var)")
@click.option("--format", "-f", "output_format", default="markdown", type=click.Choice(["markdown", "json"]),
              help="Output format (default: markdown)")
@click.option("--section", "-s", default=None, help="Get a specific section by name")
@click.option("--preview", "-p", is_flag=True, help="Get only a preview (first ~10k chars)")
@click.option("--head", is_flag=True, help="Get paper metadata (returns JSON)")
@click.option("--brief", "-b", is_flag=True, help="Get brief info (title, TLDR, keywords, citations, GitHub URL)")
@click.option("--raw", is_flag=True, help="Get raw markdown content")
@click.option("--popularity", is_flag=True, help="Get social impact metrics (trending signal)")
@click.option("--biorxiv", "bio_source", flag_value="biorxiv", default=False, help="Treat ID as bioRxiv DOI")
@click.option("--medrxiv", "bio_source", flag_value="medrxiv", default=False, help="Treat ID as medRxiv DOI")
def paper(arxiv_id, token, output_format, section, preview, head, brief, raw, popularity, bio_source):
    """Get an arXiv paper by ID (or bioRxiv/medRxiv paper with --biorxiv/--medrxiv).

    Example:
        deepxiv paper 2409.05591
        deepxiv paper 2409.05591 --brief
        deepxiv paper 2409.05591 --section Introduction
        deepxiv paper 10.1101/2021.02.26.433129 --biorxiv
        deepxiv paper 10.1101/2021.02.26.433129 --biorxiv --section Introduction
        deepxiv paper 10.1101/2025.08.11.25333149 --medrxiv
    """
    # ── bioRxiv / medRxiv via --biorxiv / --medrxiv flag ─────────────────────
    if bio_source in ("biorxiv", "medrxiv"):
        token = ensure_token(token)
        if not token:
            sys.exit(1)
        reader = Reader(token=token)
        if section:
            data_type = "section"
            section_names = [s.strip() for s in section.split(",")]
        else:
            data_type = "metadata"
            section_names = None

        result = run_reader_call(
            lambda: reader.biomed_data(
                source_id=arxiv_id,
                source=bio_source,
                data_type=data_type,
                section_names=section_names,
            ),
            command_name=bio_source,
        )
        if not result:
            handle_auth_error()
            sys.exit(1)

        if output_format == "json" or data_type == "section":
            click.echo(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            _print_biomed_metadata(result, "bioRxiv" if bio_source == "biorxiv" else "medRxiv")
        return

    # Handle --popularity flag (requires token)
    if popularity:
        token = get_token(token)
        if not token:
            check_token_and_warn(token)
            return

        reader = Reader(token=token)
        try:
            impact = run_reader_call(lambda: reader.social_impact(arxiv_id), command_name="paper")

            if output_format == "json":
                if impact:
                    click.echo(json.dumps(impact, indent=2))
                else:
                    click.echo(json.dumps({"arxiv_id": arxiv_id, "data": None}, indent=2))
            else:
                if impact:
                    click.echo(f"\n📱 Social Impact Metrics for arXiv:{arxiv_id}\n")
                    click.echo(f"  📊 Views:     {impact.get('total_views', 'N/A')}")
                    click.echo(f"  🐦 Tweets:    {impact.get('total_tweets', 'N/A')}")
                    click.echo(f"  👍 Likes:     {impact.get('total_likes', 'N/A')}")
                    click.echo(f"  💬 Replies:   {impact.get('total_replies', 'N/A')}")
                    click.echo(f"\n  📅 First seen: {impact.get('first_seen_date', 'N/A')}")
                    click.echo(f"  📅 Last seen:  {impact.get('last_seen_date', 'N/A')}\n")
                else:
                    click.echo(f"ℹ️  No social impact data found for arXiv:{arxiv_id}")
                    click.echo("   This paper may be too old or not mentioned on social media.\n")
        except Exception as e:
            click.echo(f"❌ Error: {e}", err=True)
            sys.exit(1)
        return

    token = ensure_token(token)
    if not token:
        sys.exit(1)

    reader = Reader(token=token)

    if head:
        # Get paper metadata
        result = run_reader_call(lambda: reader.head(arxiv_id), command_name="paper")
        if not result:
            handle_auth_error()
            sys.exit(1)
        click.echo(json.dumps(result, indent=2))

    elif brief:
        # Get brief information
        result = run_reader_call(lambda: reader.brief(arxiv_id), command_name="paper")
        if not result:
            handle_auth_error()
            sys.exit(1)

        if output_format == "json":
            click.echo(json.dumps(result, indent=2))
        else:
            # Pretty print brief info
            click.echo(f"\n📄 {result.get('title', 'No title')}\n")
            click.echo(f"🆔 arXiv: {result.get('arxiv_id', arxiv_id)}")
            click.echo(f"📅 Published: {result.get('publish_at', 'N/A')}")
            click.echo(f"📊 Citations: {result.get('citations', 0)}")
            click.echo(f"🔗 PDF: {result.get('src_url', 'N/A')}")
            if result.get("github_url"):
                click.echo(f"💻 GitHub: {result.get('github_url')}")

            if result.get('keywords'):
                keywords = result.get('keywords', [])
                if isinstance(keywords, list):
                    click.echo(f"\n🏷️  Keywords: {', '.join(keywords)}")
                else:
                    click.echo(f"\n🏷️  Keywords: {keywords}")

            if result.get('tldr'):
                click.echo(f"\n💡 TLDR:\n{result.get('tldr')}\n")

    elif raw:
        # Get raw markdown content
        content = run_reader_call(lambda: reader.raw(arxiv_id), command_name="paper")
        if not content:
            handle_auth_error()
            sys.exit(1)
        click.echo(content)

    elif section:
        # Get specific section
        content = run_reader_call(lambda: reader.section(arxiv_id, section), command_name="paper")
        if not content:
            handle_auth_error()
            sys.exit(1)

        if output_format == "json":
            click.echo(json.dumps({"arxiv_id": arxiv_id, "section": section, "content": content}, indent=2))
        else:
            click.echo(f"# {section}\n")
            click.echo(content)

    elif preview:
        # Get preview
        result = run_reader_call(lambda: reader.preview(arxiv_id), command_name="paper")
        if not result:
            handle_auth_error()
            sys.exit(1)

        if output_format == "json":
            click.echo(json.dumps(result, indent=2))
        else:
            click.echo(result.get("content", result.get("preview", "")))

    elif output_format == "json":
        # Get full JSON
        result = run_reader_call(lambda: reader.json(arxiv_id), command_name="paper")
        if not result:
            handle_auth_error()
            sys.exit(1)
        click.echo(json.dumps(result, indent=2))

    else:
        # Get full markdown
        content = run_reader_call(lambda: reader.raw(arxiv_id), command_name="paper")
        if not content:
            # Try head for metadata
            head = run_reader_call(lambda: reader.head(arxiv_id), command_name="paper")
            if head:
                click.echo(f"# {head.get('title', arxiv_id)}\n")
                click.echo(f"**Authors:** {', '.join([a.get('name', str(a)) if isinstance(a, dict) else str(a) for a in head.get('authors', [])])}\n")
                click.echo(f"**Categories:** {', '.join(head.get('categories', []))}\n")
                click.echo(f"\n## Abstract\n\n{head.get('abstract', 'No abstract')}\n")
                click.echo("\n## Sections\n")
                for name, info in head.get("sections", {}).items():
                    click.echo(f"- {name}: {info.get('tldr', 'No summary')[:100]}...")
            else:
                handle_auth_error()
                sys.exit(1)
        else:
            click.echo(content)


@main.command()
@click.option("--token", "-t", default=None, help="DEEPXIV_TOKEN to save (if not provided, will prompt)")
@click.option("--global", "-g", "is_global", is_flag=True, default=True, help="Save to home directory (default: True)")
def config(token, is_global):
    """Configure DEEPXIV_TOKEN in .env file.

    Get your free token at: https://data.rag.ac.cn/register

    Example:
        deepxiv config                    # Save to ~/.env (global)
        deepxiv config --token YOUR_TOKEN
        deepxiv config --no-global        # Save to current directory
    """
    # Get token from option or prompt
    if not token:
        click.echo("📝 Get your free token at: https://data.rag.ac.cn/register\n")
        token = click.prompt("Please enter your DEEPXIV_TOKEN", hide_input=True)

    if not token or not token.strip():
        click.echo("Error: Token cannot be empty", err=True)
        sys.exit(1)

    token = token.strip()

    # Determine .env file location
    if is_global:
        env_file = Path.home() / ".env"
    else:
        env_file = Path.cwd() / ".env"

    existed = env_file.exists() and f"DEEPXIV_TOKEN=" in env_file.read_text()
    _upsert_env_value(env_file, "DEEPXIV_TOKEN", token)
    os.environ["DEEPXIV_TOKEN"] = token
    action = "updated" if existed else "added"
    click.echo(f"✓ DEEPXIV_TOKEN {action} in {env_file}")

    click.echo(f"\n✅ Token saved successfully!")
    click.echo(f"   The deepxiv CLI will automatically load it from {env_file}")
    click.echo(f"\n💡 To use in other apps/shells:")
    click.echo(f"   - Run: source {env_file}")
    click.echo(f"   - Or add to ~/.bashrc: export DEEPXIV_TOKEN=your_token")


@main.command()
@click.argument("pmc_id")
@click.option("--token", "-t", default=None, envvar="DEEPXIV_TOKEN", help="API token (or set DEEPXIV_TOKEN env var)")
@click.option("--format", "-f", "output_format", default="json", type=click.Choice(["json"]),
              help="Output format (default: json)")
@click.option("--head", is_flag=True, help="Get PMC paper metadata (returns JSON)")
def pmc(pmc_id, token, output_format, head):
    """Get a PMC (PubMed Central) paper by ID.

    Example:
        deepxiv pmc PMC544940
        deepxiv pmc PMC544940 --head
        deepxiv pmc PMC514704 --token YOUR_TOKEN
    """
    token = ensure_token(token)
    if not token:
        sys.exit(1)

    reader = Reader(token=token)

    if head:
        # Get PMC paper metadata
        result = run_reader_call(lambda: reader.pmc_head(pmc_id), command_name="pmc")
        if not result:
            handle_auth_error()
            sys.exit(1)
        click.echo(json.dumps(result, indent=2))
    else:
        # Get full PMC JSON
        result = run_reader_call(lambda: reader.pmc_json(pmc_id), command_name="pmc")
        if not result:
            handle_auth_error()
            sys.exit(1)
        click.echo(json.dumps(result, indent=2))


def _print_biomed_metadata(result: dict, label: str):
    """Pretty-print bioRxiv / medRxiv metadata."""
    click.echo(f"\n📄 {result.get('title', 'No title')}\n")
    click.echo(f"🆔 DOI: {result.get('source_id', 'N/A')}")
    click.echo(f"📅 Date: {result.get('publication_date', result.get('date', 'N/A'))}")
    click.echo(f"🔗 URL: {result.get('url', 'N/A')}")
    authors = result.get("authors", [])
    if authors:
        names = ", ".join(
            a.get("name", str(a)) if isinstance(a, dict) else str(a)
            for a in authors[:5]
        )
        if len(authors) > 5:
            names += f" ... (+{len(authors) - 5} more)"
        click.echo(f"👤 Authors: {names}")
    categories = result.get("categories", [])
    if categories:
        click.echo(f"🏷️  Categories: {', '.join(categories)}")
    if result.get("tldr"):
        click.echo(f"\n💡 TLDR:\n{result['tldr']}\n")
    elif result.get("abstract"):
        click.echo(f"\n📝 Abstract:\n{result['abstract'][:500]}...\n")


@main.command()
@click.argument("source_id")
@click.option("--token", "-t", default=None, envvar="DEEPXIV_TOKEN", help="API token (or set DEEPXIV_TOKEN env var)")
@click.option("--format", "-f", "output_format", default="json", type=click.Choice(["json", "text"]),
              help="Output format (default: json)")
@click.option("--section", "-s", default=None, help="Get specific section(s) by name (comma-separated)")
@click.option("--roc", is_flag=True, help="Get cited-by-reason list")
@click.option("--roc-num", default=None, type=int, help="Limit number of cited-by-reason entries")
def biorxiv(source_id, token, output_format, section, roc, roc_num):
    """Get a bioRxiv paper by DOI.

    SOURCE_ID is the paper DOI, e.g. 10.1101/2021.02.26.433129

    Example:
        deepxiv biorxiv 10.1101/2021.02.26.433129
        deepxiv biorxiv 10.1101/2021.02.26.433129 --format text
        deepxiv biorxiv 10.1101/2021.02.26.433129 --section Introduction,Methods
        deepxiv biorxiv 10.1101/2021.02.26.433129 --roc --roc-num 5
    """
    token = ensure_token(token)
    if not token:
        sys.exit(1)

    reader = Reader(token=token)

    if roc:
        data_type = "roc"
        section_names = None
    elif section:
        data_type = "section"
        section_names = [s.strip() for s in section.split(",")]
    else:
        data_type = "metadata"
        section_names = None

    result = run_reader_call(
        lambda: reader.biomed_data(
            source_id=source_id,
            source="biorxiv",
            data_type=data_type,
            section_names=section_names,
            roc_num=roc_num,
        ),
        command_name="biorxiv",
    )

    if not result:
        handle_auth_error()
        sys.exit(1)

    if output_format == "text" and data_type == "metadata":
        _print_biomed_metadata(result, "bioRxiv")
    else:
        click.echo(json.dumps(result, indent=2, ensure_ascii=False))


@main.command()
@click.argument("source_id")
@click.option("--token", "-t", default=None, envvar="DEEPXIV_TOKEN", help="API token (or set DEEPXIV_TOKEN env var)")
@click.option("--format", "-f", "output_format", default="json", type=click.Choice(["json", "text"]),
              help="Output format (default: json)")
@click.option("--section", "-s", default=None, help="Get specific section(s) by name (comma-separated)")
@click.option("--roc", is_flag=True, help="Get cited-by-reason list")
@click.option("--roc-num", default=None, type=int, help="Limit number of cited-by-reason entries")
def medrxiv(source_id, token, output_format, section, roc, roc_num):
    """Get a medRxiv paper by DOI.

    SOURCE_ID is the paper DOI, e.g. 10.1101/2025.08.11.25333149

    Example:
        deepxiv medrxiv 10.1101/2025.08.11.25333149
        deepxiv medrxiv 10.1101/2025.08.11.25333149 --format text
        deepxiv medrxiv 10.1101/2025.08.11.25333149 --section Introduction
        deepxiv medrxiv 10.1101/2025.08.11.25333149 --roc
    """
    token = ensure_token(token)
    if not token:
        sys.exit(1)

    reader = Reader(token=token)

    if roc:
        data_type = "roc"
        section_names = None
    elif section:
        data_type = "section"
        section_names = [s.strip() for s in section.split(",")]
    else:
        data_type = "metadata"
        section_names = None

    result = run_reader_call(
        lambda: reader.biomed_data(
            source_id=source_id,
            source="medrxiv",
            data_type=data_type,
            section_names=section_names,
            roc_num=roc_num,
        ),
        command_name="medrxiv",
    )

    if not result:
        handle_auth_error()
        sys.exit(1)

    if output_format == "text" and data_type == "metadata":
        _print_biomed_metadata(result, "medRxiv")
    else:
        click.echo(json.dumps(result, indent=2, ensure_ascii=False))


@main.command()
def help():
    """Show detailed help and usage examples.

    Example:
        deepxiv help
    """
    help_text = """
deepxiv - Access arXiv papers from the command line

CONFIGURATION:
  deepxiv config                    Configure your DEEPXIV_TOKEN manually
  deepxiv token                     Show the current token and support contact

SEARCH:
  deepxiv search "query"            Search for papers
  deepxiv wsearch "query"           Search the web
  deepxiv sc ID                     Get paper data by Semantic Scholar ID
    --limit, -l N                   Number of results (default: 10)
    --mode, -m MODE                 Search mode: bm25, vector, hybrid (default: hybrid)
    --format, -f FORMAT             Output format: text, json (default: text)
    --categories, -c CATS           Filter by categories (e.g., cs.AI,cs.CL)
    --min-citations N               Minimum citation count
    --date-from YYYY-MM-DD          Publication date from
    --date-to YYYY-MM-DD            Publication date to

GET PAPER:
  deepxiv paper ARXIV_ID            Get paper by arXiv ID
    --head                          Get paper metadata (JSON)
    --brief, -b                     Get brief info (title, TLDR, keywords, citations, GitHub URL)
    --raw                           Get raw markdown content
    --preview, -p                   Get preview (~10k chars)
    --section, -s NAME              Get specific section
    --format, -f FORMAT             Output format: markdown, json (default: markdown)

GET PMC PAPER:
  deepxiv pmc PMC_ID                Get PMC paper by ID
    --head                          Get PMC paper metadata (JSON)
    --format, -f FORMAT             Output format: json (default: json)

GET bioRxiv PAPER:
  deepxiv biorxiv DOI               Get bioRxiv paper by DOI
    --section, -s NAMES             Get specific section(s), comma-separated
    --roc                           Get cited-by-reason list
    --roc-num N                     Limit cited-by-reason entries
    --format, -f FORMAT             Output format: json, text (default: json)

GET medRxiv PAPER:
  deepxiv medrxiv DOI               Get medRxiv paper by DOI
    --section, -s NAMES             Get specific section(s), comma-separated
    --roc                           Get cited-by-reason list
    --roc-num N                     Limit cited-by-reason entries
    --format, -f FORMAT             Output format: json, text (default: json)

MCP SERVER:
  deepxiv serve                     Start MCP server
    --transport, -t TYPE            Transport type: stdio (default: stdio)

EXAMPLES:
  # Configure token
  deepxiv config

  # Search examples
  deepxiv search "transformer architecture" --limit 5
  deepxiv search "protein design" --biorxiv --limit 5
  deepxiv search "Alzheimer" --medrxiv --date-from 2024-01
  deepxiv wsearch "karpathy"
  deepxiv wsearch "karpathy" --json
  deepxiv sc 258001
  deepxiv search "machine learning" --categories cs.AI,cs.LG --min-citations 100
  deepxiv search "quantum computing" --mode vector --format json

  # Get paper examples
  deepxiv paper 2409.05591
  deepxiv paper 2409.05591 --head
  deepxiv paper 2409.05591 --brief
  deepxiv paper 2409.05591 --raw
  deepxiv paper 2409.05591 --preview
  deepxiv paper 2409.05591 --section Introduction

  # Get PMC paper examples
  deepxiv pmc PMC544940
  deepxiv pmc PMC544940 --head
  deepxiv pmc PMC514704

  # Get bioRxiv / medRxiv paper examples
  deepxiv biorxiv 10.1101/2021.02.26.433129
  deepxiv biorxiv 10.1101/2021.02.26.433129 --format text
  deepxiv biorxiv 10.1101/2021.02.26.433129 --section Introduction,Methods
  deepxiv medrxiv 10.1101/2025.08.11.25333149
  deepxiv medrxiv 10.1101/2025.08.11.25333149 --format text

  # Get bioRxiv / medRxiv paper examples
  deepxiv biorxiv 10.1101/2021.02.26.433129
  deepxiv biorxiv 10.1101/2021.02.26.433129 --format text
  deepxiv biorxiv 10.1101/2021.02.26.433129 --section Introduction,Methods
  deepxiv biorxiv 10.1101/2021.02.26.433129 --roc --roc-num 5
  deepxiv medrxiv 10.1101/2025.08.11.25333149
  deepxiv medrxiv 10.1101/2025.08.11.25333149 --format text

ENVIRONMENT:
  If DEEPXIV_TOKEN is missing, deepxiv will auto-register one on first use.

  Set DEEPXIV_TOKEN via:
    - Config command: deepxiv config (recommended)
    - Inspect current token: deepxiv token
    - Environment variable: export DEEPXIV_TOKEN=your_token
    - Command option: --token YOUR_TOKEN

For more information, visit: https://data.rag.ac.cn
"""
    click.echo(help_text)


@main.group()
def agent():
    """Intelligent agent for paper research.

    Use the agent to ask questions about papers, search and analyze research.

    Example:
        deepxiv agent query "What are the latest papers about agent memory?"
        deepxiv agent config  # Configure LLM API locally first
    """
    pass


@agent.command(name="query")
@click.argument("query")
@click.option("--token", "-t", default=None, envvar="DEEPXIV_TOKEN", help="DeepXiv API token")
@click.option("--max-turn", default=20, type=int, help="Maximum number of reasoning turns (default: 20)")
@click.option("--verbose", "-v", is_flag=True, help="Show detailed reasoning process")
@click.option("--api-key", default=None, envvar="DEEPXIV_AGENT_API_KEY", help="LLM API key (overrides config)")
@click.option("--base-url", default=None, envvar="DEEPXIV_AGENT_BASE_URL", help="LLM API base URL (overrides config)")
@click.option("--model", default=None, envvar="DEEPXIV_AGENT_MODEL", help="Model name (overrides config)")
def agent_query(query, token, max_turn, verbose, api_key, base_url, model):
    """Ask the agent a question about papers.

    The agent can search papers, read content, and provide intelligent answers.

    Example:
        deepxiv agent query "What are the latest papers about agent memory?"
        deepxiv agent query "Compare transformer variants" --max-turn 10 --verbose
    """

    # Run the query logic (same as agent_query)
    # Check DeepXiv token
    token = ensure_token(token)
    if not token:
        sys.exit(1)

    # Get LLM config from options or saved config
    llm_config = get_agent_config()
    # Override with command-line options if provided
    if api_key:
        llm_config["api_key"] = api_key
    if base_url:
        llm_config["base_url"] = base_url
    if model:
        llm_config["model"] = model

    # Check if LLM is configured
    if not llm_config.get("api_key"):
        click.echo("\n❌ Agent LLM API not configured.\n", err=True)
        click.echo("Please configure it first:", err=True)
        click.echo("   deepxiv agent config\n", err=True)
        click.echo("Or set environment variables:", err=True)
        click.echo("   export DEEPXIV_AGENT_API_KEY=your_key", err=True)
        sys.exit(1)

    # Initialize reader
    reader = Reader(token=token)

    # Initialize agent
    try:
        from .agent import Agent
    except ImportError as e:
        click.echo("\n❌ Agent dependencies are not installed.\n", err=True)
        click.echo("The `deepxiv agent` command requires optional agent packages.", err=True)
        click.echo("Missing dependency details:", err=True)
        click.echo(f"   {e}", err=True)
        click.echo("\nInstall the missing packages and try again.", err=True)
        click.echo("If `langgraph` is missing, for example:", err=True)
        click.echo("   pip install langgraph langchain-core", err=True)
        sys.exit(1)

    try:
        agent_instance = Agent(
            api_key=llm_config["api_key"],
            reader=reader,
            model=llm_config.get("model", "gpt-4"),
            base_url=llm_config.get("base_url"),
            max_llm_calls=max_turn,
            print_process=verbose,
            stream=verbose
        )

        # Run query
        click.echo(f"\n🤖 Agent is thinking...\n")
        answer = agent_instance.query(query)

        # Print answer
        click.echo("\n" + "="*80)
        click.echo("📝 Answer:")
        click.echo("="*80)
        click.echo(answer)
        click.echo("="*80 + "\n")

    except Exception as e:
        click.echo(f"\n❌ Error: {e}", err=True)
        sys.exit(1)


@agent.command(name="config")
@click.option("--api-key", default=None, help="LLM API key")
@click.option("--base-url", default=None, help="LLM API base URL (for OpenAI-compatible APIs)")
@click.option("--model", default=None, help="Model name (default: gpt-4)")
def agent_config(api_key, base_url, model):
    """Configure LLM API for the agent.

    Example:
        deepxiv agent config                                    # Interactive local configuration
        deepxiv agent config --api-key YOUR_KEY                 # OpenAI
        deepxiv agent config --api-key KEY --base-url https://api.deepseek.com --model deepseek-chat
    """
    # Get inputs interactively if not provided
    if not api_key:
        click.echo("🤖 Configure LLM API for deepxiv agent\n")
        click.echo("This configuration is stored locally on this machine only.\n")
        api_key = click.prompt("Please enter your LLM API key", hide_input=True)

    if not api_key or not api_key.strip():
        click.echo("Error: API key cannot be empty", err=True)
        sys.exit(1)

    api_key = api_key.strip()

    # Optional: ask for base_url if not provided
    if base_url is None:
        click.echo("\nAPI Base URL (leave empty for OpenAI)")
        click.echo("Examples: https://api.deepseek.com, https://api.openai.com/v1")
        base_url_input = click.prompt("Base URL", default="", show_default=False)
        base_url = base_url_input.strip() if base_url_input.strip() else None

    # Optional: ask for model if not provided
    if model is None:
        click.echo("\nModel name (e.g., gpt-4, deepseek-chat, gpt-4-turbo)")
        model = click.prompt("Model", default="gpt-4")

    # Save configuration
    save_agent_config(api_key, base_url, model)

    click.echo("\n✅ Configuration saved!")
    click.echo(f"   Model: {model}")
    if base_url:
        click.echo(f"   Base URL: {base_url}")
    click.echo("   Stored locally only in ~/.deepxiv_agent_config.json")
    click.echo("\n💡 You can now use: deepxiv agent \"your question\"")


@main.command()
@click.option("--transport", "-t", default="stdio", type=click.Choice(["stdio"]),
              help="Transport type (default: stdio)")
def serve(transport):
    """Start the MCP server.

    Example:
        deepxiv serve
        deepxiv serve --transport stdio
    """
    try:
        from .mcp_server import create_server
    except ImportError:
        click.echo("MCP server requires the 'mcp' package. Install with: pip install deepxiv[mcp]", err=True)
        sys.exit(1)

    server = create_server()
    server.run(transport=transport)


@main.command(name="token")
@click.option("--token", "-t", default=None, envvar="DEEPXIV_TOKEN", help="API token (or set DEEPXIV_TOKEN env var)")
def show_token(token):
    """Show the current DEEPXIV token and support contact."""
    token = ensure_token(token)
    if not token:
        sys.exit(1)

    click.echo(f"Current DEEPXIV_TOKEN: {token}\n")
    click.echo("If you need a higher daily limit, email your name, email, and telephone to tommy@chien.io.")


@main.command()
@click.option("--token", "-t", default=None, envvar="DEEPXIV_TOKEN", help="API token")
def health(token):
    """Check API health and token validity.

    This command verifies:
    - API server connectivity
    - Token validity (if provided)
    - Free test papers availability
    """
    click.echo("🏥 Checking deepxiv API health...\n")

    # Check API connectivity
    click.echo("1️⃣  Checking API connectivity...")
    try:
        response = requests.get(f"{DEFAULT_BASE_URL}/api/docs", timeout=10)
        if response.status_code == 200:
            click.echo("   ✅ API server is reachable\n")
        else:
            click.echo(f"   ⚠️  API returned status {response.status_code}\n")
    except requests.exceptions.Timeout:
        click.echo("   ❌ API server is unreachable (timeout)\n")
        sys.exit(1)
    except requests.exceptions.ConnectionError:
        click.echo("   ❌ Cannot connect to API (connection error)\n")
        sys.exit(1)
    except Exception as e:
        click.echo(f"   ❌ Error: {e}\n")
        sys.exit(1)

    # Check token validity
    if token:
        click.echo("2️⃣  Checking token validity...")
        reader = Reader(token=token)
        try:
            # Try to access a free test paper
            result = reader.brief("2409.05591")
            if result:
                click.echo("   ✅ Token is valid\n")
            else:
                click.echo("   ⚠️  Token check inconclusive\n")
        except Exception as e:
            click.echo(f"   ❌ Token is invalid: {str(e)[:60]}\n")
            sys.exit(1)
    else:
        click.echo("2️⃣  Token not provided (skipped)\n")

    # Check free papers
    click.echo("3️⃣  Checking free test papers...")
    reader = Reader(token=token)
    test_papers = {
        "arxiv": "2409.05591",
        "pmc": "PMC544940"
    }

    try:
        brief = reader.brief(test_papers["arxiv"])
        if brief:
            click.echo(f"   ✅ arXiv test paper available: {test_papers['arxiv']}\n")
        else:
            click.echo(f"   ⚠️  Cannot access arXiv test paper\n")
    except Exception as e:
        click.echo(f"   ⚠️  arXiv test paper error: {str(e)[:40]}\n")

    click.echo("=" * 60)
    click.echo("✅ Health check completed!")
    click.echo("=" * 60)


@main.command()
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging")
def debug(verbose):
    """Print debug information and environment settings.

    Useful for troubleshooting configuration issues.
    """
    import logging

    click.echo("🐛 Debug Information\n")

    # Python and package info
    click.echo("System Information:")
    click.echo(f"  Python Version: {sys.version}")
    click.echo(f"  Platform: {sys.platform}\n")

    # deepxiv version
    from . import __version__
    click.echo(f"deepxiv-sdk Version: {__version__}\n")

    # Dependencies
    click.echo("Installed Features:")
    try:
        import mcp
        click.echo("  ✅ MCP Server support (mcp installed)")
    except ImportError:
        click.echo("  ❌ MCP Server support (install with: pip install deepxiv-sdk[mcp])")

    try:
        import langgraph
        click.echo("  ✅ Agent support (langgraph installed)")
    except ImportError:
        click.echo("  ❌ Agent support (install with: pip install deepxiv-sdk[agent])")

    try:
        import dotenv
        click.echo("  ✅ .env file support (python-dotenv installed)")
    except ImportError:
        click.echo("  ⚠️  .env file support (optional, install with: pip install python-dotenv)")

    click.echo()

    # Environment variables
    click.echo("Environment Variables:")
    deepxiv_token = os.environ.get("DEEPXIV_TOKEN")
    if deepxiv_token:
        click.echo(f"  ✅ DEEPXIV_TOKEN is set")
    else:
        click.echo(f"  ⚠️  DEEPXIV_TOKEN is not set (will auto-register on first use)")

    if os.environ.get("DEEPXIV_AGENT_API_KEY"):
        click.echo(f"  ✅ DEEPXIV_AGENT_API_KEY is set")
    else:
        click.echo(f"  ⚠️  DEEPXIV_AGENT_API_KEY is not set (required for agent)")

    click.echo()

    # Configuration files
    click.echo("Configuration Files:")
    home_env = Path.home() / ".env"
    if home_env.exists():
        click.echo(f"  ✅ ~/.env exists")
        if verbose:
            # Show non-secret values
            with open(home_env) as f:
                for line in f:
                    if "=" in line:
                        key, _ = line.split("=", 1)
                        if key.strip() and not any(secret in key for secret in ["TOKEN", "KEY", "SECRET"]):
                            click.echo(f"     {key.strip()}: (hidden)")
    else:
        click.echo(f"  ⚠️  ~/.env does not exist (tokens will be saved here on first use)")

    agent_config = Path.home() / ".deepxiv_agent_config.json"
    if agent_config.exists():
        click.echo(f"  ✅ Agent config exists at ~/.deepxiv_agent_config.json")
    else:
        click.echo(f"  ⚠️  Agent config does not exist (run 'deepxiv agent config' to create)")

    click.echo()

    # Enable logging if verbose
    if verbose:
        click.echo("Enabling verbose logging...\n")
        logging.basicConfig(level=logging.DEBUG)
        logger = logging.getLogger("deepxiv_sdk")
        logger.setLevel(logging.DEBUG)

        # Test API connectivity with logging
        click.echo("Making test API request with debug logging...\n")
        reader = Reader(token=deepxiv_token)
        try:
            result = reader.brief("2409.05591")
            click.echo("\n✅ Test request successful")
        except Exception as e:
            click.echo(f"\n❌ Test request failed: {e}")


@main.command()
@click.option("--days", type=click.Choice(["7", "14", "30"]), default="7",
              help="Time range: 7, 14, or 30 days (default: 7)")
@click.option("--limit", type=int, default=30,
              help="Maximum number of papers to return (default: 30, max: 100)")
@click.option("--output", "-o", "output_format", type=click.Choice(["text", "json"]),
              default="text", help="Output format (default: text)")
@click.option("--json", "json_output", is_flag=True, help="Shorthand for --output json")
def trending(days, limit, output_format, json_output):
    """Get trending arXiv papers.

    Shows the hottest papers from the last 7, 14, or 30 days based on
    social media mentions, views, and engagement.

    Examples:
        deepxiv trending                    # Last 7 days, 30 papers
        deepxiv trending --days 30          # Last 30 days
        deepxiv trending --limit 5          # Top 5 papers
        deepxiv trending --json             # JSON output
        deepxiv trending --days 14 --limit 10 --json
    """
    # If --json flag is used, override output_format
    if json_output:
        output_format = "json"

    reader = Reader()

    try:
        result = reader.trending(days=int(days), limit=min(limit, 100))

        if output_format == "json":
            click.echo(json.dumps(result, indent=2))
        else:
            # Text output
            papers = result.get("papers", [])

            if not papers:
                click.echo("ℹ️  No trending papers found for this period.")
                return

            click.echo(f"\n📊 Trending Papers (Last {days} Days)\n")
            click.echo(f"Generated: {result.get('generated_at', 'N/A')}")
            click.echo(f"Total trending papers available: {result.get('total', 0)}\n")
            click.echo("-" * 100)

            for paper in papers[:min(limit, 100)]:
                arxiv_id = paper.get("arxiv_id", "N/A")
                rank = paper.get("rank", "?")
                stats = paper.get("stats", {})
                views = stats.get("total_views", "0")
                likes = stats.get("total_likes", "0")
                mentions = stats.get("total_mentions", 0)

                click.echo(f"\n#{rank}: arXiv:{arxiv_id}")
                click.echo(f"  📈 Views: {views:>10} | 👍 Likes: {likes:>8} | 💬 Mentions: {mentions}")

                mentioned_by = paper.get("mentioned_by", [])
                if mentioned_by:
                    top_mention = mentioned_by[0]
                    click.echo(f"  👤 Mentioned by: {top_mention.get('name')} (@{top_mention.get('username')})")
                    click.echo(f"     Followers: {top_mention.get('followers', 'N/A'):,}")

            click.echo("\n" + "-" * 100 + "\n")

    except Exception as e:
        click.echo(f"❌ Error: {e}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
