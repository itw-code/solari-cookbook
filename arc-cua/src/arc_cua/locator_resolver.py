"""Invariant Selector Cache & Self-Healing Resolver for Phase 2 Reflex.

Implements Task 2.2:
- Ingests enriched AXNode metadata from Phase 1 (css_selector, xpath, backend_dom_id, aria_label, text, bbox).
- Implements a resilient 6-tier fallback resolution chain:
  1. data-testid / backend_dom_id
  2. Exact CSS selector
  3. XPath
  4. Role + Aria Label / Name
  5. Text content match
  6. Bounding Box (fallback only)
- In-memory LRU cache mapping semantic goals to successful locator strategies with self-healing.
- Returns ResolvedLocator object with chosen strategy, locator expression, and confidence score.
"""

from __future__ import annotations

import collections
import dataclasses
import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple, Union

from .cdp_extractor import AXNode, SanitizedAXTree

logger = logging.getLogger("arc_cua.locator_resolver")


class LocatorResolutionError(Exception):
    """Raised when all strategies in the fallback resolution chain fail."""
    pass


@dataclasses.dataclass
class ResolvedLocator:
    """Output of locator resolution containing selector and strategy metadata."""
    selector: str
    strategy: str  # "data_testid", "backend_dom_id", "css", "xpath", "role_aria", "text", "bbox", "cached"
    confidence: float  # [0.0 - 1.0]
    target_node: Optional[AXNode] = None
    cached: bool = False
    resolution_latency_ms: float = 0.0
    metadata: Dict[str, Any] = dataclasses.field(default_factory=dict)


class SelectorLRUCache:
    """Bounded Least-Recently-Used (LRU) cache for semantic locator strategies."""

    def __init__(self, maxsize: int = 500):
        self.maxsize = maxsize
        self._cache: collections.OrderedDict[str, Tuple[str, str, float]] = collections.OrderedDict()

    def get(self, key: str) -> Optional[Tuple[str, str, float]]:
        """Retrieve (selector, strategy, confidence) and mark as recently used."""
        if key not in self._cache:
            return None
        self._cache.move_to_end(key)
        return self._cache[key]

    def put(self, key: str, selector: str, strategy: str, confidence: float) -> None:
        """Store or update selector strategy in LRU cache."""
        if key in self._cache:
            self._cache.move_to_end(key)
        self._cache[key] = (selector, strategy, confidence)
        if len(self._cache) > self.maxsize:
            self._cache.popitem(last=False)

    def invalidate(self, key: str) -> None:
        """Evict an invalid or drifted entry from the cache."""
        self._cache.pop(key, None)

    def clear(self) -> None:
        """Clear all cached entries."""
        self._cache.clear()

    def __len__(self) -> int:
        return len(self._cache)


