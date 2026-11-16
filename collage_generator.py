from pathlib import Path
from typing import Callable

from PIL import (
    Image,
    ImageDraw,
    ImageFilter,
    ImageFont,
)


CANVAS_WIDTH = 1080
CANVAS_HEIGHT = 1920

BACKGROUND_COLOR = (0, 0, 0)
TEXT_COLOR = (255, 255, 255)
TEXT_SHADOW_COLOR = (0, 0, 0)

OUTER_MARGIN = 28
COLUMN_GAP = 30
ROW_GAP = 42

HEADER_TOP = 24
HEADER_HEIGHT = 105
CONTENT_TOP = 155
CONTENT_BOTTOM = 1885

STAR_SPACING = 8


def load_font(
    size: int,
    bold: bool = False,
):
    """Load a scalable font on Windows, Linux, or Docker."""

    if bold:
        candidates = [
            Path("assets/DejaVuSans-Bold.ttf"),
            Path("C:/Windows/Fonts/arialbd.ttf"),
            Path("C:/Windows/Fonts/segoeuib.ttf"),
            Path(
                "/usr/share/fonts/truetype/"
                "dejavu/DejaVuSans-Bold.ttf"
            ),
        ]

    else:
        candidates = [
            Path("assets/DejaVuSans.ttf"),
            Path("C:/Windows/Fonts/arial.ttf"),
            Path("C:/Windows/Fonts/segoeui.ttf"),
            Path(
                "/usr/share/fonts/truetype/"
                "dejavu/DejaVuSans.ttf"
            ),
        ]

    for font_path in candidates:
        if font_path.exists():
            return ImageFont.truetype(
                str(font_path),
                size=size,
            )

    raise FileNotFoundError(
        "No scalable font was found. Add "
        "DejaVuSans.ttf and "
        "DejaVuSans-Bold.ttf to assets/."
    )


def determine_grid(
    number_of_books: int,
) -> tuple[int, int]:
    """Choose a readable cover grid."""

    if number_of_books <= 1:
        return 1, 1

    if number_of_books == 2:
        return 2, 1

    if number_of_books <= 4:
        return 2, 2

    if number_of_books <= 6:
        return 3, 2

    if number_of_books <= 9:
        return 3, 3

    if number_of_books <= 12:
        return 4, 3

    columns = 4
    rows = (
        number_of_books + columns - 1
    ) // columns

    return columns, rows


def get_review_settings(
    columns: int,
    rows: int,
) -> tuple[int, int]:
    """
    Return review-area height and preferred font size.

    Four-column layouts omit reviews because each column is too narrow.
    """

    if columns >= 4:
        return 0, 0

    if rows == 1:
        return 300, 34

    if rows == 2:
        return 180, 28

    return 120, 23


def resize_to_fit(
    image: Image.Image,
    maximum_width: int,
    maximum_height: int,
) -> Image.Image:
    """Resize an image without changing its aspect ratio."""

    width, height = image.size

    scale = min(
        maximum_width / width,
        maximum_height / height,
    )

    new_width = max(
        1,
        round(width * scale),
    )

    new_height = max(
        1,
        round(height * scale),
    )

    return image.resize(
        (new_width, new_height),
        Image.Resampling.LANCZOS,
    )


def measure_text_width(
    draw: ImageDraw.ImageDraw,
    text: str,
    font,
) -> int:
    """Measure rendered text width."""

    box = draw.textbbox(
        (0, 0),
        text,
        font=font,
    )

    return box[2] - box[0]


def get_line_height(
    draw: ImageDraw.ImageDraw,
    font,
) -> int:
    """Measure a representative text line."""

    box = draw.textbbox(
        (0, 0),
        "Ag",
        font=font,
    )

    return box[3] - box[1]


def add_ellipsis(
    draw: ImageDraw.ImageDraw,
    text: str,
    font,
    maximum_width: int,
) -> str:
    """Shorten one line until an ellipsis fits."""

    shortened = text.rstrip(
        " ,.;:-"
    )

    while shortened:
        candidate = shortened + "…"

        if (
            measure_text_width(
                draw,
                candidate,
                font,
            )
            <= maximum_width
        ):
            return candidate

        shortened = shortened[:-1].rstrip()

    return "…"


def wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font,
    maximum_width: int,
    maximum_lines: int,
) -> list: 
    """Wrap review text and truncate safely."""

    normalized_text = " ".join(
        text.split()
    )

    if not normalized_text:
        return []

    words = normalized_text.split(" ")
    lines = []
    current_line = ""
    consumed_words = 0

    for word in words:
        candidate = (
            f"{current_line} {word}".strip()
        )

        if (
            measure_text_width(
                draw,
                candidate,
                font,
            )
            <= maximum_width
        ):
            current_line = candidate
            consumed_words += 1
            continue

        if current_line:
            lines.append(current_line)

        current_line = word
        consumed_words += 1

        if len(lines) >= maximum_lines:
            break

    if (
        current_line
        and len(lines) < maximum_lines
    ):
        lines.append(current_line)

    all_text_was_used = (
        consumed_words >= len(words)
    )

    if (
        not all_text_was_used
        and lines
    ):
        lines[-1] = add_ellipsis(
            draw=draw,
            text=lines[-1],
            font=font,
            maximum_width=maximum_width,
        )

    return lines[:maximum_lines]


def fit_review_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    maximum_width: int,
    maximum_height: int,
    preferred_font_size: int,
) -> tuple[object, list[str], int]:
    """
    Find a readable font and wrapping that fits the review area.

    The minimum is 18 px. If the complete review cannot fit, the final
    visible line receives an ellipsis.
    """

    if not text or maximum_height <= 0:
        return None, [], 0

    line_spacing = 8

    for font_size in range(
        preferred_font_size,
        17,
        -2,
    ):
        font = load_font(
            size=font_size,
            bold=True,
        )

        line_height = get_line_height(
            draw,
            font,
        )

        maximum_lines = max(
            1,
            (
                maximum_height
                + line_spacing
            )
            // (
                line_height
                + line_spacing
            ),
        )

        lines = wrap_text(
            draw=draw,
            text=text,
            font=font,
            maximum_width=maximum_width,
            maximum_lines=maximum_lines,
        )

        rendered_height = (
            len(lines) * line_height
            + max(
                0,
                len(lines) - 1,
            )
            * line_spacing
        )

        if rendered_height <= maximum_height:
            return font, lines, line_height

    font = load_font(
        size=18,
        bold=True,
    )

    line_height = get_line_height(
        draw,
        font,
    )

    maximum_lines = max(
        1,
        (
            maximum_height
            + line_spacing
        )
        // (
            line_height
            + line_spacing
        ),
    )

    lines = wrap_text(
        draw=draw,
        text=text,
        font=font,
        maximum_width=maximum_width,
        maximum_lines=maximum_lines,
    )

    return font, lines, line_height


def draw_centered_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    center_x: int,
    y: int,
    font,
    shadow_offset: int = 2,
) -> None:
    """Draw centred white text with a black shadow."""

    width = measure_text_width(
        draw,
        text,
        font,
    )

    x = round(center_x - width / 2)

    draw.text(
        (
            x + shadow_offset,
            y + shadow_offset,
        ),
        text,
        font=font,
        fill=TEXT_SHADOW_COLOR,
    )

    draw.text(
        (x, y),
        text,
        font=font,
        fill=TEXT_COLOR,
    )


def load_star_image() -> Image.Image:
    """Load the project star image."""

    star_path = Path("assets/star.png")

    if not star_path.exists():
        raise FileNotFoundError(
            f"Star image was not found at "
            f"{star_path}."
        )

    return Image.open(
        star_path
    ).convert("RGBA")


def draw_rating(
    collage: Image.Image,
    star_image: Image.Image,
    rating: float,
    cell_x: int,
    available_width: int,
    y: int,
    star_size: int,
) -> None:
    """Draw full and half stars centred within one cell."""

    rating = max(
        0.0,
        min(5.0, float(rating)),
    )

    full_stars = int(rating)

    has_half_star = (
        rating - full_stars
    ) >= 0.25

    displayed_stars = (
        full_stars
        + int(has_half_star)
    )

    if displayed_stars == 0:
        return

    resized_star = star_image.resize(
        (star_size, star_size),
        Image.Resampling.LANCZOS,
    )

    total_width = (
        displayed_stars * star_size
        + max(
            0,
            displayed_stars - 1,
        )
        * STAR_SPACING
    )

    star_x = (
        cell_x
        + (
            available_width
            - total_width
        )
        // 2
    )

    for star_number in range(full_stars):
        x = (
            star_x
            + star_number
            * (
                star_size
                + STAR_SPACING
            )
        )

        collage.paste(
            resized_star,
            (x, y),
            resized_star,
        )

    if has_half_star:
        x = (
            star_x
            + full_stars
            * (
                star_size
                + STAR_SPACING
            )
        )

        half_width = max(
            1,
            star_size // 2,
        )

        half_star = resized_star.crop(
            (
                0,
                0,
                half_width,
                star_size,
            )
        )

        collage.paste(
            half_star,
            (x, y),
            half_star,
        )


