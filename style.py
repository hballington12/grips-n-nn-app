"""Tokyo Night–inspired high-contrast theme for GRIPS Spectra Viewer.

PyQt uses QSS (Qt Style Sheets) — a CSS-like syntax that styles widgets.
Key differences from CSS:
  - Selectors target Qt class names (QFrame, QLabel, QPushButton, etc.)
  - Properties are a subset of CSS (no flexbox, grid, etc.)
  - Use :: for sub-controls (e.g. QScrollBar::handle)
  - Use : for pseudo-states (e.g. QPushButton:hover)
"""

# -- Color palette (Tokyo Night, high-contrast variant) --------------------

COLORS = {
    # Backgrounds — darkest to lightest
    "bg_base": "#1a1b26",       # main window background
    "bg_surface": "#16161e",    # panel/sidebar background
    "bg_input": "#14141b",      # input fields, inset areas
    "bg_highlight": "#1f2335",  # hovered/selected row background

    # Borders
    "border": "#29355a",        # panel borders (brighter than default TN for contrast)
    "border_focus": "#7aa2f7",  # focused widget border

    # Text — bumped up for high contrast
    "text_primary": "#c0caf5",  # main readable text
    "text_secondary": "#a9b1d6",  # labels, descriptions
    "text_muted": "#787c99",    # placeholders, disabled
    "text_bright": "#e0e4f7",   # headings, emphasis

    # Accent colors
    "accent": "#7aa2f7",        # primary accent (blue)
    "accent_secondary": "#bb9af7",  # secondary accent (purple)
    "green": "#9ece6a",         # success, good values
    "teal": "#73daca",          # info highlights
    "orange": "#ff9e64",        # warnings, attention
    "red": "#db4b4b",           # errors
    "yellow": "#e0af68",        # caution
}


# -- Stylesheet ------------------------------------------------------------

def build_stylesheet() -> str:
    """Generate the full application stylesheet from the color palette."""
    c = COLORS
    return f"""
    /* --- Global defaults --- */
    QMainWindow, QWidget {{
        background-color: {c["bg_base"]};
        color: {c["text_primary"]};
        font-family: "Segoe UI", "Noto Sans", "Ubuntu", sans-serif;
        font-size: 13px;
    }}

    /* --- Panels (QFrame with StyledPanel) --- */
    QFrame[frameShape="5"] {{
        background-color: {c["bg_surface"]};
        border: 1px solid {c["border"]};
        border-radius: 4px;
    }}

    /* --- Panel title labels --- */
    QLabel {{
        color: {c["text_bright"]};
        font-weight: bold;
        font-size: 14px;
        border: none;
        background: transparent;
    }}

    /* --- Splitter drag handles --- */
    QSplitter::handle {{
        background-color: {c["bg_base"]};
    }}
    QSplitter::handle:horizontal {{
        width: 4px;
    }}
    QSplitter::handle:vertical {{
        height: 4px;
    }}
    QSplitter::handle:hover {{
        background-color: {c["accent"]};
    }}

    /* --- Buttons (for later use) --- */
    QPushButton {{
        background-color: {c["bg_highlight"]};
        color: {c["text_primary"]};
        border: 1px solid {c["border"]};
        border-radius: 4px;
        padding: 6px 16px;
    }}
    QPushButton:hover {{
        background-color: {c["accent"]};
        color: {c["bg_base"]};
    }}
    QPushButton:pressed {{
        background-color: {c["accent_secondary"]};
    }}

    /* --- Input fields (for later use) --- */
    QLineEdit, QSpinBox, QComboBox {{
        background-color: {c["bg_input"]};
        color: {c["text_primary"]};
        border: 1px solid {c["border"]};
        border-radius: 3px;
        padding: 4px 8px;
    }}
    QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{
        border-color: {c["border_focus"]};
    }}

    /* --- Table views --- */
    QTableView {{
        background-color: {c["bg_surface"]};
        alternate-background-color: {c["bg_highlight"]};
        color: {c["text_primary"]};
        border: 1px solid {c["border"]};
        border-radius: 3px;
        gridline-color: transparent;
        font-size: 13px;
        font-weight: normal;
    }}
    QTableView::item {{
        padding: 4px 6px;
        border: none;
    }}
    QTableView::item:selected {{
        background-color: {c["accent"]};
        color: {c["bg_base"]};
    }}

    /* --- Table header --- */
    QHeaderView::section {{
        background-color: {c["bg_input"]};
        color: {c["text_secondary"]};
        border: none;
        border-bottom: 1px solid {c["border"]};
        border-right: 1px solid {c["border"]};
        padding: 4px 6px;
        font-size: 12px;
        font-weight: bold;
    }}
    QHeaderView::section:hover {{
        color: {c["text_bright"]};
    }}
    /* Sort indicator arrow */
    QHeaderView::down-arrow {{
        image: none;
        subcontrol-position: center right;
    }}
    QHeaderView::up-arrow {{
        image: none;
        subcontrol-position: center right;
    }}

    /* --- Sliders --- */
    QSlider::groove:horizontal {{
        background: {c["bg_input"]};
        height: 4px;
        border-radius: 2px;
    }}
    QSlider::handle:horizontal {{
        background: {c["accent"]};
        width: 14px;
        height: 14px;
        margin: -5px 0;
        border-radius: 7px;
    }}
    QSlider::handle:horizontal:hover {{
        background: {c["accent_secondary"]};
    }}
    QSlider::sub-page:horizontal {{
        background: {c["accent"]};
        border-radius: 2px;
    }}

    /* --- Scroll bars --- */
    QScrollBar:vertical {{
        background: {c["bg_surface"]};
        width: 10px;
        border: none;
    }}
    QScrollBar::handle:vertical {{
        background: {c["border"]};
        border-radius: 5px;
        min-height: 20px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {c["accent"]};
    }}
    QScrollBar::add-line, QScrollBar::sub-line {{
        height: 0px;
    }}
    """
