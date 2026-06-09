import logging
import os
from typing import List, Optional

import fitz

logger = logging.getLogger(__name__)


class PDFPageExtractor:
    """Extract PDF pages into image files inside a configured working folder."""

    def __init__(
        self,
        working_folder: Optional[str] = None,
        image_format: str = "png",
        dpi: int = 200,
    ):
        self.working_folder = (
            working_folder
            or os.getenv("CONTENT_WORKING_FOLDER")
            or os.path.join(os.getcwd(), "working")
        )
        self.image_format = image_format.lower().strip(".")
        self.dpi = dpi

        if self.image_format not in {"png", "jpg", "jpeg"}:
            raise ValueError("image_format must be one of: png, jpg, jpeg")

        os.makedirs(self.working_folder, exist_ok=True)
        logger.info(
            "PDFPageExtractor initialized: working_folder='%s', format='%s', dpi=%s",
            self.working_folder,
            self.image_format,
            self.dpi,
        )

    def extract_pdf_to_images(
        self,
        pdf_path: str,
        output_subfolder: Optional[str] = None,
        prefix: Optional[str] = None,
    ) -> List[str]:
        """Extract every PDF page as one image file and return output image paths."""
        if not os.path.isfile(pdf_path):
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")

        pdf_basename = os.path.splitext(os.path.basename(pdf_path))[0]
        output_dir = self.working_folder
        if output_subfolder:
            output_dir = os.path.join(output_dir, output_subfolder)

        os.makedirs(output_dir, exist_ok=True)

        file_prefix = prefix or pdf_basename
        output_paths: List[str] = []

        logger.info("Extracting PDF pages from '%s' into '%s'", pdf_path, output_dir)
        with fitz.open(pdf_path) as doc:
            if doc.page_count == 0:
                logger.warning("PDF has no pages: %s", pdf_path)
                return []

            scale = self.dpi / 72.0
            matrix = fitz.Matrix(scale, scale)

            for page_index in range(doc.page_count):
                page = doc.load_page(page_index)
                pix = page.get_pixmap(matrix=matrix, alpha=False)
                output_name = f"{file_prefix}_page_{page_index + 1:03d}.{self.image_format}"
                output_path = os.path.join(output_dir, output_name)
                pix.save(output_path)
                output_paths.append(output_path)

        logger.info("Extracted %s pages from '%s'", len(output_paths), pdf_path)
        return output_paths


def extract_pdf_to_images(
    pdf_path: str,
    working_folder: Optional[str] = None,
    output_subfolder: Optional[str] = None,
    prefix: Optional[str] = None,
    image_format: str = "png",
    dpi: int = 200,
) -> List[str]:
    """Convenience function to extract all PDF pages into image files."""
    extractor = PDFPageExtractor(
        working_folder=working_folder,
        image_format=image_format,
        dpi=dpi,
    )
    return extractor.extract_pdf_to_images(
        pdf_path=pdf_path,
        output_subfolder=output_subfolder,
        prefix=prefix,
    )
