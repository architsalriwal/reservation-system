"""Self-contained inline-SVG product icons for demo/seed data.

Used instead of hotlinked stock photos so the catalog never depends on an
external image host being up - each icon is a data: URI baked directly into
Product.image_url, so there's zero runtime network dependency for images.
"""

import urllib.parse

ICON_PATHS = {
    "headphones": """
        <path d="M110 210 v-30 a90 90 0 0 1 180 0 v30" />
        <rect x="90" y="200" width="45" height="80" rx="18" />
        <rect x="265" y="200" width="45" height="80" rx="18" />
    """,
    "sneaker": """
        <path d="M80 260 h230 a20 20 0 0 0 20-20 c0-15-10-24-24-28
                 l-40-14 -18-40 c-6-14-18-22-32-22 h-70
                 c-10 0-19 5-24 14 l-16 28 -46 18
                 a26 26 0 0 0-16 24 v20 a20 20 0 0 0 20 20 z" />
        <path d="M120 154 l16 46 M170 146 l14 54 M220 146 l10 58" />
    """,
    "smartwatch": """
        <rect x="130" y="120" width="140" height="160" rx="28" />
        <path d="M165 120 l-8-40 h86 l-8 40 M165 280 l-8 40 h86 l-8-40" />
        <path d="M200 165 v40 l28 20" />
    """,
    "keyboard": """
        <rect x="60" y="140" width="280" height="120" rx="16" />
        <path d="M90 175 h20 M130 175 h20 M170 175 h20 M210 175 h20 M250 175 h20 M290 175 h20
                 M90 210 h20 M130 210 h20 M170 210 h100 M290 210 h20
                 M90 235 h240" />
    """,
    "backpack": """
        <path d="M140 120 a60 50 0 0 1 120 0 v10" />
        <rect x="100" y="130" width="200" height="170" rx="30" />
        <path d="M100 190 h200 M150 190 v-30 a10 10 0 0 1 10-10 h80
                 a10 10 0 0 1 10 10 v30" />
    """,
    "mug": """
        <path d="M110 130 h140 v110 a55 55 0 0 1-110 0 v-110 z" />
        <path d="M250 155 a45 45 0 0 1 0 90 h-10" />
        <path d="M140 100 q10-20 0-40 M180 100 q10-20 0-40 M220 100 q10-20 0-40" />
    """,
    "lamp": """
        <path d="M140 130 l50-40 l50 40 z" />
        <path d="M190 90 v-20 M190 130 v110 M150 280 h80" />
        <circle cx="190" cy="245" r="16" />
    """,
    "bottle": """
        <path d="M170 90 h40 v35 c25 15 35 35 35 60 v90
                 a20 20 0 0 1-20 20 h-70
                 a20 20 0 0 1-20-20 v-90
                 c0-25 10-45 35-60 z" />
        <path d="M160 220 h60" />
    """,
}

GRADIENTS = {
    "headphones": ("#818cf8", "#4f46e5"),
    "sneaker": ("#fb923c", "#ea580c"),
    "smartwatch": ("#34d399", "#059669"),
    "keyboard": ("#a78bfa", "#7c3aed"),
    "backpack": ("#f472b6", "#db2777"),
    "mug": ("#fbbf24", "#d97706"),
    "lamp": ("#60a5fa", "#2563eb"),
    "bottle": ("#2dd4bf", "#0d9488"),
}


def product_icon_data_uri(icon_key):
    c1, c2 = GRADIENTS[icon_key]
    path = ICON_PATHS[icon_key]
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 400">
  <defs>
    <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="{c1}"/>
      <stop offset="1" stop-color="{c2}"/>
    </linearGradient>
  </defs>
  <rect width="400" height="400" fill="url(#g)"/>
  <g fill="none" stroke="white" stroke-width="9" stroke-linecap="round" stroke-linejoin="round" opacity="0.95">
    {path}
  </g>
</svg>"""
    return f"data:image/svg+xml,{urllib.parse.quote(svg)}"
