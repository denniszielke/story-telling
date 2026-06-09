import logging
import os
from typing import Dict, List, Optional

from .content_image_extractor import ContentImageExtractor
from .content_internet_extractor import load_prompt

logger = logging.getLogger(__name__)


PROMPT_FILES = {
    "case-study": "case-study-extraction.md",
    "methodology": "methodology_pattern_analysis.md",
    "concept": "methodology_pattern_analysis.md",
}

PROMPT_ALIASES = {
    "use case": "case-study",
    "use-case": "case-study",
    "method": "methodology",
}


class PresentationProcessor:
    """Process presentation images with overlapping sliding windows for context capture."""

    def __init__(
        self,
        image_extractor: Optional[ContentImageExtractor] = None,
        window_size: int = 5,
        overlap: int = 2,
        prompt_files: Optional[Dict[str, str]] = None,
    ):
        if window_size <= 0:
            raise ValueError("window_size must be > 0")
        if overlap < 0 or overlap >= window_size:
            raise ValueError("overlap must be >= 0 and < window_size")

        self.image_extractor = image_extractor or ContentImageExtractor()
        self.window_size = window_size
        self.overlap = overlap

        merged_prompt_files = dict(PROMPT_FILES)
        if prompt_files:
            merged_prompt_files.update(prompt_files)

        self._prompt_templates = self._load_prompt_templates(merged_prompt_files)

    def _load_prompt_templates(self, prompt_files: Dict[str, str]) -> Dict[str, str]:
        templates: Dict[str, str] = {}
        for key, prompt_file in prompt_files.items():
            templates[key.lower()] = load_prompt(prompt_file)
        return templates

    def _normalize_type(self, content_type: str) -> str:
        normalized = (content_type or "").strip().lower()
        return PROMPT_ALIASES.get(normalized, normalized)

    def _select_prompt(self, content_type: str) -> str:
        normalized_type = self._normalize_type(content_type)
        if normalized_type in self._prompt_templates:
            return self._prompt_templates[normalized_type]

        for key, prompt in self._prompt_templates.items():
            if normalized_type.startswith(key) or key in normalized_type:
                return prompt

        available = ", ".join(sorted(self._prompt_templates.keys()))
        raise ValueError(
            f"No prompt template found for content_type '{content_type}'. "
            f"Available content types: {available}"
        )

    def _collect_image_paths(self, folder_path: str) -> List[str]:
        if not os.path.isdir(folder_path):
            raise NotADirectoryError(f"Image folder not found: {folder_path}")

        supported_extensions = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff", ".tif"}
        image_paths = [
            os.path.join(folder_path, name)
            for name in sorted(os.listdir(folder_path))
            if os.path.splitext(name)[1].lower() in supported_extensions
        ]

        if not image_paths:
            raise ValueError(f"No supported image files found in folder: {folder_path}")

        return image_paths

    def _build_windows(self, total_items: int) -> List[List[int]]:
        step = self.window_size - self.overlap
        windows: List[List[int]] = []

        start = 0
        while start < total_items:
            end = min(start + self.window_size, total_items)
            windows.append(list(range(start, end)))
            if end == total_items:
                break
            start += step

        return windows

    def process_presentation(
        self,
        image_folder: str,
        content_type: str,
        description: str = "",
        window_size: Optional[int] = None,
        overlap: Optional[int] = None,
    ) -> Dict[str, object]:
        """Process presentation images in overlapping windows and return window-level extraction."""
        prompt_template = self._select_prompt(content_type)
        image_paths = self._collect_image_paths(image_folder)

        resolved_window = window_size if window_size is not None else self.window_size
        resolved_overlap = overlap if overlap is not None else self.overlap

        if resolved_window <= 0:
            raise ValueError("window_size must be > 0")
        if resolved_overlap < 0 or resolved_overlap >= resolved_window:
            raise ValueError("overlap must be >= 0 and < window_size")

        original_window_size = self.window_size
        original_overlap = self.overlap
        self.window_size = resolved_window
        self.overlap = resolved_overlap
        try:
            windows = self._build_windows(len(image_paths))
        finally:
            self.window_size = original_window_size
            self.overlap = original_overlap

        window_outputs: List[Dict[str, object]] = []
        previous_window_summary = ""

        logger.info(
            "Processing presentation '%s' with %s images, window_size=%s, overlap=%s",
            image_folder,
            len(image_paths),
            resolved_window,
            resolved_overlap,
        )

        for window_number, indices in enumerate(windows, start=1):
            window_image_paths = [image_paths[i] for i in indices]
            page_start = indices[0] + 1
            page_end = indices[-1] + 1

            # Window-aware instructions preserve cross-page context and continuity across overlaps.
            window_prompt = (
                f"{prompt_template}\n\n"
                "Additional instructions for sliding-window presentation analysis:\n"
                f"- This is window {window_number} of {len(windows)}.\n"
                f"- Analyze pages {page_start} to {page_end} (1-based index).\n"
                f"- Window size is {resolved_window} with overlap {resolved_overlap}.\n"
                "- Capture connections between pages and avoid isolated per-page summaries.\n"
                "- If a point continues from prior pages, preserve continuity in the output.\n"
                "- Include only information visible or inferable from these pages.\n"
            )
            if description:
                window_prompt += f"- Presentation context: {description}\n"
            if previous_window_summary:
                window_prompt += (
                    "- Prior overlapping window summary (use only for continuity, not as new evidence):\n"
                    f"{previous_window_summary}\n"
                )

            page_outputs: List[Dict[str, str]] = []
            for page_index, image_path in zip(indices, window_image_paths):
                extracted = self.image_extractor.describe_image(source=image_path, prompt=window_prompt)
                page_outputs.append(
                    {
                        "page_number": str(page_index + 1),
                        "image_path": image_path,
                        "extracted_content": extracted,
                    }
                )

            current_window_summary = "\n\n".join(
                f"Page {entry['page_number']}:\n{entry['extracted_content']}" for entry in page_outputs
            )
            previous_window_summary = current_window_summary[:4000]

            window_outputs.append(
                {
                    "window_number": window_number,
                    "page_start": page_start,
                    "page_end": page_end,
                    "image_paths": window_image_paths,
                    "pages": page_outputs,
                }
            )

        return {
            "image_folder": image_folder,
            "content_type": self._normalize_type(content_type),
            "window_size": resolved_window,
            "overlap": resolved_overlap,
            "window_count": len(window_outputs),
            "image_count": len(image_paths),
            "windows": window_outputs,
        }