def load_book_images(
    books,
    cover_path_function: Callable,
):
    """Load available cover images and preserve matching book records."""

    loaded = []

    for book in books:
        cover_path = cover_path_function(
            book
        )

        if not cover_path.exists():
            print(
                f"Missing cover for "
                f"'{book.title}' "
                f"({book.book_id})."
            )

            continue

        try:
            with Image.open(
                cover_path
            ) as source_image:
                image = source_image.convert(
                    "RGBA"
                )

            loaded.append(
                (book, image)
            )

        except Exception as error:
            print(
                f"Could not load cover for "
                f"'{book.title}': {error}"
            )

    return loaded


def create_collage(
    books,
    cover_path_function: Callable,
    output_path: Path,
    header_text: str,
) -> Path | None:
    """Create a 1080 × 1920 Instagram Story collage."""

    loaded_books = load_book_images(
        books,
        cover_path_function,
    )

    if not loaded_books:
        print(
            "No valid cover images were found "
            "for the collage."
        )

        return None

    number_of_books = len(
        loaded_books
    )

    columns, rows = determine_grid(
        number_of_books
    )

    review_height, review_font_size = (
        get_review_settings(
            columns=columns,
            rows=rows,
        )
    )

    available_width = (
        CANVAS_WIDTH
        - 2 * OUTER_MARGIN
        - (
            columns - 1
        )
        * COLUMN_GAP
    )

    cell_width = (
        available_width // columns
    )

    total_content_height = (
        CONTENT_BOTTOM
        - CONTENT_TOP
    )

    cell_height = (
        total_content_height
        - (
            rows - 1
        )
        * ROW_GAP
    ) // rows

    review_top_gap = (
        28 if review_height else 0
    )

    cover_area_height = (
        cell_height
        - review_height
        - review_top_gap
    )

    cover_area_height = max(
        100,
        cover_area_height,
    )

    resized_items = []

    for book, image in loaded_books:
        resized_image = resize_to_fit(
            image=image,
            maximum_width=cell_width,
            maximum_height=cover_area_height,
        )

        resized_items.append(
            (book, resized_image)
        )

    collage = Image.new(
        "RGB",
        (
            CANVAS_WIDTH,
            CANVAS_HEIGHT,
        ),
        BACKGROUND_COLOR,
    )

    draw = ImageDraw.Draw(collage)

    header_font = load_font(
        size=64,
        bold=True,
    )

    draw_centered_text(
        draw=draw,
        text=header_text,
        center_x=CANVAS_WIDTH // 2,
        y=HEADER_TOP,
        font=header_font,
        shadow_offset=2,
    )

    star_image = load_star_image()

    for index, (
        book,
        image,
    ) in enumerate(resized_items):
        row = index // columns
        column = index % columns

        cell_x = (
            OUTER_MARGIN
            + column
            * (
                cell_width
                + COLUMN_GAP
            )
        )

        cell_y = (
            CONTENT_TOP
            + row
            * (
                cell_height
                + ROW_GAP
            )
        )

        image_width, image_height = (
            image.size
        )

        image_x = (
            cell_x
            + (
                cell_width
                - image_width
            )
            // 2
        )

        # Centre the cover only inside its cover area.
        image_y = (
            cell_y
            + (
                cover_area_height
                - image_height
            )
            // 2
        )

        shadow = Image.new(
            "RGBA",
            image.size,
            (50, 50, 50, 180),
        )

        shadow = shadow.filter(
            ImageFilter.GaussianBlur(
                radius=5
            )
        )

        collage.paste(
            shadow,
            (
                image_x + 9,
                image_y + 9,
            ),
            shadow,
        )

        collage.paste(
            image,
            (
                image_x,
                image_y,
            ),
            image,
        )

        star_size = max(
            24,
            min(
                50,
                round(image_height * 0.08),
            ),
        )

        rating_y = (
            image_y
            + image_height
            - star_size
            - 12
        )

        draw_rating(
            collage=collage,
            star_image=star_image,
            rating=book.rating,
            cell_x=cell_x,
            available_width=cell_width,
            y=rating_y,
            star_size=star_size,
        )

        if review_height <= 0:
            continue

        review_y = (
            cell_y
            + cover_area_height
            + review_top_gap
        )

        review_width = (
            cell_width - 24
        )

        review_font, lines, line_height = (
            fit_review_text(
                draw=draw,
                text=book.review or "",
                maximum_width=review_width,
                maximum_height=review_height,
                preferred_font_size=(
                    review_font_size
                ),
            )
        )

        if not lines:
            continue

        line_spacing = 8
        text_y = review_y

        for line in lines:
            draw_centered_text(
                draw=draw,
                text=line,
                center_x=(
                    cell_x
                    + cell_width // 2
                ),
                y=text_y,
                font=review_font,
                shadow_offset=2,
            )

            text_y += (
                line_height
                + line_spacing
            )

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    collage.save(
        output_path,
        quality=95,
        subsampling=0,
    )

    print(
        f"Collage saved to {output_path} "
        f"using {number_of_books} books."
    )

    return output_path