class LocatorResolver:
    """Self-healing selector resolver implementing 6-tier fallback and invariant caching."""

    STRATEGY_CONFIDENCE: Dict[str, float] = {
        "data_testid": 1.0,
        "backend_dom_id": 0.98,
        "cached": 0.95,
        "css": 0.90,
        "xpath": 0.80,
        "role_aria": 0.70,
        "text": 0.60,
        "bbox": 0.40,
    }

    def __init__(self, cache_size: int = 500):
        self.cache = SelectorLRUCache(maxsize=cache_size)

    def resolve(
        self,
        node_or_index: Union[AXNode, int, str],
        page: Any = None,
        tree: Optional[SanitizedAXTree] = None,
        goal: Optional[str] = None,
    ) -> ResolvedLocator:
        """Resolve a locator using cached strategy or the 6-tier fallback chain.

        Args:
            node_or_index: An AXNode, action index (int), or selector/query string.
            page: Optional Playwright Page object to verify locator presence.
            tree: Optional SanitizedAXTree to locate node if index or string is provided.
            goal: Optional semantic goal string for caching.

        Returns:
            ResolvedLocator containing selector string, strategy, and confidence.
        """
        start_time = time.perf_counter()

        # Step 1: Normalize target into an AXNode if possible
        node: Optional[AXNode] = None
        if isinstance(node_or_index, AXNode):
            node = node_or_index
        elif isinstance(node_or_index, int) and tree is not None:
            node = self._find_node_by_index(tree, node_or_index)
        elif isinstance(node_or_index, str) and tree is not None:
            node = self._find_node_by_query(tree, node_or_index)

        # Generate cache key
        cache_key = self._generate_cache_key(node, node_or_index, goal)

        # Step 2: Invariant Cache Check (with self-healing fallback)
        if cache_key:
            cached_val = self.cache.get(cache_key)
            if cached_val:
                cached_selector, cached_strat, cached_conf = cached_val
                # Test whether cached selector works on the live page
                if self._verify_locator_on_page(page, cached_selector):
                    latency = (time.perf_counter() - start_time) * 1000.0
                    return ResolvedLocator(
                        selector=cached_selector,
                        strategy=cached_strat,
                        confidence=cached_conf,
                        target_node=node,
                        cached=True,
                        resolution_latency_ms=latency,
                        metadata={"cache_key": cache_key},
                    )
                else:
                    # Self-healing: Invalidate drifted cache entry
                    logger.info(f"Self-healing: Evicting drifted cache entry for key '{cache_key}'")
                    self.cache.invalidate(cache_key)

        # If we have a raw string that didn't match an AXNode and page verifies it, use it
        if node is None and isinstance(node_or_index, str):
            if self._verify_locator_on_page(page, node_or_index):
                latency = (time.perf_counter() - start_time) * 1000.0
                return ResolvedLocator(
                    selector=node_or_index,
                    strategy="css" if not node_or_index.startswith("//") else "xpath",
                    confidence=0.85,
                    target_node=None,
                    cached=False,
                    resolution_latency_ms=latency,
                )

        if node is None:
            raise LocatorResolutionError(
                f"Cannot resolve locator: node target '{node_or_index}' not found in AXTree"
            )

        # Step 3: Execute Fallback Resolution Chain
        resolved = self._execute_fallback_chain(node, page)
        resolved.resolution_latency_ms = (time.perf_counter() - start_time) * 1000.0

        # Step 4: Populate LRU cache for future invariant hits
        if cache_key and resolved.confidence >= 0.60:
            self.cache.put(
                cache_key,
                resolved.selector,
                resolved.strategy,
                resolved.confidence,
            )

        return resolved

    def _execute_fallback_chain(self, node: AXNode, page: Any) -> ResolvedLocator:
        """Evaluate the 6 fallback resolution tiers in order."""

        # Tier 1: data-testid / backend_dom_id
        # Check test-id in css_selector or attributes
        test_id_selector = self._derive_testid_selector(node)
        if test_id_selector and self._verify_locator_on_page(page, test_id_selector):
            return ResolvedLocator(
                selector=test_id_selector,
                strategy="data_testid",
                confidence=self.STRATEGY_CONFIDENCE["data_testid"],
                target_node=node,
            )

        if node.backend_dom_id is not None:
            dom_id_sel = f"[data-backend-id='{node.backend_dom_id}']"
            if self._verify_locator_on_page(page, dom_id_sel):
                return ResolvedLocator(
                    selector=dom_id_sel,
                    strategy="backend_dom_id",
                    confidence=self.STRATEGY_CONFIDENCE["backend_dom_id"],
                    target_node=node,
                )

        # Tier 2: Exact CSS selector
        if node.css_selector and self._verify_locator_on_page(page, node.css_selector):
            return ResolvedLocator(
                selector=node.css_selector,
                strategy="css",
                confidence=self.STRATEGY_CONFIDENCE["css"],
                target_node=node,
            )

        # Tier 3: XPath
        if node.xpath and self._verify_locator_on_page(page, node.xpath):
            return ResolvedLocator(
                selector=node.xpath,
                strategy="xpath",
                confidence=self.STRATEGY_CONFIDENCE["xpath"],
                target_node=node,
            )

        # Tier 4: Role + Aria Label / Name
        role_aria_sel = self._derive_role_aria_selector(node)
        if role_aria_sel and self._verify_locator_on_page(page, role_aria_sel):
            return ResolvedLocator(
                selector=role_aria_sel,
                strategy="role_aria",
                confidence=self.STRATEGY_CONFIDENCE["role_aria"],
                target_node=node,
            )

        # Tier 5: Text content match
        text_sel = self._derive_text_selector(node)
        if text_sel and self._verify_locator_on_page(page, text_sel):
            return ResolvedLocator(
                selector=text_sel,
                strategy="text",
                confidence=self.STRATEGY_CONFIDENCE["text"],
                target_node=node,
            )

        # Tier 6: Bounding Box (fallback only)
        if node.bbox:
            x, y, w, h = node.bbox
            cx = x + w / 2.0
            cy = y + h / 2.0
            coords_sel = f"coords:{cx:.1f},{cy:.1f}"
            return ResolvedLocator(
                selector=coords_sel,
                strategy="bbox",
                confidence=self.STRATEGY_CONFIDENCE["bbox"],
                target_node=node,
                metadata={"bbox": list(node.bbox), "center": (cx, cy)},
            )

        # If page is None (offline / static resolution mode), return best available candidate
        if page is None:
            return self._offline_best_candidate(node)

        raise LocatorResolutionError(
            f"All 6 fallback locator strategies failed for node role='{node.role}' name='{node.name}'"
        )

    def _offline_best_candidate(self, node: AXNode) -> ResolvedLocator:
        """Select best candidate when running in offline mode without live page verification."""
        test_id_sel = self._derive_testid_selector(node)
        if test_id_sel:
            return ResolvedLocator(selector=test_id_sel, strategy="data_testid", confidence=1.0, target_node=node)
        if node.css_selector:
            return ResolvedLocator(selector=node.css_selector, strategy="css", confidence=0.90, target_node=node)
        if node.xpath:
            return ResolvedLocator(selector=node.xpath, strategy="xpath", confidence=0.80, target_node=node)
        role_sel = self._derive_role_aria_selector(node)
        if role_sel:
            return ResolvedLocator(selector=role_sel, strategy="role_aria", confidence=0.70, target_node=node)
        text_sel = self._derive_text_selector(node)
        if text_sel:
            return ResolvedLocator(selector=text_sel, strategy="text", confidence=0.60, target_node=node)
        if node.bbox:
            cx = node.bbox[0] + node.bbox[2] / 2.0
            cy = node.bbox[1] + node.bbox[3] / 2.0
            return ResolvedLocator(
                selector=f"coords:{cx:.1f},{cy:.1f}",
                strategy="bbox",
                confidence=0.40,
                target_node=node,
            )
        raise LocatorResolutionError(f"No usable locator metadata found on node {node.name}")

    def _derive_testid_selector(self, node: AXNode) -> Optional[str]:
        """Extract data-testid from css selector or aria label."""
        if node.css_selector:
            match = re.search(r'\[data-testid=["\']?([^"\'\]]+)["\']?\]', node.css_selector)
            if match:
                return f'[data-testid="{match.group(1)}"]'
        if node.name and node.name.startswith("test-"):
            return f'[data-testid="{node.name}"]'
        return None

    def _derive_role_aria_selector(self, node: AXNode) -> Optional[str]:
        """Synthesize resilient role + aria label selector."""
        label = node.aria_label or node.name
        if not label:
            return None
        safe_label = label.replace('"', '\\"')
        role_lower = node.role.lower()
        if role_lower in ("button", "link", "checkbox", "tab", "menuitem"):
            return f'[role="{role_lower}"][aria-label="{safe_label}"]'
        return f'[aria-label="{safe_label}"]'

    def _derive_text_selector(self, node: AXNode) -> Optional[str]:
        """Synthesize text content selector."""
        txt = node.text or node.name
        if not txt:
            return None
        clean_text = txt.strip()
        if len(clean_text) > 40:
            clean_text = clean_text[:40]
        safe_txt = clean_text.replace('"', '\\"')
        return f'text="{safe_txt}"'

    def _verify_locator_on_page(self, page: Any, selector: str) -> bool:
        """Check if selector resolves to at least one element on page."""
        if page is None:
            # If no page provided, assume valid candidate syntax
            return True

        if selector.startswith("coords:"):
            return True

        try:
            loc = page.locator(selector)
            if hasattr(loc, "count"):
                return loc.count() > 0
            if hasattr(loc, "is_visible"):
                return loc.is_visible()
            return True
        except Exception:
            return False

    def _generate_cache_key(
        self,
        node: Optional[AXNode],
        node_or_index: Union[AXNode, int, str],
        goal: Optional[str],
    ) -> Optional[str]:
        """Generate consistent cache key from goal, node, or index."""
        if goal:
            return f"goal:{goal.strip().lower()}"
        if node:
            key_parts = [node.role]
            if node.name:
                key_parts.append(node.name)
            if node.index is not None:
                key_parts.append(f"#{node.index}")
            return ":".join(key_parts)
        if isinstance(node_or_index, (int, str)):
            return f"target:{node_or_index}"
        return None

    def _find_node_by_index(self, tree: SanitizedAXTree, action_index: int) -> Optional[AXNode]:
        """Lookup node in tree by action index [#N]."""
        # First check action_index_map
        if action_index in tree.action_index_map:
            item = tree.action_index_map[action_index]
            bbox_val = tuple(item["bbox"]) if item.get("bbox") else None
            return AXNode(
                index=action_index,
                role=item.get("role", "button"),
                name=item.get("name", ""),
                value=item.get("value"),
                description=item.get("description"),
                is_actionable=True,
                states=item.get("states", []),
                backend_dom_id=item.get("backend_dom_id"),
                css_selector=item.get("css"),
                xpath=item.get("xpath"),
                text=item.get("text"),
                aria_label=item.get("aria_label"),
                bbox=bbox_val,  # type: ignore
            )
        return None

    def _find_node_by_query(self, tree: SanitizedAXTree, query: str) -> Optional[AXNode]:
        """Search tree by name or selector."""
        q_lower = query.lower()
        for idx, item in tree.action_index_map.items():
            name = (item.get("name") or "").lower()
            css = (item.get("css") or "").lower()
            if q_lower in name or q_lower == css or query == str(idx):
                return self._find_node_by_index(tree, idx)
        return None
