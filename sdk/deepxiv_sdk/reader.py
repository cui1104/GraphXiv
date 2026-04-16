"""
Reader class for accessing the arXiv data service API.
Provides typed interface with robust error handling and logging.

Fork of deepxiv_sdk pointed at local backend (http://localhost:8000).
URL construction rewritten from query-param to path-param style to match
the local backend routes defined in app/api/routes/arxiv.py and
app/api/routes/pmc.py.
"""
import logging
import requests
import time
from typing import Dict, List, Optional, Any

# Configure logger
logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://localhost:8000"


class APIError(Exception):
    """Base exception for API errors."""
    pass


class AuthenticationError(APIError):
    """Raised when authentication fails (401, invalid token)."""
    pass


class BadRequestError(APIError):
    """Raised when the request is invalid (400)."""
    pass


class RateLimitError(APIError):
    """Raised when rate limit is exceeded (429)."""
    pass


class NotFoundError(APIError):
    """Raised when requested resource is not found (404)."""
    pass


class ServerError(APIError):
    """Raised when server returns 5xx error."""
    pass


class Reader:
    """Reader for accessing arXiv papers via the data service API.

    Provides comprehensive paper search, metadata retrieval, and content access.
    This fork points at a local backend (default: http://localhost:8000).

    URL construction uses path-param style to match the local backend routes:
      GET /arxiv/{arxiv_id}/head
      GET /arxiv/{arxiv_id}/brief
      GET /arxiv/{arxiv_id}/sections
      GET /arxiv/{arxiv_id}/full
      GET /arxiv/{arxiv_id}/references
      GET /arxiv/{arxiv_id}/cited_by
      GET /arxiv/{arxiv_id}/related
      GET /pmc/{pmc_id}/head
      GET /pmc/{pmc_id}/full
      GET /arxiv/search?q=&limit=&search_mode=

    Attributes:
        token: API token for authentication (optional for free papers)
        base_url: Base URL of the data service
        timeout: Request timeout in seconds (default: 60)
        max_retries: Maximum number of retry attempts (default: 3)
        retry_delay: Initial retry delay in seconds (default: 1)
    """

    def __init__(
        self,
        token: Optional[str] = None,
        base_url: str = DEFAULT_BASE_URL,
        timeout: int = 60,
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ) -> None:
        """
        Initialize the Reader.

        Args:
            token: API token for authentication (optional for free papers)
            base_url: Base URL of the data service (default: http://localhost:8000)
            timeout: Request timeout in seconds (default: 60)
            max_retries: Maximum number of retry attempts (default: 3)
            retry_delay: Initial retry delay in seconds (default: 1.0)
        """
        self.token = token
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        logger.debug(
            f"Reader initialized with base_url={self.base_url}, "
            f"token={'***' if token else 'None'}"
        )

    def _make_request(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        retry_count: int = 0,
    ) -> Optional[Dict[str, Any]]:
        """
        Make a GET request to the API with retry logic and comprehensive error handling.

        Args:
            url: Full URL to request
            params: Query parameters
            retry_count: Current retry attempt number (internal use)

        Returns:
            Response JSON or None if max retries exceeded

        Raises:
            BadRequestError: Invalid request parameters or malformed IDs (400)
            AuthenticationError: Invalid or expired token (401)
            RateLimitError: Daily limit reached (429)
            NotFoundError: Resource not found (404)
            ServerError: Server error (5xx)
            APIError: Other API errors
        """
        headers: Dict[str, str] = {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        try:
            logger.debug(f"Making request to {url} with params {params}")
            response = requests.get(
                url,
                params=params,
                headers=headers,
                timeout=self.timeout,
            )

            # Handle HTTP errors with appropriate exceptions
            if response.status_code == 400:
                logger.warning(f"Bad request to {url}: {response.text}")
                raise BadRequestError(
                    "Invalid request. Please check your arXiv/PMC ID or command arguments."
                )
            elif response.status_code == 401:
                logger.error("Authentication failed: Invalid or expired token")
                raise AuthenticationError(
                    "Invalid or expired token. Run 'deepxiv config' to set a valid token."
                )
            elif response.status_code == 404:
                logger.warning(f"Resource not found: {url}")
                raise NotFoundError(f"Paper not found. Check your arXiv/PMC ID.")
            elif response.status_code == 429:
                logger.warning("Rate limit exceeded")
                raise RateLimitError(
                    "Daily limit reached. Email tommy@chien.io for higher limits."
                )
            elif response.status_code >= 500:
                logger.error(f"Server error {response.status_code}: {response.text}")
                raise ServerError(f"Server error {response.status_code}")

            response.raise_for_status()
            if not response.content:
                logger.debug(f"Empty response body from {url}")
                return {}
            result = response.json()
            logger.debug(f"Successfully received response from {url}")
            return result

        except APIError:
            raise

        except requests.exceptions.Timeout as e:
            if retry_count < self.max_retries:
                wait_time = self.retry_delay * (2 ** retry_count)
                logger.warning(
                    f"Request timeout (attempt {retry_count + 1}/{self.max_retries}), "
                    f"retrying in {wait_time}s..."
                )
                time.sleep(wait_time)
                return self._make_request(url, params, retry_count + 1)
            else:
                logger.error(f"Request timeout after {self.max_retries} retries")
                raise APIError(
                    f"Request timed out after {self.max_retries} retries. "
                    "Check your internet connection or try again later."
                )

        except requests.exceptions.ConnectionError as e:
            if retry_count < self.max_retries:
                wait_time = self.retry_delay * (2 ** retry_count)
                logger.warning(
                    f"Connection error (attempt {retry_count + 1}/{self.max_retries}), "
                    f"retrying in {wait_time}s..."
                )
                time.sleep(wait_time)
                return self._make_request(url, params, retry_count + 1)
            else:
                logger.error(f"Connection error after {self.max_retries} retries")
                raise APIError(
                    f"Failed to connect to {url}. "
                    "Check your internet connection or try again later."
                )

        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP error {e.response.status_code}: {e}")
            raise APIError(f"HTTP error {e.response.status_code}: {str(e)}")

        except requests.exceptions.RequestException as e:
            logger.error(f"Request failed: {e}")
            raise APIError(f"Request failed: {str(e)}")

        except ValueError as e:
            logger.error(f"Failed to parse JSON response: {e}")
            raise APIError(f"Invalid response format: {str(e)}")

        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            raise APIError(f"Unexpected error: {str(e)}")

    # ========== arXiv Methods ==========

    def head(self, arxiv_id: str) -> Dict[str, Any]:
        """
        Get paper metadata (head information) for an arXiv paper.

        Args:
            arxiv_id: arXiv ID (e.g., "2409.05591", "2504.21776")

        Returns:
            Dictionary with paper head information including:
            - paper_id, arxiv_id, title, abstract, authors, tldr,
              year, venue, src_url, token_count, parse_source

        Raises:
            APIError: If the request fails
        """
        if not arxiv_id or not arxiv_id.strip():
            raise ValueError("arxiv_id cannot be empty")

        url = f"{self.base_url}/arxiv/{arxiv_id}/head"
        result = self._make_request(url)
        return result or {}

    def brief(self, arxiv_id: str) -> Dict[str, Any]:
        """
        Get brief paper information (concise summary for quick overview).

        Args:
            arxiv_id: arXiv ID (e.g., "2409.05591", "2504.21776")

        Returns:
            Dictionary with brief paper information (same shape as head)

        Raises:
            APIError: If the request fails
        """
        if not arxiv_id or not arxiv_id.strip():
            raise ValueError("arxiv_id cannot be empty")

        url = f"{self.base_url}/arxiv/{arxiv_id}/brief"
        result = self._make_request(url)
        return result or {}

    def sections(self, arxiv_id: str) -> Dict[str, Any]:
        """
        Get all sections for an arXiv paper (convenience method, returns raw response dict).

        Args:
            arxiv_id: arXiv ID (e.g., "2409.05591")

        Returns:
            Dictionary with paper_id, title, sections list, token_count

        Raises:
            APIError: If the request fails
        """
        if not arxiv_id or not arxiv_id.strip():
            raise ValueError("arxiv_id cannot be empty")

        url = f"{self.base_url}/arxiv/{arxiv_id}/sections"
        result = self._make_request(url)
        return result or {}

    def _match_section_name(self, arxiv_id: str, section_name: str) -> Optional[str]:
        """
        Match user input to actual section name via the sections endpoint.
        Uses case-insensitive partial match against the 'heading' field.

        Args:
            arxiv_id: arXiv ID
            section_name: User-provided section name (e.g., "Introduction")

        Returns:
            Matched section heading or None if not found
        """
        response = self.sections(arxiv_id)
        if not response or "sections" not in response:
            return None

        sections: List[Dict[str, Any]] = response.get("sections", [])
        section_lower = section_name.lower()

        # Build list of headings
        headings = [
            s.get("heading", "") if isinstance(s, dict) else str(s)
            for s in sections
        ]

        # Exact match first (case-insensitive)
        for heading in headings:
            if heading.lower() == section_lower:
                return heading

        # Partial match (heading contains query)
        for heading in headings:
            clean = heading.lower()
            # Strip leading numbering like "1. "
            if clean and clean[0].isdigit():
                clean = clean.lstrip("0123456789. ")
            if clean == section_lower or section_lower in clean:
                return heading

        logger.warning(
            f"Section '{section_name}' not found in paper {arxiv_id}. "
            f"Available sections: {', '.join(headings)}"
        )
        return None

    def section(self, arxiv_id: str, section_name: str) -> str:
        """
        Get a specific section content from a paper (client-side filter on sections endpoint).

        Args:
            arxiv_id: arXiv ID (e.g., "2409.05591")
            section_name: Name of the section (case-insensitive, partial match supported)

        Returns:
            Section text content as string

        Raises:
            ValueError: If section is not found
            APIError: If the request fails
        """
        if not arxiv_id or not arxiv_id.strip():
            raise ValueError("arxiv_id cannot be empty")
        if not section_name or not section_name.strip():
            raise ValueError("section_name cannot be empty")

        response = self.sections(arxiv_id)
        if not response or "sections" not in response:
            raise ValueError(f"No sections found for paper {arxiv_id}")

        sections: List[Dict[str, Any]] = response.get("sections", [])
        section_lower = section_name.lower()

        # Try exact match first
        for sec in sections:
            heading = sec.get("heading", "") if isinstance(sec, dict) else str(sec)
            if heading.lower() == section_lower:
                return sec.get("text", "") if isinstance(sec, dict) else ""

        # Try partial match
        for sec in sections:
            heading = sec.get("heading", "") if isinstance(sec, dict) else str(sec)
            clean = heading.lower()
            if clean and clean[0].isdigit():
                clean = clean.lstrip("0123456789. ")
            if section_lower in clean:
                return sec.get("text", "") if isinstance(sec, dict) else ""

        raise ValueError(f"Section '{section_name}' not found in paper {arxiv_id}")

    def full(self, arxiv_id: str) -> Dict[str, Any]:
        """
        Get the complete structured paper data (head + sections + citations + ref_entries).

        Args:
            arxiv_id: arXiv ID (e.g., "2409.05591")

        Returns:
            Complete structured JSON with all paper data

        Raises:
            APIError: If the request fails
        """
        if not arxiv_id or not arxiv_id.strip():
            raise ValueError("arxiv_id cannot be empty")

        url = f"{self.base_url}/arxiv/{arxiv_id}/full"
        result = self._make_request(url)
        return result or {}

    def raw(self, arxiv_id: str) -> Dict[str, Any]:
        """
        Alias for full(). Get the complete structured paper data.

        Args:
            arxiv_id: arXiv ID (e.g., "2409.05591")

        Returns:
            Complete structured JSON dict

        Raises:
            APIError: If the request fails
        """
        return self.full(arxiv_id)

    def json(self, arxiv_id: str) -> Dict[str, Any]:
        """
        Alias for full(). Get the complete structured JSON paper data.

        Args:
            arxiv_id: arXiv ID (e.g., "2409.05591")

        Returns:
            Complete structured JSON dict

        Raises:
            APIError: If the request fails
        """
        return self.full(arxiv_id)

    def references(self, arxiv_id: str) -> Dict[str, Any]:
        """
        Get outgoing references (citations) for an arXiv paper.

        Args:
            arxiv_id: arXiv ID (e.g., "2409.05591")

        Returns:
            Dictionary with paper_id and references list

        Raises:
            APIError: If the request fails
        """
        if not arxiv_id or not arxiv_id.strip():
            raise ValueError("arxiv_id cannot be empty")

        url = f"{self.base_url}/arxiv/{arxiv_id}/references"
        result = self._make_request(url)
        return result or {}

    def cited_by(self, arxiv_id: str) -> Dict[str, Any]:
        """
        Get papers that cite this arXiv paper.

        Args:
            arxiv_id: arXiv ID (e.g., "2409.05591")

        Returns:
            Dictionary with paper_id and cited_by list

        Raises:
            APIError: If the request fails
        """
        if not arxiv_id or not arxiv_id.strip():
            raise ValueError("arxiv_id cannot be empty")

        url = f"{self.base_url}/arxiv/{arxiv_id}/cited_by"
        result = self._make_request(url)
        return result or {}

    def related(self, arxiv_id: str, limit: int = 20) -> Dict[str, Any]:
        """
        Get related papers (co-cited papers) for an arXiv paper.

        Args:
            arxiv_id: arXiv ID (e.g., "2409.05591")
            limit: Maximum number of related papers to return (default: 20)

        Returns:
            Dictionary with paper_id and related list

        Raises:
            APIError: If the request fails
        """
        if not arxiv_id or not arxiv_id.strip():
            raise ValueError("arxiv_id cannot be empty")

        url = f"{self.base_url}/arxiv/{arxiv_id}/related"
        result = self._make_request(url, params={"limit": limit})
        return result or {}

    def search(
        self,
        query: str,
        size: int = 10,
        offset: int = 0,
        search_mode: str = "hybrid",
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Search for papers using the local backend search endpoint.

        Args:
            query: Search query string
            size: Number of results to return (default: 10, max: 100)
            offset: Result offset for pagination (default: 0)
            search_mode: Search mode - "bm25", "vector", or "hybrid" (default: "hybrid")

        Returns:
            Dictionary with 'total' and 'results' fields

        Raises:
            ValueError: If query is empty or size/offset are invalid
            APIError: If the request fails
        """
        if not query or not query.strip():
            raise ValueError("Query cannot be empty")
        if size < 1 or size > 100:
            raise ValueError("Size must be between 1 and 100")
        if offset < 0:
            raise ValueError("Offset must be non-negative")

        # NOTE: search route is /arxiv/search (per routes/search.py mounted at "/" in main.py)
        url = f"{self.base_url}/arxiv/search"
        params: Dict[str, Any] = {
            "q": query,
            "limit": size,
            "search_mode": search_mode,
        }

        result = self._make_request(url, params=params)
        logger.info(f"Search for '{query}' returned {(result or {}).get('total', 0)} results")
        return result or {"total": 0, "results": []}

    # ========== PMC (PubMed Central) Methods ==========

    def pmc_head(self, pmc_id: str) -> Dict[str, Any]:
        """
        Get PMC paper metadata (title, abstract, authors, categories, publication date).

        Args:
            pmc_id: PMC ID (e.g., "PMC544940", "PMC514704")

        Returns:
            Dictionary with PMC paper metadata

        Raises:
            APIError: If the request fails
        """
        if not pmc_id or not pmc_id.strip():
            raise ValueError("pmc_id cannot be empty")

        url = f"{self.base_url}/pmc/{pmc_id}/head"
        result = self._make_request(url)
        return result or {}

    def pmc_full(self, pmc_id: str) -> Dict[str, Any]:
        """
        Get the complete PMC paper in structured JSON format with full content and metadata.

        Args:
            pmc_id: PMC ID (e.g., "PMC544940", "PMC514704")

        Returns:
            Complete structured JSON with all PMC paper data

        Raises:
            APIError: If the request fails
        """
        if not pmc_id or not pmc_id.strip():
            raise ValueError("pmc_id cannot be empty")

        url = f"{self.base_url}/pmc/{pmc_id}/full"
        result = self._make_request(url)
        return result or {}

    def pmc_json(self, pmc_id: str) -> Dict[str, Any]:
        """Alias for pmc_full(). Get the complete PMC paper in JSON format."""
        return self.pmc_full(pmc_id)

    # ========== Stub Methods (Not Available Against Local Backend) ==========
    # These methods require the upstream data.rag.ac.cn service.
    # They are preserved to maintain the API surface but raise NotImplementedError.

    def websearch(self, query: str, **kwargs) -> Dict[str, Any]:
        """Not available against local backend — requires upstream data.rag.ac.cn service."""
        raise NotImplementedError(
            "websearch() is not available against this backend. "
            "It requires the upstream data.rag.ac.cn service."
        )

    def semantic_scholar(self, semantic_scholar_id: str, **kwargs) -> Dict[str, Any]:
        """Not available against local backend — requires upstream data.rag.ac.cn service."""
        raise NotImplementedError(
            "semantic_scholar() is not available against this backend. "
            "It requires the upstream data.rag.ac.cn service."
        )

    def trending(self, days: int = 7, limit: int = 30, **kwargs) -> Dict[str, Any]:
        """Not available against local backend — requires upstream data.rag.ac.cn service."""
        raise NotImplementedError(
            "trending() is not available against this backend. "
            "It requires the upstream data.rag.ac.cn service."
        )

    def biomed_search(self, query: str, **kwargs) -> Dict[str, Any]:
        """Not available against local backend — requires upstream data.rag.ac.cn service."""
        raise NotImplementedError(
            "biomed_search() is not available against this backend. "
            "It requires the upstream data.rag.ac.cn service."
        )

    def biomed_data(self, source_id: str, **kwargs) -> Dict[str, Any]:
        """Not available against local backend — requires upstream data.rag.ac.cn service."""
        raise NotImplementedError(
            "biomed_data() is not available against this backend. "
            "It requires the upstream data.rag.ac.cn service."
        )

    def social_impact(self, arxiv_id: str, **kwargs) -> Optional[Dict[str, Any]]:
        """Not available against local backend — requires upstream data.rag.ac.cn service."""
        raise NotImplementedError(
            "social_impact() is not available against this backend. "
            "It requires the upstream data.rag.ac.cn service."
        )

    def markdown(self, arxiv_id: str, **kwargs) -> str:
        """Not available against local backend — requires upstream data.rag.ac.cn service."""
        raise NotImplementedError(
            "markdown() is not available against this backend. "
            "It requires the upstream data.rag.ac.cn service."
        )

    def preview(self, arxiv_id: str, **kwargs) -> Dict[str, Any]:
        """Not available against local backend — requires upstream data.rag.ac.cn service."""
        raise NotImplementedError(
            "preview() is not available against this backend. "
            "It requires the upstream data.rag.ac.cn service."
        )
