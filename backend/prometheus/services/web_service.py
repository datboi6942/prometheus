import httpx
import structlog
from typing import Dict, Any, Optional

logger = structlog.get_logger()

class WebService:
    """Fetches content from URLs for the agent to read documentation or API specs."""

    async def fetch(self, url: str, max_length: int = 50000) -> Dict[str, Any]:
        """Fetch the content of a URL."""
        logger.info("Fetching URL", url=url)
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as client:
                response = await client.get(url)
                response.raise_for_status()
                
                content = response.text
                if len(content) > max_length:
                    content = content[:max_length] + "\n\n... (content truncated)"
                
                return {
                    "success": True,
                    "url": url,
                    "status_code": response.status_code,
                    "content": content,
                    "content_type": response.headers.get("content-type", "unknown")
                }
        except httpx.HTTPStatusError as e:
            logger.error("HTTP error fetching URL", url=url, status=e.response.status_code)
            return {"success": False, "error": f"HTTP {e.response.status_code}: {e.response.reason_phrase}"}
        except Exception as e:
            logger.error("Failed to fetch URL", url=url, error=str(e))
            return {"success": False, "error": str(e)}
